#!/usr/bin/env python3
"""PostToolUse: append the edited file to the session journal. Stdlib only."""
import json
import os
import sys


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    file_path = (event.get("tool_input") or {}).get("file_path")
    if not file_path:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
