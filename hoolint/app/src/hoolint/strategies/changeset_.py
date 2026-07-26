"""Change-set strategies: rules about which files changed together.

Pure. These read the change set already on the Context and perform no I/O beyond resolving
paths, so they have no failure mode other than invalid configuration, which raises.
"""
from pathlib import Path

import re2

from hoolint.findings import Finding
from hoolint.strategies.base import Context, anchored_finding


def _rel(p: Path, ctx: Context) -> str:
    """The path relative to the project root, resolving both sides."""
    try:
        return str(p.resolve().relative_to(ctx.root.resolve()))
    except ValueError:
        return str(p)


class CompanionStrategy:
    """Generator: flags a changed file whose required companion did not also change."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag this file if the companion it requires is absent from the change set.

        Args:
            candidates: Ignored; this strategy generates rather than filters.
            stage: Stage config: `requires`, or `requires_from` plus `requires_to`, and an
                optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding if the companion did not change, otherwise an empty list.

        Raises:
            ValueError: If the stage config is contradictory or incomplete, or if a derived
                path escapes the project root.
        """
        if candidates is not None:
            return []
        target = self._target(stage, ctx)
        if target is None:
            return []
        if target in {_rel(p, ctx) for p in ctx.changed}:
            return []
        message = stage.get("message", f"changed without {target}")
        return [anchored_finding(ctx, message)]

    def _target(self, stage: dict, ctx: Context) -> str | None:
        """The companion path this file requires, or None if the rule does not apply.

        Args:
            stage: Stage config.
            ctx: Per-file execution context.

        Returns:
            The required companion's path relative to the root, or None when a derived
            pattern does not match this file.

        Raises:
            ValueError: On contradictory or incomplete config, or an escaping path.
        """
        fixed = stage.get("requires")
        frm, to = stage.get("requires_from"), stage.get("requires_to")
        if fixed and (frm or to):
            raise ValueError(
                "companion: requires and requires_from/requires_to are mutually exclusive")
        if fixed:
            return fixed
        if not (frm and to):
            raise ValueError(
                "companion: set requires, or both requires_from and requires_to")
        rel = _rel(ctx.path, ctx)
        if not re2.fullmatch(frm, rel):
            return None
        derived = re2.sub(frm, to, rel)
        if not (ctx.root / derived).resolve().is_relative_to(ctx.root.resolve()):
            raise ValueError(f"companion: derived path escapes the project root: {derived}")
        return derived


class ChangeSizeStrategy:
    """Generator: flags a change set that touches too many files."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag an oversized change, reporting once for the whole set.

        The engine invokes a strategy once per matched file, but this check describes the whole
        change set. It therefore emits only from a deterministic anchor, the first matched file
        in sorted order, so the run yields exactly one finding with a stable fingerprint.

        `max_files` counts the entire change set, not the rule's glob subset, because blast
        radius is the point. Line counts are deliberately unsupported: the session journal
        records paths only, so a line threshold would silently mean nothing in session mode.

        Args:
            candidates: Ignored; this strategy generates rather than filters.
            stage: Stage config: `max_files` (default 20) and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding when the change set exceeds `max_files`, otherwise an empty list.
        """
        if candidates is not None:
            return []
        if not ctx.matched or ctx.path != sorted(ctx.matched)[0]:
            return []
        max_files = stage.get("max_files", 20)
        count = len(ctx.changed)
        if count <= max_files:
            return []
        message = stage.get(
            "message", f"change touches {count} files (max {max_files})")
        return [anchored_finding(ctx, message)]
