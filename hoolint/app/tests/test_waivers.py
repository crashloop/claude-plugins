import pytest
from hoolint import waivers
from hoolint.findings import Finding


def _finding():
    return Finding(rule_id="verbose-comments", file="src/x.py", start_line=3,
                   end_line=5, span_text="# a\n# b\n# c\n", message="verbose")


def test_add_and_load(tmp_path):
    f = _finding()
    waivers.add(tmp_path, f, "user asked for this comment block")
    assert waivers.load(tmp_path) == {f.fingerprint}
    text = (tmp_path / "hoolint-waivers.toml").read_text()
    assert "user asked for this comment block" in text


def test_entry_is_reviewable_in_a_diff(tmp_path):
    """A PR reviewer must see what was excused, not just a hash."""
    waivers.add(tmp_path, _finding(), "sanctioned")
    text = (tmp_path / "hoolint-waivers.toml").read_text()
    for expected in ("verbose-comments", "src/x.py", "3-5", "# a"):
        assert expected in text


def test_reason_mandatory(tmp_path):
    with pytest.raises(ValueError):
        waivers.add(tmp_path, _finding(), "")


def test_prune_drops_dead_entries(tmp_path):
    f = _finding()
    waivers.add(tmp_path, f, "sanctioned")
    assert waivers.prune(tmp_path, live_fingerprints=set()) == 1
    assert waivers.load(tmp_path) == set()
