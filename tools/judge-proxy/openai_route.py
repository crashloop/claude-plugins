"""An OpenAI-shaped `/v1/chat/completions` backed by a real `claude -p` process.

Why this exists: hoolint's `local_llm` stage speaks OpenAI and is pinned to
loopback, so on a machine without a usable GPU there is no way to exercise a
judge stage at all. This serves that endpoint and answers it by shelling out to
the Claude Code CLI already authenticated on this box.

Two boundaries this deliberately does NOT cross:

- It is a benchmark harness, not a hoolint feature. Pointing `local_llm` here
  forwards file spans to Anthropic, which is precisely what `_resolve_pinned_ip`
  exists to prevent. Nothing in the hoolint package references it.
- It is not for the Stop hook. Even judged with thinking off a call costs
  seconds, so it belongs in git mode and in precision measurement. In session
  mode use the `escalate` stage, which costs nothing extra because the session
  model is already running.
"""
import asyncio
import json
import os
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

DEFAULT_MODEL = os.environ.get("JUDGE_PROXY_MODEL", "haiku")
TIMEOUT_S = float(os.environ.get("JUDGE_PROXY_TIMEOUT", "120"))

# Thinking is the latency budget, not the prompt size. Measured over 3 runs on
# this box: thinking on costs 19.5-33.8s wall and 645-992 output tokens for a
# one-line verdict; MAX_THINKING_TOKENS=0 costs 1.9-2.4s of API time and 67-88
# tokens, same verdict. A rule that needs no deliberation says so by sending
# `reasoning_effort`. `--effort low` was measured and changed nothing.
_NO_THINKING = {"none", "minimal"}

