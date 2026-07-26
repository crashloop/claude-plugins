"""Git-history strategies: rules about how a file has changed over time.

Every git failure raises. `engine._guarded` converts the exception into a visible warn finding,
so a missing binary, a non-repository, or a non-zero exit can never read as a clean check. That
reuses one tested degradation path rather than adding a second.
"""
from hoolint.changes import run_git
from hoolint.findings import Finding
from hoolint.strategies.base import Context, anchored_finding


def _has_commits(ctx: Context) -> bool:
    """Whether HEAD resolves, distinguishing an unborn HEAD from a broken environment.

    `rev-parse --verify HEAD` fails for both an unborn HEAD and a non-repository, so probing it
    alone would swallow a real error as "no history" and return a clean result from a check that
    never ran. The `--git-dir` probe runs with check=True first, so a missing git binary or a
    non-repository raises and surfaces as a visible warn finding.

    Args:
        ctx: Per-file execution context.

    Returns:
        True if HEAD resolves to a commit, False for a valid repository with no commits yet.

    Raises:
        RuntimeError: If the directory is not a git repository, or git is unavailable.
    """
    run_git(ctx.root, "rev-parse", "--git-dir")
    return run_git(ctx.root, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


class ChurnStrategy:
    """Generator: flags a file revised too many times within a window."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag this file when its recent commit count exceeds the threshold.

        Args:
            candidates: Ignored; this strategy generates rather than filters.
            stage: Stage config: `max_commits` (default 5), `window` (default "30.days",
                passed to `git log --since`), and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding when the file is churning, otherwise an empty list.

        Raises:
            RuntimeError: If git fails. The engine's guard turns this into a visible warn.
        """
        if candidates is not None:
            return []
        if not _has_commits(ctx):
            return []
        rel = str(ctx.path.relative_to(ctx.root))
        window = stage.get("window", "30.days")
        out = run_git(ctx.root, "log", f"--since={window}", "--format=%H", "--", rel)
        count = len([line for line in out.stdout.splitlines() if line.strip()])
        max_commits = stage.get("max_commits", 5)
        if count <= max_commits:
            return []
        message = stage.get(
            "message",
            f"{rel} changed {count} times in {window} (max {max_commits})")
        return [anchored_finding(ctx, message)]
