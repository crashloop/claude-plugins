import subprocess

import pytest

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


def test_git_changed_excludes_paths_outside_root(tmp_path):
    """A symlink into a directory outside root must not leak its target."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "."); _git(repo, "commit", "-m", "base")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("y = 1\n")
    (repo / "link").symlink_to(outside)          # untracked, resolves outside root
    (repo / "b.py").write_text("y = 1\n")         # untracked, inside root
    names = sorted(p.name for p in git_changed(repo))
    assert names == ["b.py"]


def test_git_changed_returns_non_ascii_filenames(tmp_path):
    """Non-ASCII names are quote-escaped by git and must be unescaped, not dropped."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "."); _git(tmp_path, "commit", "-m", "base")
    (tmp_path / "café.py").write_text("y = 1\n")  # untracked, non-ASCII name
    names = sorted(p.name for p in git_changed(tmp_path))
    assert names == ["café.py"]


def test_git_changed_unborn_head_returns_untracked(tmp_path):
    """With no commits yet, HEAD is unborn: return untracked files, don't raise."""
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "b.py").write_text("y = 1\n")     # untracked, never committed
    names = sorted(p.name for p in git_changed(tmp_path))
    assert names == ["b.py"]


def test_git_changed_raises_without_main_or_master(tmp_path):
    """HEAD exists but neither main nor master resolves: raise, don't fall back."""
    _git(tmp_path, "init", "-b", "trunk")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "."); _git(tmp_path, "commit", "-m", "base")
    with pytest.raises(RuntimeError):
        git_changed(tmp_path)
