"""An OpenAI-shaped `/v1/chat/completions` backed by a real `claude -p` process.

Why this exists: hoolint's `local_llm` stage speaks OpenAI and is pinned to
loopback, so on a machine without a usable GPU there is no way to exercise a
judge stage at all. This serves that endpoint and answers it by shelling out to
the Claude Code CLI already authenticated on this box.

Two boundaries this deliberately does NOT cross:

- It is a benchmark harness, not a hoolint feature. Pointing `local_llm` here
  forwards file spans to Anthropic, which is precisely what `_resolve_pinned_ip`
  exists to prevent. Nothing in the hoolint package references it.
- It is not for the Stop hook. Measured on this machine a judging prompt takes
  15.7s to 31s, so it belongs in git mode and in precision measurement. In
  session mode use the `escalate` stage, which costs nothing extra because the
  session model is already running.
"""
import asyncio
import os
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

DEFAULT_MODEL = os.environ.get("JUDGE_PROXY_MODEL", "haiku")
TIMEOUT_S = float(os.environ.get("JUDGE_PROXY_TIMEOUT", "120"))

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


async def _run_claude(prompt: str, model: str) -> tuple[int, str, str]:
    """Run one `claude -p`, feeding the prompt on stdin.

    stdin rather than argv: prompts carry code spans with quotes, newlines and
    backslashes, and argv has both a length ceiling and a quoting hazard.

    Tools are disabled and turns capped at one. The judge is asked to rule on the
    text it was given, and a judge that can read the filesystem could reach past
    the span it is judging.

    Returns:
        (returncode, stdout, stderr), all decoded.
    """
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", "--model", model, "--allowed-tools", "",
        "--max-turns", "1", "--append-system-prompt", VERDICT_FORMAT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(prompt.encode()), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", f"claude -p exceeded {TIMEOUT_S}s"
    return (proc.returncode or 0, out.decode(errors="replace"),
            err.decode(errors="replace"))


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Answer an OpenAI chat completion by running the Claude Code CLI.

    Only the fields hoolint reads are populated. `model` from the request is
    ignored unless it names a Claude model: rules configure names like
    `qwen3:4b`, which would be meaningless to the CLI.
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

    started = time.monotonic()
    code, out, err = await _run_claude(_prompt_from(messages), model)
    if code != 0:
        # 502 rather than a 200 with empty content: hoolint treats an HTTP error
        # as "judge unavailable" and demotes the rule to advisory, whereas an
        # empty 200 would read as "every candidate cleared".
        return JSONResponse(status_code=502, content={
            "error": {"type": "api_error",
                      "message": f"claude -p failed ({code}): {err.strip()[:300]}"}})

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": out.strip()}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "x_judge_proxy": {"seconds": round(time.monotonic() - started, 1)},
    }
