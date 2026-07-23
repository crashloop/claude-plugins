"""Doc checks: broken relative links and stale file references.

Both strategies are generators, not filters: they scan the file's own content
for broken references and ignore any incoming candidates.
"""
import re
from hoolint.findings import Finding
from hoolint.strategies.base import Context

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_REF = re.compile(r"`([\w./-]+\.(?:py|md|toml|json|sh|js|ts|yaml|yml))`")


def _finding(ctx: Context, line: int, span: str, message: str) -> Finding:
    return Finding(rule_id=ctx.rule_id,
                   file=str(ctx.path.relative_to(ctx.root)),
                   start_line=line, end_line=line, span_text=span,
                   message=message, severity=ctx.severity)


class DocLinksStrategy:
    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag relative markdown links whose target file does not exist.

        Args:
            candidates: Ignored; this strategy generates from the file itself.
            stage: Stage config (unused).
            ctx: Per-file execution context.

        Returns:
            One finding per broken relative link.
        """
        out = []
        for i, ln in enumerate(ctx.content().splitlines(), 1):
            for m in _LINK.finditer(ln):
                target = m.group(1).split("#")[0].strip()
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                if not (ctx.path.parent / target).exists():
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
