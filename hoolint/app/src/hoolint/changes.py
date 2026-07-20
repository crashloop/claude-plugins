"""Git-mode change detection for verification pipelines."""
import subprocess
from pathlib import Path


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, timeout=30)


def git_changed(root: Path, ref: str = "auto") -> list[Path]:
    """Files changed vs ref, plus untracked, restricted to inside root.

    ref='auto' resolves the merge-base with main, then master, else HEAD.
    """
    if ref == "auto":
        ref = "HEAD"
        for base in ("main", "master"):
            r = _run(root, "merge-base", "HEAD", base)
            if r.returncode == 0:
                ref = r.stdout.strip()
                break
    diff = _run(root, "diff", "--name-only", ref).stdout.splitlines()
    untracked = _run(root, "ls-files", "--others",
                     "--exclude-standard").stdout.splitlines()
    out: dict[Path, None] = {}
    for name in [*diff, *untracked]:
        p = (root / name).resolve()
        if p.exists() and p.is_relative_to(root.resolve()):
            out.setdefault(p)
    return list(out)
