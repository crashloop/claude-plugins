"""Shared per-file execution context passed to every stage."""
from dataclasses import dataclass, field
from pathlib import Path

from hoolint.findings import Finding


@dataclass
class Context:
    path: Path
    root: Path
    mode: str            # "session" | "git"
    settings: dict
    rule_id: str
    severity: str
    changed: list[Path] = field(default_factory=list)
    matched: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    filter_skipped: bool = False
    _content: str | None = None

    def content(self) -> str:
        """Read and cache the file's text, replacing undecodable bytes.

        Returns:
            The file's full text content.
        """
        if self._content is None:
            self._content = self.path.read_text(errors="replace")
        return self._content

    def warn(self, msg: str) -> None:
        """Record a deduplicated note on this context.

        The engine copies these onto any findings the rule's stages produce.

        Args:
            msg: The note text to record.
        """
        if msg not in self.notes:
            self.notes.append(msg)

    def skip_filter(self, msg: str) -> None:
        """A filter stage could not run: note it and disarm blocking.

        A skipped filter removed no false positives, so its survivors have not
        earned a block. Findings from this run degrade to warn.
        """
        self.warn(msg)
        self.filter_skipped = True


def anchored_finding(ctx: Context, message: str) -> Finding:
    """Build a finding anchored to the file itself, for rules with no code span.

    Metadata rules describe how a file relates to other files, not a span inside it.
    The span is the file's own relative path, so the fingerprint is stable for that
    file. Waivers on metadata findings are therefore durable by design: they do not
    expire when the file's contents change.

    Args:
        ctx: Per-file execution context.
        message: The finding's human-readable message.

    Returns:
        A Finding anchored to ctx.path, carrying the rule's configured severity.
    """
    rel = str(ctx.path.relative_to(ctx.root))
    return Finding(rule_id=ctx.rule_id, file=rel, start_line=1, end_line=1,
                   span_text=rel, message=message, severity=ctx.severity)
