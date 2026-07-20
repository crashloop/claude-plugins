"""Committed team waivers; git review is the approval gate.

Entries carry the excused span so a reviewer can judge the waiver from the
diff alone, without checking out the branch and recomputing a hash.

A malformed waivers file is never treated as "no waivers": that would
silently un-waive exceptions the team already approved. Parse errors
propagate instead, the same way a malformed hoolint.toml already does
in config.py.
"""
import tomllib
from pathlib import Path

import tomli_w

from hoolint.findings import Finding

FILE = "hoolint-waivers.toml"


def load(root: Path) -> set[str]:
    """Fingerprints currently excused by the committed waivers file.

    Args:
        root: Project root directory.
    """
    p = root / FILE
    if not p.exists():
        return set()
    data = tomllib.loads(p.read_text())
    return {w["fingerprint"] for w in data.get("waiver", [])}


def _excerpt(span: str) -> str:
    return "\n".join(span.splitlines()[:3])[:200]


def add(root: Path, finding: Finding, reason: str) -> None:
    """Append a reviewable waiver. Reason is mandatory -- it lands in the diff.

    Args:
        root: Project root directory.
        finding: The excused finding; its span and location are recorded.
        reason: Human-readable justification, required and non-blank.

    Raises:
        ValueError: If reason is empty or whitespace-only.
    """
    if not reason.strip():
        raise ValueError("waiver reason is mandatory")
    p = root / FILE
    data = tomllib.loads(p.read_text()) if p.exists() else {}
    entries = data.get("waiver", [])
    entries.append({
        "fingerprint": finding.fingerprint,
        "rule_id": finding.rule_id,
        "file": finding.file,
        "lines": f"{finding.start_line}-{finding.end_line}",
        "span": _excerpt(finding.span_text),
        "reason": reason,
    })
    p.write_text(tomli_w.dumps({"waiver": entries}))


def prune(root: Path, live_fingerprints: set[str]) -> int:
    """Drop waivers whose fingerprint no longer occurs in a full check.

    Args:
        root: Project root directory.
        live_fingerprints: Fingerprints a full check currently produces.

    Returns:
        Count of dropped entries.
    """
    p = root / FILE
    if not p.exists():
        return 0
    entries = tomllib.loads(p.read_text()).get("waiver", [])
    kept = [w for w in entries if w["fingerprint"] in live_fingerprints]
    p.write_text(tomli_w.dumps({"waiver": kept}))
    return len(entries) - len(kept)