# The default system prompt carries ~35k tokens of Claude Code chrome, the
# operator's CLAUDE.md and their hook output, against a judging prompt of ~10.
# That is cost, but mainly contamination: the judge should rule on the span it
# was given, not inherit whatever the operator told their session model to
# prefer. Replacing it cuts the prefill to ~7.5k. Latency was unchanged, so this
# is a correctness and cost change, not a speed one.
BASE_ARGS = ["-p", "--input-format", "stream-json", "--output-format",
             "stream-json", "--verbose", "--max-turns", "1", "--tools", "",
             "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']

# Without this the CLI answers in prose ("I need to see the test code context...")
# and hoolint's verdict regex matches nothing, so every candidate is silently
# dropped. A dropped candidate never blocks, so the failure looks like a clean
# check rather than a judge that did not run. Hence the format is enforced here
# rather than left to each rule's prompt.
VERDICT_FORMAT = (
    "You are a lint verdict engine. Output ONLY one line per numbered item, "
    "formatted exactly `[N] VIOLATION: reason` or `[N] OK: reason`. No preamble, "
    "no markdown, no bold, no blank lines, no trailing commentary. Judge on the "
    "evidence given; never ask for more context."
)


class _Judge:
    """One CLI process in streaming mode, booted before the request needs it.

    Streaming input rather than a plain `-p` pipe because the process must be
    able to sit idle after boot and take its prompt later. Measured: boot is
    2.2-3.4s and swings to 14s under load, while a booted process answers in
    4-5s and does not degrade over an 8s idle. A plain `-p` pipe cannot be
    prewarmed at all: it does its work only once stdin closes, and one probe run
    returned no result when stdin was held open.
    """

    def __init__(self, model: str, no_thinking: bool):
        self.key = (model, no_thinking)
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        """Spawn and block until the CLI announces the session is up."""
        env = dict(os.environ)
        if self.key[1]:
            env["MAX_THINKING_TOKENS"] = "0"
        self._proc = await asyncio.create_subprocess_exec(
            "claude", *BASE_ARGS, "--model", self.key[0],
            "--system-prompt", VERDICT_FORMAT,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env)
        line = await asyncio.wait_for(self._proc.stdout.readline(), TIMEOUT_S)
        if b'"init"' not in line and b'"system"' not in line:
            raise RuntimeError(f"no init line from claude: {line[:200]!r}")

    async def ask(self, prompt: str) -> str:
        """Send one prompt and read until the CLI reports a result.

        Raises:
            RuntimeError: The process died or ended the stream without a result.
        """
        proc = self._proc
        msg = json.dumps({"type": "user", "message": {
            "role": "user", "content": [{"type": "text", "text": prompt}]}})
        proc.stdin.write((msg + "\n").encode())
        await proc.stdin.drain()

        # `result.result` has come back empty in probing, so assistant text is
        # accumulated as it streams and used as the fallback.
        chunks: list[str] = []
        while True:
            line = await proc.stdout.readline()
            if not line:
                err = (await proc.stderr.read())[:300].decode(errors="replace")
                raise RuntimeError(f"claude ended without a result: {err.strip()}")
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "assistant":
                for part in event.get("message", {}).get("content", []):
                    if part.get("type") == "text":
                        chunks.append(part.get("text", ""))
            elif event.get("type") == "result":
                return str(event.get("result") or "".join(chunks))

    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def kill(self) -> None:
        if self.alive():
            self._proc.kill()


# A pool, not one spare: several rules judge at once and their (model, thinking)
# keys differ, so one slot would be killed and rebooted on every other request.
SPARES = max(0, int(os.environ.get("JUDGE_PROXY_SPARES", "4")))
_pool: list[_Judge] = []        # oldest boot first
_lock = asyncio.Lock()
# asyncio keeps only a weak reference to a running task, so a fire-and-forget
# prewarm can be collected mid-boot. Holding it here is what makes it happen.
_warming: set[asyncio.Task] = set()


async def _warm(model: str, no_thinking: bool) -> None:
    """Boot a spare and park it, evicting the oldest if the pool is full.

    Args:
        model: Model name the spare is booted with.
        no_thinking: Whether the spare runs with thinking disabled.
    """
    if SPARES <= 0:
        return
    judge = _Judge(model, no_thinking)
    try:
        await judge.start()
    except (OSError, RuntimeError, asyncio.TimeoutError):
        return  # Prewarming is an optimisation; a failure must not fail a request.
    async with _lock:
        while _pool and len(_pool) >= SPARES:
            _pool.pop(0).kill()
        _pool.append(judge)


async def _take(model: str, no_thinking: bool) -> tuple[_Judge, bool]:
    """Return a ready process, reusing a parked spare when one matches.

    Args:
        model: Model name the request wants.
        no_thinking: Whether the request wants thinking disabled.

    Returns:
        The judge to serve this request, and whether it came from the pool.
    """
    key = (model, no_thinking)
    async with _lock:
        # Sweep the whole list, not just up to the first key match: a dead entry
        # of another key would otherwise hold a cap slot forever.
        for judge in list(_pool):
            if not judge.alive():
                judge.kill()
                _pool.remove(judge)
        for judge in _pool:
            if judge.key == key:
                _pool.remove(judge)
                return judge, True
    # Booting outside the lock: holding it across a 3s boot would serialize
    # every concurrent request behind the first, which is what this pool fixes.
    fresh = _Judge(model, no_thinking)
    await fresh.start()
    return fresh, False


async def _startup() -> None:
    """Park one spare before the first request, guessing the common key.

    Rules that judge through this proxy are expected to set
    `reasoning_effort = "none"`, so that is the guess. The remaining slots fill
    from real traffic, since the keys in use are not knowable in advance.
    """
    await _warm(DEFAULT_MODEL, no_thinking=True)


def _shutdown() -> None:
    """Kill every parked spare so uvicorn leaves no orphan CLI behind."""
    while _pool:
        _pool.pop().kill()


router.add_event_handler("startup", _startup)
router.add_event_handler("shutdown", _shutdown)


def _flatten(content) -> str:
    """Accept both a plain string and OpenAI's list-of-parts content shape."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict))
    return str(content)


def _prompt_from(messages: list) -> str:
    """Join every message into one prompt, keeping role order.

    hoolint sends a single user message, but joining rather than taking the last
    means a caller that sends a system turn does not lose it silently.
    """
    return "\n\n".join(f"{m.get('role', 'user')}: {_flatten(m.get('content', ''))}"
                       for m in messages)


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Answer an OpenAI chat completion by running the Claude Code CLI.

    Only the fields hoolint reads are populated. `model` from the request is
    ignored unless it names a Claude model: rules configure names like
    `qwen3:4b`, which would be meaningless to the CLI. `reasoning_effort` is
    honoured as an on/off switch, since only "off" measured as different.
    """
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={
            "error": {"type": "invalid_request_error", "message": "body is not JSON"}})

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return JSONResponse(status_code=400, content={
            "error": {"type": "invalid_request_error", "message": "messages is required"}})

    requested = str(body.get("model", ""))
    model = requested if requested.startswith(("claude", "haiku", "sonnet", "opus")) \
        else DEFAULT_MODEL
    no_thinking = str(body.get("reasoning_effort", "")).lower() in _NO_THINKING

    started = time.monotonic()
    try:
        judge, warm = await _take(model, no_thinking)
    except (OSError, RuntimeError, asyncio.TimeoutError) as exc:
        return JSONResponse(status_code=502, content={
            "error": {"type": "api_error", "message": f"claude failed to start: {exc}"}})

    try:
        out = await asyncio.wait_for(
            judge.ask(_prompt_from(messages)), timeout=TIMEOUT_S)
    except (asyncio.TimeoutError, RuntimeError) as exc:
        # 502 rather than a 200 with empty content: hoolint treats an HTTP error
        # as "judge unavailable" and demotes the rule to advisory, whereas an
        # empty 200 would read as "every candidate cleared".
        detail = f"timed out after {TIMEOUT_S}s" if isinstance(
            exc, asyncio.TimeoutError) else str(exc)[:300]
        return JSONResponse(status_code=502, content={
            "error": {"type": "api_error", "message": f"claude -p failed: {detail}"}})
    finally:
        # One prompt per process: a reused session would carry the previous
        # file's verdicts into the next judgment and grow the prompt each call.
        judge.kill()
        task = asyncio.create_task(_warm(model, no_thinking))
        _warming.add(task)
        task.add_done_callback(_warming.discard)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": out.strip()}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "x_judge_proxy": {"seconds": round(time.monotonic() - started, 1),
                          "thinking": not no_thinking},
    }
