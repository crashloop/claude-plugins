"""End-to-end: canned hook JSON through the real hook scripts."""
import json
import os
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]   # hoolint/


def _env(project):
    return {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
            "CLAUDE_PROJECT_DIR": str(project)}


def test_journal_then_stop_blocks(tmp_path):
    # Filter-free rule: the stock pipeline's skipped filters would demote to warn.
    (tmp_path / "hoolint.toml").write_text(
        '[[rule]]\nid = "verbose-comments"\nglobs = ["**/*.py"]\n'
        'severity = "block"\n[[rule.stage]]\nstrategy = "regex"\n'
        'pattern = "(?m)(^[ \\\\t]*# [^\\\\n]*\\\\n){3,}"\n'
        'message = "more than 2 consecutive comment lines"\n')
    bad = tmp_path / "m.py"
    bad.write_text("# one\n# two\n# three\nx = 1\n")
    post = json.dumps({"session_id": "e2e",
                       "tool_input": {"file_path": str(bad)}})
    r = subprocess.run(
        ["python3", str(PLUGIN_ROOT / "hooks" / "journal_add.py")],
        input=post, text=True, env=_env(tmp_path), capture_output=True)
    assert r.returncode == 0
    stop = json.dumps({"session_id": "e2e"})
    r = subprocess.run(
        ["bash", str(PLUGIN_ROOT / "hooks" / "stop_check.sh")],
        input=stop, text=True, env=_env(tmp_path), capture_output=True)
    assert r.returncode == 2
    assert "verbose-comments" in r.stderr
