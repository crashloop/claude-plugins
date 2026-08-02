import json
import httpx
from hoolint.findings import Finding
from hoolint.strategies.base import Context
from hoolint.strategies.local_llm import LocalLLMStrategy

STAGE = {"model": "qwen3:4b", "prompt": "Judge: {span}"}


def _ctx(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("# a\n# b\n# c\nx = 1\n")
    return Context(path=f, root=tmp_path, mode="session", settings={},
                   rule_id="verbose-comments", severity="block")


def _cand():
    return Finding(rule_id="verbose-comments", file="m.py", start_line=1,
                   end_line=3, span_text="# a\n# b\n# c\n", message="verbose")


def _transport(reply, calls=None):
    def handler(request):
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert body["model"] == "qwen3:4b"
        if calls is not None:
            calls.append(body)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": reply}}]})
    return httpx.MockTransport(handler)


def test_violation_kept_ok_dropped(tmp_path):
    ctx = _ctx(tmp_path)
    strat = LocalLLMStrategy(transport=_transport("[0] VIOLATION: restates code"))
    assert len(strat.run([_cand()], STAGE, ctx)) == 1
    strat = LocalLLMStrategy(transport=_transport("[0] OK: adds context"))
    assert strat.run([_cand()], STAGE, ctx) == []


def test_candidates_batched_into_one_request(tmp_path):
    """Wall time must not scale with candidate count."""
    ctx = _ctx(tmp_path)
    calls = []
    strat = LocalLLMStrategy(
        transport=_transport("[0] VIOLATION: x\n[1] OK: y", calls))
    kept = strat.run([_cand(), _cand()], STAGE, ctx)
    assert len(calls) == 1
    assert len(kept) == 1


def test_unreachable_endpoint_passes_through_and_disarms(tmp_path):
    ctx = _ctx(tmp_path)
    def boom(request):
        raise httpx.ConnectError("refused")
    strat = LocalLLMStrategy(transport=httpx.MockTransport(boom))
    cand = _cand()
    assert strat.run([cand], STAGE, ctx) == [cand]
    assert any("unreachable" in n for n in ctx.notes)
    assert ctx.filter_skipped is True


def test_http_status_error_is_not_reported_as_unreachable(tmp_path):
    """A wrong model name must not send the user debugging their server."""
    ctx = _ctx(tmp_path)
    def not_found(request):
        return httpx.Response(404, json={"error": "model 'qwen3:4b' not found"})
    strat = LocalLLMStrategy(transport=httpx.MockTransport(not_found))
    cand = _cand()
    assert strat.run([cand], STAGE, ctx) == [cand]
    assert any("404" in n and "not found" in n for n in ctx.notes)
    assert not any("unreachable" in n for n in ctx.notes)


def test_non_local_base_url_refused(tmp_path, monkeypatch):
    """Project config must not be able to exfiltrate file content."""
    monkeypatch.delenv("HOOLINT_LLM_BASE_URL", raising=False)
    ctx = _ctx(tmp_path)
    called = []
    def handler(request):
        called.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
    strat = LocalLLMStrategy(transport=httpx.MockTransport(handler))
    stage = {**STAGE, "base_url": "https://evil.example.com/v1"}
    cand = _cand()
    assert strat.run([cand], stage, ctx) == [cand]
    assert called == []
    assert any("refused non-local" in n for n in ctx.notes)


def test_reasoning_effort_forwarded_when_the_rule_sets_it(tmp_path):
    """A rule cheap enough to need no deliberation must be able to say so."""
    ctx = _ctx(tmp_path)
    calls = []
    strat = LocalLLMStrategy(transport=_transport("[0] VIOLATION: x", calls))
    strat.run([_cand()], {**STAGE, "reasoning_effort": "none"}, ctx)
    assert calls[0]["reasoning_effort"] == "none"


def test_reasoning_effort_omitted_when_the_rule_does_not_set_it(tmp_path):
    """Endpoints that reject unknown fields must not see it by default."""
    ctx = _ctx(tmp_path)
    calls = []
    strat = LocalLLMStrategy(transport=_transport("[0] VIOLATION: x", calls))
    strat.run([_cand()], STAGE, ctx)
    assert "reasoning_effort" not in calls[0]


def test_candidate_cap_skips_rather_than_hanging(tmp_path):
    ctx = _ctx(tmp_path)
    strat = LocalLLMStrategy(transport=_transport("[0] VIOLATION: x"))
    cands = [_cand() for _ in range(11)]
    assert strat.run(cands, {**STAGE, "max_candidates": 10}, ctx) == cands
    assert any("budget exhausted" in n for n in ctx.notes)


def test_malformed_reply_drops_unclear_candidates_without_crashing(tmp_path):
    """No verdict lines at all: nothing can be confirmed VIOLATION, so nothing
    is kept. A malformed reply must never cause an un-vetted finding to block.
    """
    ctx = _ctx(tmp_path)
    strat = LocalLLMStrategy(transport=_transport("not a verdict line at all"))
    assert strat.run([_cand()], STAGE, ctx) == []


def test_verdict_containing_but_not_starting_with_violation_is_not_kept(tmp_path):
    """'NOT A VIOLATION' contains the substring 'VIOLATION' but is not one;
    a naive substring check would wrongly keep (and block on) this candidate.
    """
    ctx = _ctx(tmp_path)
    strat = LocalLLMStrategy(transport=_transport("[0] NOT A VIOLATION: fine"))
    assert strat.run([_cand()], STAGE, ctx) == []


def test_malformed_json_response_skips_and_disarms(tmp_path):
    """Response shape the client doesn't expect (e.g. no choices) must not
    crash; it degrades like any other filter failure."""
    ctx = _ctx(tmp_path)
    def bad_shape(request):
        return httpx.Response(200, json={"unexpected": "shape"})
    strat = LocalLLMStrategy(transport=httpx.MockTransport(bad_shape))
    cand = _cand()
    assert strat.run([cand], STAGE, ctx) == [cand]
    assert ctx.filter_skipped is True


def test_public_address_refused_even_when_dns_returns_mixed_results(tmp_path,
                                                                      monkeypatch):
    """A DNS-rebinding-style host resolving to both a private and a public IP
    must be refused: every returned address is checked, not just the first.
    """
    import socket
    from hoolint.strategies import local_llm as mod

    def fake_getaddrinfo(host, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.5", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0)),
        ]
    monkeypatch.setattr(mod.socket, "getaddrinfo", fake_getaddrinfo)
    assert mod._resolve_pinned_ip("http://mixed.example.com/v1") is None


def test_dns_resolution_failure_fails_closed(monkeypatch):
    """A hostname that fails to resolve is refused, not allowed by default."""
    import socket
    from hoolint.strategies import local_llm as mod

    def fake_getaddrinfo(host, port):
        raise socket.gaierror("name or service not known")
    monkeypatch.setattr(mod.socket, "getaddrinfo", fake_getaddrinfo)
    assert mod._resolve_pinned_ip("http://does-not-resolve.example.com/v1") is None


def test_null_content_reply_skips_and_disarms_instead_of_crashing(tmp_path):
    """Ollama can return `"content": null` for an empty completion. This
    passes the KeyError/IndexError/ValueError guard untouched (every key is
    present, the value is just None), so it must be caught separately or
    `_apply_verdicts` crashes on `None.splitlines()`.
    """
    ctx = _ctx(tmp_path)
    def null_content(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": None}}]})
    strat = LocalLLMStrategy(transport=httpx.MockTransport(null_content))
    cand = _cand()
    assert strat.run([cand], STAGE, ctx) == [cand]
    assert ctx.filter_skipped is True
    assert any("malformed reply" in n for n in ctx.notes)


def test_real_path_pins_connection_to_the_validated_ip(tmp_path, monkeypatch):
    """The real (non-injected-transport) path must connect to the address
    that was just validated, not let httpx re-resolve the hostname at
    connect time - otherwise a hostile DNS server could answer the
    validation lookup and the connection lookup differently (TOCTOU / DNS
    rebinding), defeating the whole guard. No real socket is ever opened:
    getaddrinfo and the innermost transport are both faked.
    """
    import socket
    from hoolint.strategies import local_llm as mod

    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
    monkeypatch.setattr(mod.socket, "getaddrinfo", fake_getaddrinfo)

    seen = {}
    class _FakeInner(httpx.BaseTransport):
        def handle_request(self, request):
            seen["url_host"] = request.url.host
            seen["host_header"] = request.headers.get("host")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "[0] OK: fine"}}]})

    real_cls = mod._PinnedIPTransport
    monkeypatch.setattr(
        mod, "_PinnedIPTransport",
        lambda pinned_ip: real_cls(pinned_ip, inner=_FakeInner()))
    # conftest pins this env var to a closed port for every other test;
    # override it here so the pinning under test sees a hostname base_url.
    monkeypatch.delenv("HOOLINT_LLM_BASE_URL", raising=False)

    ctx = _ctx(tmp_path)
    strat = LocalLLMStrategy(transport=None)
    stage = {**STAGE, "base_url": "http://localhost:11434/v1"}
    strat.run([_cand()], stage, ctx)

    assert seen["url_host"] == "127.0.0.1"
    assert seen["host_header"] == "localhost:11434"
