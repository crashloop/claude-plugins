"""Doc checks: broken relative links, stale file references, banned prose patterns.

The two reference checks are generators, not filters: they scan the file's own
content and ignore any incoming candidates. `ProsePatternStrategy` filters when
given candidates. What the three share is knowing where a fenced code block is,
so a quoted sample is never read as authored content.
"""
import re
from pathlib import Path

import re2

from hoolint.changes import run_git
from hoolint.findings import Finding
from hoolint.strategies.base import Context, rel_to_root

# Alt 1: inline `[text](target)`. Alt 2: reference `[text][ref]` / `[text][]`.
# The shortcut form `[ref]` (a single bracket pair, nothing after it) is not
# matched: it's indistinguishable from ordinary bracketed prose.
_LINK_ANY = re.compile(
    r"\[([^\]]*)\]\(([^)]+)\)"
    r"|\[([^\]]+)\]\[([^\]]*)\]"
)
_DEF = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(\S+)")
_REF = re.compile(r"`([\w./-]+\.(?:py|md|toml|json|sh|js|ts|yaml|yml))`")


def _finding(ctx: Context, line: int, span: str, message: str) -> Finding:
    return Finding(rule_id=ctx.rule_id,
                   file=str(ctx.path.relative_to(ctx.root)),
                   start_line=line, end_line=line, span_text=span,
                   message=message, severity=ctx.severity)


def _clean_target(raw: str) -> str:
    """Strip an optional title and `#anchor` from a link destination.

    A CommonMark destination runs up to the first unescaped whitespace; any
    trailing `"title"`, `'title'`, or `(title)` is discarded.

    Args:
        raw: The raw text captured between the destination delimiters.

    Returns:
        The bare path or URL, with title and anchor removed.
    """
    dest = raw.strip()
    if dest:
        dest = dest.split(None, 1)[0]
    return dest.split("#")[0].strip()


def _is_local_broken(target: str, ctx: Context) -> bool:
    """Whether a cleaned target is a relative path that resolves to nothing.

    Args:
        target: A destination already run through `_clean_target`.
        ctx: Per-file execution context, for resolving relative paths.

    Returns:
        True if the target is a relative path and no such file exists.
    """
    if not target or "://" in target or target.startswith("mailto:"):
        return False
    return not (ctx.path.parent / target).exists()


def _fence_mask(lines: list[str]) -> list[bool]:
    """Mark which lines fall inside, or open/close, a fenced code block.

    Args:
        lines: The file's lines.

    Returns:
        A parallel list of booleans; True means the line must not be scanned.
    """
    mask = []
    in_fence = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mask.append(True)
            in_fence = not in_fence
        else:
            mask.append(in_fence)
    return mask


def _collect_defs(lines: list[str], mask: list[bool]) -> dict[str, str]:
    """Collect reference-style link definitions, skipping fenced lines.

    Args:
        lines: The file's lines.
        mask: Parallel fence mask from `_fence_mask`.

    Returns:
        Map of lowercased label to its cleaned target.
    """
    defs = {}
    for skip, ln in zip(mask, lines):
        if skip:
            continue
        m = _DEF.match(ln)
        if m:
            defs[m.group(1).lower()] = _clean_target(m.group(2))
    return defs


