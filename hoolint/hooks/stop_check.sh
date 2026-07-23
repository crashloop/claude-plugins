#!/usr/bin/env bash
# Stop: run the session-mode check; stdin (hook JSON) flows through.
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
exec uv run --project "$CLAUDE_PLUGIN_ROOT/app" hoolint check --mode session
