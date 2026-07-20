"""Regex strategy: generate findings from matches, or filter candidates.

Uses google-re2, not stdlib `re`: patterns come from project config, and RE2's
linear-time guarantee means no pattern can hang the check. No lookaround.
"""
import re2
from hoolint.findings import Finding
from hoolint.strategies.base import Context


class RegexStrategy:
    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        pat = re2.compile(stage["pattern"])
        excludes = [re2.compile(p) for p in stage.get("exclude", [])]
        if candidates is not None:
            return [c for c in candidates if pat.search(c.span_text)
                    and not any(x.search(c.span_text) for x in excludes)]
        text = ctx.content()
        out = []
        for m in pat.finditer(text):
            span = m.group()
            if any(x.search(span) for x in excludes):
                continue
            start = text.count("\n", 0, m.start()) + 1
            end = start + span.rstrip("\n").count("\n")
            out.append(Finding(
                rule_id=ctx.rule_id, file=str(ctx.path.relative_to(ctx.root)),
                start_line=start, end_line=end, span_text=span,
                message=stage.get("message", f"matched {stage['pattern']}"),
                severity=ctx.severity))
        return out
