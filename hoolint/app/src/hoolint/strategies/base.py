"""Shared per-file execution context passed to every stage."""
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Context:
    path: Path
    root: Path
    mode: str            # "session" | "git"
    settings: dict
    rule_id: str
    severity: str
    notes: list[str] = field(default_factory=list)
    filter_skipped: bool = False
    _content: str | None = None

    def content(self) -> str:
        if self._content is None:
            self._content = self.path.read_text(errors="replace")
        return self._content

    def warn(self, msg: str) -> None:
        if msg not in self.notes:
            self.notes.append(msg)

    def skip_filter(self, msg: str) -> None:
        """A filter stage could not run: note it and disarm blocking.

        A skipped filter removed no false positives, so its survivors have not
        earned a block. Findings from this run degrade to warn.
        """
        self.warn(msg)
        self.filter_skipped = True
