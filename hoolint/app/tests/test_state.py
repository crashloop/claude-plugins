from hoolint import state


def _rec(fp):
    return {"fingerprint": fp, "rule_id": "r", "file": "m.py", "start_line": 1,
            "end_line": 3, "span_text": "# a\n", "message": "verbose"}


def test_bump_counts_consecutive_identical_sets(tmp_path):
    assert state.bump(tmp_path, [_rec("b"), _rec("a")], [])[0] == 1
    assert state.bump(tmp_path, [_rec("a"), _rec("b")], [])[0] == 2  # order-free
    assert state.bump(tmp_path, [_rec("a"), _rec("c")], [])[0] == 1  # set changed
    state.reset(tmp_path)
    assert state.bump(tmp_path, [_rec("a")], [])[0] == 1


def test_consecutive_counter_survives_churn(tmp_path):
    """Editing the span changes fingerprints; the loop must still be bounded."""
    assert state.bump(tmp_path, [_rec("a")], [])[1] == 1
    assert state.bump(tmp_path, [_rec("b")], [])[1] == 2   # different set
    assert state.bump(tmp_path, [_rec("c")], [])[1] == 3
    state.reset(tmp_path)
    assert state.bump(tmp_path, [_rec("d")], [])[1] == 1


def test_blocked_files_and_records_persist(tmp_path):
    state.bump(tmp_path, [_rec("r:f:abc")], ["/p/m.py"])
    assert [str(p) for p in state.blocked_files(tmp_path)] == ["/p/m.py"]
    assert state.last_fingerprints(tmp_path) == {"r:f:abc"}
    assert state.finding_record(tmp_path, "r:f:abc")["file"] == "m.py"
    assert state.finding_record(tmp_path, "nope") is None
