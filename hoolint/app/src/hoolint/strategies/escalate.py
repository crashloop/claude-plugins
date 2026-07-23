"""Hand the shortlist to the session model for judgment (never an API call)."""
from hoolint.findings import Finding
from hoolint.strategies.base import Context


class EscalateStrategy:
    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Escalate survivors to the session model, or note they went unjudged.

        Args:
            candidates: Prior-stage findings to hand off.
            stage: Stage config with the "prompt" to surface to the session model.
            ctx: Per-file execution context.

        Returns:
            The same findings, annotated for the CLI or waiver flow.
        """
        if not candidates:
            return []
        for c in candidates:
            if ctx.mode == "git":
                # Severity is retained: CI must still fail on unjudged blocks.
                c.notes.append("not-judged (no session)")
            else:
                c.needs_judgment = True
                c.judgment_prompt = stage.get("prompt", "")
        return candidates
