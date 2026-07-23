#!/usr/bin/env bash
# SessionStart: warm venv and embedding model in the background; exit fast.
(uv run --project "$CLAUDE_PLUGIN_ROOT/app" hoolint warmup >/dev/null 2>&1 &)
exit 0
