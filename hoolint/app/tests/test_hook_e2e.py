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


def _run_journal_add(project, payload):
    r = subprocess.run(
        ["python3", str(PLUGIN_ROOT / "hooks" / "journal_add.py")],
        input=payload, text=True, env=_env(project), capture_output=True)
    assert r.returncode == 0, f"{payload!r} exited {r.returncode}: {r.stderr}"
    assert "Traceback" not in r.stderr


def test_journal_add_never_breaks_the_edit(tmp_path):
    """Malformed hook input must exit 0, not crash the Write/Edit it follows.

    Each crash mode gets its own clean project so no trap masks another:
    the path-bearing session_id must hit the nested-open failure, not a
    pre-fired makedirs error.
    """
    # Malformed JSON shapes and a path-bearing session_id, each in a clean dir.
    for i, payload in enumerate(
            ("not json", "null", '"a string"', "[1, 2]",
             '{"tool_input": [1], "session_id": "x"}',
             '{"tool_input": {"file_path": "/p/x.py"}, "session_id": "a/b"}')):
        project = tmp_path / f"clean{i}"
        project.mkdir()
        _run_journal_add(project, payload)

    # .hoolint pre-existing as a file, isolated so it is the only trap in play.
    trap = tmp_path / "trap"
    trap.mkdir()
    (trap / ".hoolint").write_text("i am a file, not a dir")
    _run_journal_add(
        trap, '{"tool_input": {"file_path": "/p/x.py"}, "session_id": "s"}')
