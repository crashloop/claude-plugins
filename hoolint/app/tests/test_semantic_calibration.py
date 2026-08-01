import json
import tomllib
from importlib import resources
from pathlib import Path

import pytest

from hoolint.strategies.semantic import DEFAULT_MODEL

FIXTURES = Path(__file__).parent / "fixtures" / "comment_pairs.jsonl"


def shipped_threshold() -> float:
    """The semantic threshold defaults.toml actually ships.

    Reading it rather than recomputing an optimum is the point: the previous
    version of this test derived its own midpoint, so it never checked the
    value users run with.

    Returns:
        The `threshold` on the verbose-comments semantic stage.
    """
    cfg = tomllib.loads((resources.files("hoolint") / "defaults.toml").read_text())
    return next(st["threshold"]
                for r in cfg["rule"] if r["id"] == "verbose-comments"
                for st in r.get("stage", []) if st["strategy"] == "semantic")


@pytest.mark.slow
def test_shipped_threshold_keeps_every_redundant_comment():
    """Recall floor on the shipped threshold; fails if a model swap degrades it.

    Semantic is an `and` gate upstream of the judge, so its two errors cost
    differently. A useful comment scoring high stays a candidate and is dropped
    later by local_llm or escalate. Redundant code scoring low is discarded
    silently and reaches no judge at all. Recall is the property worth pinning;
    the false-positive rate only has to stay low enough that the stage still
    shortens the judge's list.

    Excluded from the default run by `addopts = "-m 'not slow'"` because it
    downloads the model. Run `uv run pytest -m slow` whenever the model or the
    threshold changes.
    """
    from model2vec import StaticModel
    import numpy as np
    enc = StaticModel.from_pretrained(DEFAULT_MODEL)
    pairs = [json.loads(ln) for ln in FIXTURES.read_text().splitlines()]
    scores = {True: [], False: []}
    for p in pairs:
        v = enc.encode([p["comment"], p["code"]])
        sim = float(v[0] @ v[1] /
                    (np.linalg.norm(v[0]) * np.linalg.norm(v[1]) + 1e-9))
        scores[p["redundant"]].append(sim)
    threshold = shipped_threshold()
    recall = sum(s >= threshold for s in scores[True]) / len(scores[True])
    fp = sum(s >= threshold for s in scores[False]) / len(scores[False])
    print(f"threshold={threshold:.2f} recall={recall:.2f} fp={fp:.2f} "
          f"redundant>={min(scores[True]):.3f} useful<={max(scores[False]):.3f}")
    assert recall >= 0.9, (
        f"threshold {threshold} discards real slop before any judge sees it "
        f"(recall {recall:.2f}); lowest redundant pair scores "
        f"{min(scores[True]):.3f}")
    assert fp <= 0.5, (
        f"threshold {threshold} passes {fp:.0%} of useful comments through; "
        f"the stage no longer shortens the judge's list")
