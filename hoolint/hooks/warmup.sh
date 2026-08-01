#!/usr/bin/env bash
# SessionStart: warm venv and embedding model in the background; exit fast.
# --root: warm the model this project configures, not the packaged default.
(uv run --project "$CLAUDE_PLUGIN_ROOT/app" hoolint warmup \
    --root "${CLAUDE_PROJECT_DIR:-.}" >/dev/null 2>&1 &)
exit 0
