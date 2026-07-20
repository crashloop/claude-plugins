"""Per-session record of files the model touched since the last check."""
import json
from pathlib import Path


def _path(root: Path, session_id: str) -> Path:
    return root / ".hoolint" / f"session-{session_id}.jsonl"


def add(root: Path, session_id: str, file_path: str) -> None:
    """Append a file path to the session journal.

    Args:
      root: Project root directory.
      session_id: Session identifier.
      file_path: Absolute path of the file to record.
    """
    p = _path(root, session_id)
    p.parent.mkdir(exist_ok=True)
    gitignore = p.parent / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    with p.open("a") as f:
        f.write(json.dumps({"file": file_path}) + "\n")


def files(root: Path, session_id: str) -> list[Path]:
    """Journalled files that still exist and live inside the project root.

    Args:
      root: Project root directory.
      session_id: Session identifier.

    Returns:
      Deduplicated, existing files within the project root.
    """
    p = _path(root, session_id)
    if not p.exists():
        return []
    seen: dict[str, None] = {}
    for line in p.read_text().splitlines():
        try:
            seen.setdefault(json.loads(line)["file"])
        except (json.JSONDecodeError, KeyError):
            continue  # a corrupt line must not kill the Stop check
    return [f for f in map(Path, seen)
            if f.exists() and f.resolve().is_relative_to(root.resolve())]


def clear(root: Path, session_id: str) -> None:
    """Delete the session journal.

    Args:
      root: Project root directory.
      session_id: Session identifier.
    """
    _path(root, session_id).unlink(missing_ok=True)
