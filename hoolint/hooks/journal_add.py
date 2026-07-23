#!/usr/bin/env python3
"""PostToolUse: append the edited file to the session journal. Stdlib only."""
import json
import os
import sys


def main() -> int:
    """Append the edited file to the session journal; never break the edit.

    Any malformed input or I/O failure exits 0 quietly: journaling is
    best-effort and must not fail a Write/Edit the model just made.
    """
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            return 0
        tool_input = event.get("tool_input")
        file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        if not isinstance(file_path, str) or not file_path:
            return 0
        root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        session = event.get("session_id", "default")
        hoolint_dir = os.path.join(root, ".hoolint")
        os.makedirs(hoolint_dir, exist_ok=True)
        gitignore = os.path.join(hoolint_dir, ".gitignore")
        if not os.path.exists(gitignore):
            with open(gitignore, "w") as f:
                f.write("*\n")
        with open(os.path.join(hoolint_dir, f"session-{session}.jsonl"), "a") as f:
            f.write(json.dumps({"file": file_path}) + "\n")
    except Exception:  # noqa: BLE001 - journaling must never break an edit
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
