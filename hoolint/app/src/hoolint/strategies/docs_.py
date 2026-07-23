"""Doc checks: broken relative links and stale file references.

Both strategies are generators, not filters: they scan the file's own content
for broken references and ignore any incoming candidates.
"""
import re
from hoolint.findings import Finding
from hoolint.strategies.base import Context

# Alt 1: inline `[text](target)`. Alt 2: reference `[text][ref]` / `[text][]`.
# Alt 3: shortcut `[ref]`, excluded when it's actually a `[ref]:` definition.
_LINK_ANY = re.compile(
    r"\[([^\]]*)\]\(([^)]+)\)"
    r"|\[([^\]]+)\]\[([^\]]*)\]"
    r"|\[([^\]]+)\](?!:)"
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

        Handles inline links `[t](path "title")`, reference links
        `[t][ref]` / `[t][]` / `[ref]`, and skips fenced code blocks so
        markdown examples aren't scanned as live links.

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
                label = (m.group(4) or m.group(3)) if m.group(3) is not None else m.group(5)
                label = label.lower()
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
    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag backticked file references that don't exist in the repo.

        Args:
            candidates: Ignored; this strategy generates from the file itself.
            stage: Stage config (unused).
            ctx: Per-file execution context.

        Returns:
            One finding per backticked path that resolves to no real file.
        """
        out = []
        for i, ln in enumerate(ctx.content().splitlines(), 1):
            for m in _REF.finditer(ln):
                ref = m.group(1)
                if not (ctx.root / ref).exists() and not (ctx.path.parent / ref).exists():
                    out.append(_finding(ctx, i, ref,
                                        f"references missing file: {ref}"))
        return out
