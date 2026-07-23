"""Judge candidates via a local OpenAI-compatible endpoint (Ollama, vLLM...).

Never a cloud provider. That is enforced, not assumed: project config supplies
base_url, so an unvalidated host would let any repo exfiltrate file content on
the next Stop hook.
"""
import ipaddress
import os
import re
import socket
import time
from urllib.parse import urlparse

import httpx

from hoolint.findings import Finding
from hoolint.strategies.base import Context

DEFAULT_BASE = "http://localhost:11434/v1"
_VERDICT = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")


def is_local(base_url: str) -> bool:
    """True iff every address the host resolves to is loopback, private, or
    link-local.

    Fails closed: an empty host, a resolution error, an empty result, or any
    single address (among several) that is public all refuse the endpoint.
    A hostname that resolves to both a private and a public address (e.g. a
    DNS-rebinding attempt) is refused, since every address is checked.

    Args:
        base_url: The configured or overridden endpoint URL.

    Returns:
        True iff the host is safe to send file content to.
    """
    try:
        host = urlparse(base_url).hostname
        if not host:
            return False
        infos = socket.getaddrinfo(host, None)
        if not infos:
            return False
        return all(
            (ip := ipaddress.ip_address(info[4][0])).is_loopback
            or ip.is_private or ip.is_link_local
            for info in infos)
    except (OSError, ValueError):
        return False


class LocalLLMStrategy:
    """Filter stage: keeps only candidates a local LLM judges real violations."""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Judge one file's candidates in a single batched request.

        Args:
            candidates: Prior-stage findings to filter, or None (never generates).
            stage: Stage config: base_url, model, prompt, timeout, max_candidates,
                budget_seconds.
            ctx: Per-file execution context.

        Returns:
            Candidates the model confirmed as violations. On any failure, all
            candidates pass through unfiltered and the filter is disarmed via
            `ctx.skip_filter`, so survivors demote to warn rather than block
            on an un-vetted finding.
        """
        if candidates is None:
            return []
        if not candidates:
            return []

        base = os.environ.get("HOOLINT_LLM_BASE_URL") or stage.get(
            "base_url", DEFAULT_BASE)
        if not is_local(base):
            ctx.skip_filter(f"local_llm refused non-local endpoint: {base}")
            return candidates

        cap = stage.get("max_candidates", 10)
        if len(candidates) > cap:
            ctx.skip_filter(
                f"local_llm skipped (budget exhausted: {len(candidates)} "
                f"candidates > max {cap})")
            return candidates

        deadline = time.monotonic() + stage.get("budget_seconds", 60)
        if time.monotonic() > deadline:
            ctx.skip_filter("local_llm skipped (budget exhausted)")
            return candidates

        # One request per file, not per candidate: wall time stays bounded.
        numbered = "\n\n".join(
            f"[{i}]\n{c.span_text}" for i, c in enumerate(candidates))
        prompt = stage["prompt"].format(span=numbered, code=ctx.content())

        with httpx.Client(base_url=base, transport=self._transport,
                          timeout=stage.get("timeout", 30)) as client:
            try:
                r = client.post("/chat/completions", json={
                    "model": stage["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                })
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:200]
                ctx.skip_filter(
                    f"local_llm skipped (HTTP {exc.response.status_code} "
                    f"from {base}: {body})")
                return candidates
            except httpx.HTTPError:
                ctx.skip_filter(f"local_llm skipped (endpoint unreachable: {base})")
                return candidates

            try:
                reply = r.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                ctx.skip_filter(
                    f"local_llm skipped (malformed reply from {base}: {exc})")
                return candidates

        return self._apply_verdicts(reply, candidates)

    def _apply_verdicts(self, reply: str, candidates: list[Finding]) -> list[Finding]:
        """Keep only candidates whose verdict line clearly starts with VIOLATION.

        A missing verdict, a garbled reply, or wording like "NOT A VIOLATION"
        (which contains the substring but isn't one) all resolve to dropped:
        an un-confirmed candidate must never block.
        """
        verdicts: dict[int, str] = {}
        for line in reply.splitlines():
            m = _VERDICT.match(line)
            if m:
                verdicts[int(m.group(1))] = m.group(2).strip()
        kept = []
        for i, c in enumerate(candidates):
            verdict = verdicts.get(i, "")
            if verdict.upper().startswith("VIOLATION"):
                c.notes.append(f"local_llm: {verdict[:120]}")
                kept.append(c)
        return kept
