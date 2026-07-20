import subprocess
from hoolint.changes import git_changed


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_git_changed_lists_modified_and_untracked(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "."); _git(tmp_path, "commit", "-m", "base")
    (tmp_path / "a.py").write_text("x = 2\n")       # modified
    (tmp_path / "b.py").write_text("y = 1\n")       # untracked
    names = sorted(p.name for p in git_changed(tmp_path))
    assert names == ["a.py", "b.py"]
