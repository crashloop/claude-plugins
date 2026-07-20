"""Cross-stop state: stand-down counters, blocked files, waivable fingerprints.

Two counters, two loop shapes: `same_set` catches "same problem, no progress";
`consecutive` bounds a model that keeps editing the span without fixing it,
which changes the fingerprints and would otherwise reset `same_set` forever.

Unlike hoolint-waivers.toml, this file is hoolint's own ephemeral scratch
state under .hoolint/ (never committed, never team-reviewed). If it's
corrupt, treating it as fresh state costs nothing but the stand-down count
-- no approval is lost -- so a bad read resets rather than crashing the
Stop hook.
"""
import json
from pathlib import Path


def _path(root: Path) -> Path:
    return root / ".hoolint" / "state.json"


def _read(root: Path) -> dict:
    p = _path(root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}  # corrupt scratch state: restart counters, don't crash the hook


def bump(root: Path, records: list[dict],
         blocked_files: list[str]) -> tuple[int, int]:
    """Record a blocked stop. Returns (same_set_count, consecutive_count).

    Args:
        root: Project root directory.
        records: `Finding.record()` dicts for the blocking findings.
        blocked_files: Paths that must stay in scope at the next stop.
    """
    p = _path(root)
    p.parent.mkdir(exist_ok=True)
    fps = sorted(r["fingerprint"] for r in records)
    prev = _read(root)
    if prev.get("fingerprints") == fps:
        same = prev.get("same_set", 0) + 1
    else:
        same = 1
    consecutive = prev.get("consecutive", 0) + 1
    p.write_text(json.dumps({"fingerprints": fps, "same_set": same,
                             "consecutive": consecutive,
                             "blocked_files": blocked_files,
                             "last_findings": records}))
    return same, consecutive


def blocked_files(root: Path) -> list[Path]:
    """Files that still carried block findings at the previous stop.

    Args:
        root: Project root directory.
    """
    return [Path(f) for f in _read(root).get("blocked_files", [])]


def last_fingerprints(root: Path) -> set[str]:
    """The only fingerprints `hoolint waive` will accept.

    Args:
        root: Project root directory.
    """
    return {r["fingerprint"] for r in _read(root).get("last_findings", [])}


def finding_record(root: Path, fingerprint: str) -> dict | None:
    """The stored record for a surfaced finding, so waive can write its span.

    Args:
        root: Project root directory.
        fingerprint: Fingerprint to look up among the last surfaced findings.
    """
    for r in _read(root).get("last_findings", []):
        if r["fingerprint"] == fingerprint:
            return r
    return None


def record_findings(root: Path, records: list[dict]) -> None:
    """Remember a clean or warn-only run's findings so they stay waivable.

    Args:
        root: Project root directory.
        records: `Finding.record()` dicts for the surfaced (non-blocking)
            findings.
    """
    p = _path(root)
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({"fingerprints": [], "same_set": 0,
                             "consecutive": 0, "blocked_files": [],
                             "last_findings": records}))


def reset(root: Path) -> None:
    """Discard all stand-down state.

    Args:
        root: Project root directory.
    """
    _path(root).unlink(missing_ok=True)
