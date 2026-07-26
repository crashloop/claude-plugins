"""Git-mode change detection for verification pipelines."""
import subprocess
from pathlib import Path


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in root.

    Args:
      root: Directory to run git in.
      *args: Arguments to pass to git, after the "git" binary.
      check: If True, raise RuntimeError when git exits nonzero. Pass False for
        probes whose failure is an expected, handled outcome.

    Returns:
      The completed process, with captured stdout/stderr.

    Raises:
      RuntimeError: If check is True and git exits nonzero.
    """
    r = subprocess.run(["git", *args], cwd=root, capture_output=True,
                       text=True, timeout=30)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def _split_nul(output: str) -> list[str]:
    """Split NUL-terminated git output, dropping the trailing empty element."""
    return [name for name in output.split("\0") if name]


def git_changed(root: Path, ref: str = "auto") -> list[Path]:
    """Files changed vs ref, plus untracked, restricted to inside root.

    ref='auto' resolves the merge-base with main, then master. If HEAD is
    unborn (no commits yet), only untracked files are returned. If HEAD
    exists but neither main nor master resolves, raises RuntimeError asking
    the caller to pass ref explicitly.
    """
    diff_ref = None
    if ref == "auto":
        head = run_git(root, "rev-parse", "--verify", "HEAD", check=False)
        if head.returncode == 0:
            for base in ("main", "master"):
                r = run_git(root, "merge-base", "HEAD", base, check=False)
                if r.returncode == 0:
                    diff_ref = r.stdout.strip()
                    break
            else:
                raise RuntimeError(
                    "git_changed: no merge-base with main or master found; "
                    "pass --ref explicitly")
        # else: unborn HEAD, nothing to diff against, fall through to untracked
    else:
        diff_ref = ref

    diff = []
    if diff_ref is not None:
        diff = _split_nul(run_git(root, "diff", "--name-only", "-z", diff_ref).stdout)
    untracked = _split_nul(
        run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)

    root_resolved = root.resolve()
    out: dict[Path, None] = {}
    for name in [*diff, *untracked]:
        p = (root / name).resolve()
        if p.exists() and p.is_relative_to(root_resolved):
            out.setdefault(p)
    return list(out)
