"""Redundancy-with-code scoring via model2vec static embeddings.

Heuristic shortlist filter: a comment highly similar to its adjacent code
restates it. The escalate stage remains the judge.
"""
import os
import re
from pathlib import Path

import numpy as np

from hoolint.findings import Finding
from hoolint.strategies.base import Context

DEFAULT_MODEL = "minishlab/potion-base-8M"
_COMMENT = re.compile(r"^\s*#")


def marker_path() -> Path:
    """Ready-marker location; env-overridable so tests can isolate it."""
    base = os.environ.get("HOOLINT_CACHE_DIR")
    return (Path(base) if base else Path.home() / ".cache" / "hoolint") / "model-ready"


def model_ready() -> bool:
    return marker_path().exists()


def download_model(name: str = DEFAULT_MODEL) -> None:
    """Warmup path: downloads, then writes the ready marker."""
    from model2vec import StaticModel
    StaticModel.from_pretrained(name)
    marker = marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def _adjacent_code(text: str, start_line: int, end_line: int, n: int = 20) -> str:
    """Code the comment is attached to: after it, or before it if nothing follows.

    A trailing comment block (file footer, end of a function) has no code after
    it; judging it against the code above is what a reader actually does.
    """
    lines = text.splitlines()
    after = [ln for ln in lines[end_line:] if ln.strip() and not _COMMENT.match(ln)]
    if after:
        return "\n".join(after[:n])
    before = [ln for ln in lines[:max(start_line - 1, 0)]
              if ln.strip() and not _COMMENT.match(ln)]
    return "\n".join(before[-n:])


class SemanticStrategy:
    def __init__(self, encoder=None):
        self._encoder = encoder

    def _get_encoder(self, model_name: str):
        if self._encoder is None:
            os.environ["HF_HUB_OFFLINE"] = "1"  # never download at check time
            from model2vec import StaticModel
            self._encoder = StaticModel.from_pretrained(model_name)
        return self._encoder

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        if candidates is None:
            return []          # semantic never generates, only filters
        if self._encoder is None and not model_ready():
            ctx.skip_filter("semantic skipped (warming up); run `hoolint warmup`")
            return candidates
        enc = self._get_encoder(
            ctx.settings.get("semantic_model", DEFAULT_MODEL))
        threshold = stage.get("threshold", 0.6)
        kept = []
        for c in candidates:
            code = _adjacent_code(ctx.content(), c.start_line, c.end_line)
            if not code:
                kept.append(c)
                continue
            v = enc.encode([c.span_text.strip(), code])
            sim = float(v[0] @ v[1] /
                        (np.linalg.norm(v[0]) * np.linalg.norm(v[1]) + 1e-9))
            if sim >= threshold:
                c.notes.append(f"semantic: redundancy {sim:.2f} >= {threshold}")
                kept.append(c)
        return kept
