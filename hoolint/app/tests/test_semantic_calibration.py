import json
from pathlib import Path

import pytest

from hoolint.strategies.semantic import DEFAULT_MODEL

FIXTURES = Path(__file__).parent / "fixtures" / "comment_pairs.jsonl"


@pytest.mark.slow
def test_threshold_separates_labelled_pairs():
    """Records the real model's separation; fails if a model swap degrades it."""
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
    threshold = (max(scores[False]) + min(scores[True])) / 2
    fp = sum(s >= threshold for s in scores[False]) / len(scores[False])
    print(f"separation: redundant>={min(scores[True]):.3f} "
          f"useful<={max(scores[False]):.3f} threshold={threshold:.3f} fp={fp:.2f}")
    assert fp <= 0.2, "threshold cannot separate redundant from useful comments"
