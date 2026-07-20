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
