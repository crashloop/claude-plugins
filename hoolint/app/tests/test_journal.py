import json
from hoolint import journal


def test_add_files_clear_roundtrip(tmp_path):
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    outside = tmp_path.parent / "outside.py"
    outside.write_text("x = 1\n")
    journal.add(tmp_path, "s1", str(a))
    journal.add(tmp_path, "s1", str(a))                # duplicate
    journal.add(tmp_path, "s1", str(tmp_path / "gone.py"))  # deleted since
    journal.add(tmp_path, "s1", str(outside))          # outside the root
    assert journal.files(tmp_path, "s1") == [a]
    assert (tmp_path / ".hoolint" / ".gitignore").read_text() == "*\n"
    journal.clear(tmp_path, "s1")
    assert journal.files(tmp_path, "s1") == []


def test_files_excludes_lexical_prefix_escapes(tmp_path):
    """Paths with .. segments that escape root are excluded after resolution."""
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    # Create a real file outside the root
    outside = tmp_path.parent / "outside.py"
    outside.write_text("x = 1\n")
    # Manually craft a journal entry with .. that lexically prefixes root
    # but resolves outside (e.g., /tmp/rootx/../../etc/passwd pattern)
    root_parent = tmp_path.parent.name
    crafted_path = tmp_path / ".." / ".." / root_parent / "outside.py"
    journal.add(tmp_path, "s2", str(a))
    journal.add(tmp_path, "s2", str(crafted_path))
    result = journal.files(tmp_path, "s2")
    assert result == [a]
    assert outside not in result


def test_files_skips_corrupt_journal_lines(tmp_path):
    """Corrupt JSON or missing 'file' key are skipped without crashing."""
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    b = tmp_path / "b.py"
    b.write_text("x = 2\n")
    # Manually write a journal with valid, corrupt, and valid lines
    journal_path = tmp_path / ".hoolint" / "session-s3.jsonl"
    journal_path.parent.mkdir(exist_ok=True)
    journal_path.write_text(
        json.dumps({"file": str(a)}) + "\n"
        + "not valid json\n"
        + json.dumps({"not_file": "value"}) + "\n"
        + json.dumps({"file": str(b)}) + "\n"
    )
    result = journal.files(tmp_path, "s3")
    assert set(result) == {a, b}
