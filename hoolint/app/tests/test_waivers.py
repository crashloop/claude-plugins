import tomllib

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


def test_add_preserves_comments_and_unknown_tables(tmp_path):
    """A reviewer's own annotations and unrelated tables must survive a write."""
    p = tmp_path / "hoolint-waivers.toml"
    p.write_text(
        '# Team policy: do not remove without asking Ana\n'
        '[meta]\n'
        'owner = "platform"\n'
    )
    waivers.add(tmp_path, _finding(), "sanctioned")
    text = p.read_text()
    assert "# Team policy: do not remove without asking Ana" in text
    assert 'owner = "platform"' in text


def test_span_is_written_as_multiline_toml_string(tmp_path):
    """A multi-line excerpt must read as a TOML block, not one escaped line."""
    waivers.add(tmp_path, _finding(), "sanctioned")
    text = (tmp_path / "hoolint-waivers.toml").read_text()
    assert '"""' in text
    assert "\\n" not in text


def test_prune_with_nothing_to_drop_preserves_comments(tmp_path):
    f = _finding()
    waivers.add(tmp_path, f, "sanctioned")
    p = tmp_path / "hoolint-waivers.toml"
    p.write_text("# keep me\n" + p.read_text())
    assert waivers.prune(tmp_path, live_fingerprints={f.fingerprint}) == 0
    assert "# keep me" in p.read_text()


def test_malformed_waivers_file_raises(tmp_path):
    """Silently reading a broken file as 'no waivers' would un-waive the team's
    approved exceptions, so a parse error must propagate."""
    (tmp_path / "hoolint-waivers.toml").write_text("[[waiver]\nfingerprint = ")
    with pytest.raises(tomllib.TOMLDecodeError):
        waivers.load(tmp_path)