class DocLinksStrategy:
    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag relative markdown links whose target file does not exist.

        Handles inline links `[t](path "title")` and reference links
        `[t][ref]` / `[t][]`, and skips fenced code blocks so markdown
        examples aren't scanned as live links. The bare shortcut form
        `[ref]` is intentionally not treated as a reference use: it is
        indistinguishable from ordinary bracketed prose.

        Args:
            candidates: Ignored; this strategy generates from the file itself.
            stage: Stage config (unused).
            ctx: Per-file execution context.

        Returns:
            One finding per broken or undefined link.
        """
        lines = ctx.content().splitlines()
        mask = _fence_mask(lines)
        defs = _collect_defs(lines, mask)
        out = []
        for i, (skip, ln) in enumerate(zip(mask, lines), 1):
            if skip:
                continue
            for m in _LINK_ANY.finditer(ln):
                if m.group(2) is not None:
                    target = _clean_target(m.group(2))
                    if _is_local_broken(target, ctx):
                        out.append(_finding(ctx, i, target,
                                            f"broken relative link: {target}"))
                    continue
                label = (m.group(4) or m.group(3)).lower()
                if label not in defs:
                    out.append(_finding(ctx, i, label,
                                        f"undefined reference: [{label}]"))
                    continue
                target = defs[label]
                if _is_local_broken(target, ctx):
                    out.append(_finding(ctx, i, target,
                                        f"broken relative link: {target}"))
        return out


class DocRefsStrategy:
    """Flags backticked file references that name no file in the repo.

    A doc says which directory it works from and then names files relative to
    it, so root- and sibling-relative resolution alone reads a correct reference
    as drift. Measured on this repo, that was 121 of 142 findings.
    """

    def __init__(self):
        # ponytail: one index per root, never invalidated. The CLI is one
        # process per run; add a mtime check if that stops being true.
        self._segments: dict[Path, set[str]] = {}

    def _tracked(self, root: Path) -> set[str]:
        """Every path-segment suffix of every tracked file, e.g. `a/b.py`, `b.py`.

        Args:
            root: Repository root to index.

        Returns:
            The suffix set, empty outside a git repository.
        """
        if root not in self._segments:
            out: set[str] = set()
            r = run_git(root, "ls-files", check=False)
            if r.returncode == 0:
                for path in r.stdout.split("\n"):
                    parts = path.strip().split("/")
                    out.update("/".join(parts[i:]) for i in range(len(parts)) if path)
            self._segments[root] = out
        return self._segments[root]

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag backticked file references that don't exist in the repo.

        Args:
            candidates: Ignored; this strategy generates from the file itself.
            stage: Stage config (unused).
            ctx: Per-file execution context.

        Returns:
            One finding per backticked path that names no tracked file.
        """
        tracked = self._tracked(ctx.root)
        out = []
        for i, ln in enumerate(ctx.content().splitlines(), 1):
            for m in _REF.finditer(ln):
                ref = m.group(1).strip("/")
                if (ref in tracked or (ctx.root / ref).exists()
                        or (ctx.path.parent / ref).exists()):
                    continue
                out.append(_finding(ctx, i, ref, f"references missing file: {ref}"))
        return out


class ProsePatternStrategy:
    """Flags a configured pattern in prose, skipping fenced code blocks.

    Unlike `regex`, this knows what a code fence is, so a pattern banned in
    authored prose stays legal in a quoted code sample. Unlike its two
    file-mates, it filters when handed candidates rather than generating over
    them, which would silently replace the previous stage's findings.
    """

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag every non-fenced line matching the stage's pattern.

        One finding per line, not per match: the span is the whole line, so two
        occurrences on one line read as one problem and each line keeps a
        distinct fingerprint. Matching the bare pattern would instead give every
        hit in the file the same fingerprint, and waiving one would silence all.

        Uses re2 rather than this module's stdlib `re`, because this pattern
        comes from project config: RE2's linear-time guarantee is what stops a
        pathological pattern hanging the check.

        Args:
            candidates: Prior-stage findings to filter, or None to scan the file.
            stage: Stage config: `pattern`, and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            The filtered candidates, or one finding per offending line.
        """
        pat = re2.compile(stage["pattern"])
        if candidates is not None:
            return [c for c in candidates if pat.search(c.span_text)]
        lines = ctx.content().splitlines()
        rel = rel_to_root(ctx.path, ctx.root)
        message = stage.get("message", f"matched {stage['pattern']}")
        return [Finding(rule_id=ctx.rule_id, file=rel, start_line=i, end_line=i,
                        span_text=line, message=message, severity=ctx.severity)
                for i, (line, fenced) in enumerate(zip(lines, _fence_mask(lines)), 1)
                if not fenced and pat.search(line)]
