import numpy as np
from hoolint.findings import Finding
from hoolint.strategies.base import Context
from hoolint.strategies.semantic import SemanticStrategy


class FakeEncoder:
    """Maps known texts to fixed vectors; everything else orthogonal."""
    def __init__(self, mapping):
        self.mapping = mapping
    def encode(self, texts):
        return np.array([self.mapping.get(t.strip(), [0.0, 0.0, 1.0])
                         for t in texts])


def _ctx(tmp_path, body):
    f = tmp_path / "m.py"
    f.write_text(body)
    return f, Context(path=f, root=tmp_path, mode="session", settings={},
                      rule_id="verbose-comments", severity="block")


def _cand(f, span, start=1):
    end = start + span.rstrip("\n").count("\n")
    return Finding(rule_id="verbose-comments", file=f.name, start_line=start,
                   end_line=end, span_text=span, message="verbose")


def test_redundant_comment_kept_distinct_dropped(tmp_path):
    span = "# adds one\n# to the number\n# and returns it\n"
    body = span + "def add_one(n):\n    return n + 1\n"
    f, ctx = _ctx(tmp_path, body)
    same = [1.0, 0.0, 0.0]
    enc = FakeEncoder({span.strip(): same,
                       "def add_one(n):\n    return n + 1": same})
    strat = SemanticStrategy(encoder=enc)
    kept = strat.run([_cand(f, span)], {"threshold": 0.6}, ctx)
    assert len(kept) == 1                      # redundant with code -> kept
    other = "# licensed under MIT\n# see LICENSE\n# for details\n"
    kept = strat.run([_cand(f, other)], {"threshold": 0.6}, ctx)
    assert kept == []                          # orthogonal to code -> dropped


def test_not_ready_passes_through_and_disarms_blocking(tmp_path, monkeypatch):
    """A skipped filter must not let its survivors block."""
    f, ctx = _ctx(tmp_path, "# a\n# b\n# c\nx = 1\n")
    monkeypatch.setattr("hoolint.strategies.semantic.model_ready", lambda: False)
    strat = SemanticStrategy()
    cand = _cand(f, "# a\n# b\n# c\n")
    assert strat.run([cand], {}, ctx) == [cand]
    assert any("warming up" in n for n in ctx.notes)
    assert ctx.filter_skipped is True


def test_trailing_comment_uses_preceding_code(tmp_path):
    """A comment block at EOF is judged against the code above it."""
    from hoolint.strategies.semantic import _adjacent_code
    text = "def add_one(n):\n    return n + 1\n# adds one\n# to n\n# returns it\n"
    assert "return n + 1" in _adjacent_code(text, start_line=3, end_line=5)
