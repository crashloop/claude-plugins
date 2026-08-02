"""Judge candidates via a local OpenAI-compatible endpoint (Ollama, vLLM...).

Never a cloud provider. That is enforced, not assumed: project config supplies
base_url, so an unvalidated host would let any repo exfiltrate file content on
the next Stop hook.
"""
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

import httpx

from hoolint.findings import Finding
from hoolint.strategies.base import Context

DEFAULT_BASE = "http://localhost:11434/v1"
_VERDICT = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")


def _resolve_pinned_ip(base_url: str) -> str | None:
    """Resolve the base URL's host once and return the address to connect to.

    Validation and connection must share one resolution: if they resolve
    separately (as a naive check-then-connect does), a hostname whose DNS an
    attacker controls can answer the check with a private IP and the
    connection with a public one (TOCTOU / DNS rebinding).

    Fails closed: an empty host, a resolution error, an empty result, or any
    single address (among several) that is public all refuse the endpoint.
    A hostname that resolves to both a private and a public address is
    refused, since every address is checked.

    Args:
        base_url: The configured or overridden endpoint URL.

    Returns:
        The resolved IP address to pin the connection to, or None if the
        host is not safe to send file content to.
    """
    try:
        host = urlparse(base_url).hostname
        if not host:
            return None
        infos = socket.getaddrinfo(host, None)
        if not infos:
            return None
        addrs = [ipaddress.ip_address(info[4][0]) for info in infos]
        if not all(ip.is_loopback or ip.is_private or ip.is_link_local for ip in addrs):
            return None
        return str(addrs[0])
    except (OSError, ValueError):
        return None


class _PinnedIPTransport(httpx.BaseTransport):
    """Routes a request to a pre-resolved IP instead of letting httpx
    re-resolve the hostname at connect time.

    The original Host header is preserved so the pinning is transparent to
    the server. `inner` defaults to a real `httpx.HTTPTransport`; tests
    inject a fake one to observe the rewritten request without a real
    connection.
    """

    def __init__(self, pinned_ip: str, inner: httpx.BaseTransport | None = None):
        self._pinned_ip = pinned_ip
        self._inner = inner if inner is not None else httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        original_host = request.headers.get("host", request.url.host)
        request.url = request.url.copy_with(host=self._pinned_ip)
        request.headers["host"] = original_host
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class LocalLLMStrategy:
    """Filter stage: keeps only candidates a local LLM judges real violations."""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Judge one file's candidates in a single batched request.

        Args:
            candidates: Prior-stage findings to filter, or None (never generates).
            stage: Stage config: base_url, model, prompt, timeout, max_candidates.
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
        pinned_ip = _resolve_pinned_ip(base)
        if pinned_ip is None:
            ctx.skip_filter(f"local_llm refused non-local endpoint: {base}")
            return candidates

        # Over the cap, judge the first N rather than nothing: skipping the
        # whole file gave the noisiest files the least scrutiny.
        cap = stage.get("max_candidates", 10)
        candidates, overflow = candidates[:cap], candidates[cap:]
        if overflow:
            ctx.skip_filter(
                f"local_llm judged the first {cap}, {len(overflow)} candidates "
                f"over the cap pass unjudged")
        if not candidates:
            return overflow

        # One request per file, not per candidate: wall time stays bounded.
        numbered = "\n\n".join(
            f"[{i}]\n{c.span_text}" for i, c in enumerate(candidates))
        prompt = stage["prompt"].format(span=numbered, code=ctx.content())

        payload = {
            "model": stage["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        # How hard the endpoint should think, when the rule knows. OpenAI's own
        # field name, so an endpoint that has no such control ignores it. Sent
        # only when set: some servers reject unknown fields outright.
        if "reasoning_effort" in stage:
            payload["reasoning_effort"] = stage["reasoning_effort"]

        # An injected transport (tests) is used as-is; the real path pins the
        # connection to the address that was just validated above.
        transport = self._transport or _PinnedIPTransport(pinned_ip)
        with httpx.Client(base_url=base, transport=transport,
                          timeout=stage.get("timeout", 30)) as client:
            try:
                r = client.post("/chat/completions", json=payload)
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:200]
                ctx.skip_filter(
                    f"local_llm skipped (HTTP {exc.response.status_code} "
                    f"from {base}: {body})")
                return candidates + overflow
            except httpx.HTTPError:
                ctx.skip_filter(f"local_llm skipped (endpoint unreachable: {base})")
                return candidates + overflow

            try:
                reply = r.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                ctx.skip_filter(
                    f"local_llm skipped (malformed reply from {base}: {exc})")
                return candidates + overflow

            if not isinstance(reply, str):
                ctx.skip_filter(
                    f"local_llm skipped (malformed reply from {base}: "
                    f"content was {type(reply).__name__}, not a string)")
                return candidates + overflow

        return self._apply_verdicts(reply, candidates) + overflow

    def _apply_verdicts(self, reply: str, candidates: list[Finding]) -> list[Finding]:
        """Keep only candidates whose verdict line clearly starts with VIOLATION.

        A missing verdict, a garbled reply, or wording like "NOT A VIOLATION"
        (which contains the substring but isn't one) all resolve to dropped:
        an un-confirmed candidate must never block.

        Args:
            reply: The model's raw text response, one `[i] verdict` line per
                candidate.
            candidates: The findings under judgment, indexed by position.

        Returns:
            The subset of candidates whose verdict starts with VIOLATION.
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
