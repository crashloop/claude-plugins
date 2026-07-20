"""Shared helper for hoolint's ephemeral .hoolint/ scratch directory.

.hoolint/ must never be committed. It self-gitignores via a `.gitignore`
containing `*`, written the first time anything creates the directory.
"""
from pathlib import Path


def ensure_dir(root: Path) -> Path:
    """Create .hoolint/ under root if missing, with its self-gitignore.

    Args:
        root: Project root directory.

    Returns:
        The .hoolint/ directory path.
    """
    d = root / ".hoolint"
    d.mkdir(exist_ok=True)
    gitignore = d / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return d
