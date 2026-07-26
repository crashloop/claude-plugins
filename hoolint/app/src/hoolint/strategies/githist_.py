"""Git-history strategies: rules about how a file has changed over time.

Every git failure raises. `engine._guarded` converts the exception into a visible warn finding,
so a missing binary, a non-repository, or a non-zero exit can never read as a clean check. That
reuses one tested degradation path rather than adding a second.
"""
import re2
from hoolint.changes import run_git
from hoolint.findings import Finding
from hoolint.strategies.base import Context, anchored_finding, rel_to_root


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
            candidates: Must be None; this strategy generates rather than filters.
            stage: Stage config: `max_commits` (default 5), `window` (default "30.days",
                passed to `git log --since`), and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding when the file is churning, otherwise an empty list.

        Raises:
            RuntimeError: If git fails. The engine's guard turns this into a visible warn.
            ValueError: If the stage was chained after another.
        """
        if candidates is not None:
            raise ValueError(
                "churn is a generator; it cannot follow another stage. "
                "Put it first, or chain it with op = \"or\".")
        if not _has_commits(ctx):
            return []
        rel = rel_to_root(ctx.path, ctx.root)
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


class CommitMetaStrategy:
    """Generator: flags a commit subject that breaks the project's convention."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Judge the most recent commit subject against a pattern, once per run.

        The subject describes the whole change, so this emits only from a deterministic anchor,
        the first matched file in sorted order. In practice this rule belongs in git mode: at
        Stop time in a session there is usually no new commit to inspect.

        Args:
            candidates: Must be None; this strategy generates rather than filters.
            stage: Stage config: `subject_pattern`, an re2 pattern matched against the whole
                subject, and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding when the subject does not match, otherwise an empty list.

        Raises:
            RuntimeError: If git fails. The engine's guard turns this into a visible warn.
            KeyError: If `subject_pattern` is absent, which is a config error.
            ValueError: If the stage was chained after another.
        """
        if candidates is not None:
            raise ValueError(
                "commit_meta is a generator; it cannot follow another stage. "
                "Put it first, or chain it with op = \"or\".")
        if not ctx.matched or ctx.path != sorted(ctx.matched)[0]:
            return []
        if not _has_commits(ctx):
            return []
        subject = run_git(ctx.root, "log", "-1", "--format=%s").stdout.strip()
        if re2.fullmatch(stage["subject_pattern"], subject):
            return []
        message = stage.get(
            "message", f"commit subject does not match the convention: {subject!r}")
        return [anchored_finding(ctx, message)]
