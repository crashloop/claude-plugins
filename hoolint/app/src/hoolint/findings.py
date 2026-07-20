"""Finding: one rule violation anchored to a span in a file."""
import hashlib
from dataclasses import dataclass, field


@dataclass
class Finding:
    rule_id: str
    file: str
    start_line: int
    end_line: int
    span_text: str
    message: str
    severity: str = "warn"
    needs_judgment: bool = False
    judgment_prompt: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        """Stable identity: changes iff the offending span changes."""
        span_hash = hashlib.sha256(self.span_text.encode()).hexdigest()[:16]
        return f"{self.rule_id}:{self.file}:{span_hash}"

    def record(self) -> dict:
        """Minimal JSON-safe form, enough to write a reviewable waiver later."""
        return {"fingerprint": self.fingerprint, "rule_id": self.rule_id,
                "file": self.file, "start_line": self.start_line,
                "end_line": self.end_line, "span_text": self.span_text,
                "message": self.message}

    @classmethod
    def from_record(cls, rec: dict) -> "Finding":
        return cls(rule_id=rec["rule_id"], file=rec["file"],
                   start_line=rec["start_line"], end_line=rec["end_line"],
                   span_text=rec["span_text"], message=rec["message"])
