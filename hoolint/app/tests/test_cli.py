import json
import io
import pytest
from hoolint import cli


@pytest.fixture
def project(tmp_path):
    """Project with one blocking verbose comment, journal pre-filled.

    Regex-only on purpose, and it stays that way for the rest of the plan:
    conftest disables the semantic and local_llm tiers, a skipped filter demotes
    its findings to warn, and `escalate` does not exist until Task 10. Because
    this file overrides `verbose-comments` wholesale, these tests keep passing
    unchanged when Task 10 lands the full stock pipeline.
    """
    (tmp_path / "hoolint.toml").write_text(
        '[[rule]]\n'
        'id = "verbose-comments"\n'
        'globs = ["**/*.py"]\n'
        'severity = "block"\n'
        '[[rule.stage]]\n'
        'strategy = "regex"\n'
        'pattern = "(?m)(^[ \\\\t]*# [^\\\\n]*\\\\n){3,}"\n'
        'message = "more than 2 consecutive comment lines"\n'
    )
    f = tmp_path / "m.py"
    f.write_text("# one\n# two\n# three\nx = 1\n")
    from hoolint import journal
    journal.add(tmp_path, "s1", str(f))
    return tmp_path


def _check(project, monkeypatch, capsys, stop_hook_active=False):
    payload = {"session_id": "s1", "stop_hook_active": stop_hook_active}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = cli.main(["check", "--mode", "session", "--root", str(project)])
    return code, capsys.readouterr()


def test_session_block_exits_2_with_feedback(project, monkeypatch, capsys):
    code, out = _check(project, monkeypatch, capsys)
    assert code == 2
    assert "verbose-comments" in out.err
    assert "Fix" in out.err


def test_second_stop_with_no_edits_still_blocks(project, monkeypatch, capsys):
    """The escape hatch: doing nothing must not clear the finding."""
    code, _ = _check(project, monkeypatch, capsys)
    assert code == 2
    code, out = _check(project, monkeypatch, capsys)   # no edits, no re-journal
    assert code == 2
    assert "verbose-comments" in out.err


def test_stand_down_after_two_identical_blocks(project, monkeypatch, capsys):
    _check(project, monkeypatch, capsys)
    _check(project, monkeypatch, capsys)
    code, out = _check(project, monkeypatch, capsys)
    assert code == 0
    assert "stand" in out.out.lower()


def test_waive_survives_a_no_edit_stop_after_stand_down(project, monkeypatch, capsys):
    """The waive window must not close one stop after stand-down.

    block, block, stand-down (fingerprint reported), then one more no-edit
    stop with nothing in scope must still leave that fingerprint waivable.
    """
    _check(project, monkeypatch, capsys)
    _check(project, monkeypatch, capsys)
    code, out = _check(project, monkeypatch, capsys)   # stand-down
    assert code == 0
    fingerprint = out.out.split("[")[1].split("]")[0]

    code, out = _check(project, monkeypatch, capsys)   # no edits, nothing in scope
    assert code == 0
    assert out.out == "" and out.err == ""

    code = cli.main(["waive", fingerprint, "--reason", "user asked for it",
                     "--root", str(project)])
    assert code == 0
    assert "fingerprint" in (project / "hoolint-waivers.toml").read_text()


def test_stand_down_bounds_a_churning_loop(project, monkeypatch, capsys):
    """Editing the span changes fingerprints; the loop must still terminate."""
    f = project / "m.py"
    codes = []
    for i in range(3):
        code, _ = _check(project, monkeypatch, capsys)
        codes.append(code)
        f.write_text(f"# one {i}\n# two {i}\n# three {i}\nx = 1\n")
        from hoolint import journal
        journal.add(project, "s1", str(f))
    assert codes == [2, 2, 0]


def test_waived_finding_does_not_block(project, monkeypatch, capsys):
    code, out = _check(project, monkeypatch, capsys)
    fingerprint = out.err.split("[")[1].split("]")[0]
    cli.main(["waive", fingerprint, "--reason", "user asked for it",
              "--root", str(project)])
    code, _ = _check(project, monkeypatch, capsys)
    assert code == 0


def test_waive_rejects_unsurfaced_fingerprint(project):
    """A violation cannot be pre-waived before hoolint reports it."""
    code = cli.main(["waive", "verbose-comments:m.py:deadbeefdeadbeef",
                     "--reason", "preemptive", "--root", str(project)])
    assert code == 1
    assert not (project / "hoolint-waivers.toml").exists()


def test_git_mode_exits_1_on_block(project):
    import subprocess
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    code = cli.main(["check", "--mode", "git", "--root", str(project)])
    assert code == 1


def test_git_mode_reports_broken_ref_without_passing(project, capsys):
    """git_changed raises when HEAD has commits but no main/master exists;
    a broken check must not silently report success (exit 0)."""
    import subprocess
    for args in (["init", "-b", "trunk"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=project, check=True,
                   capture_output=True)
    code = cli.main(["check", "--mode", "git", "--root", str(project)])
    assert code == 1
    err = capsys.readouterr().err
    assert "git" in err.lower()


def test_session_mode_tolerates_malformed_waivers(project, monkeypatch, capsys):
    """A malformed hoolint-waivers.toml must report but never block Claude."""
    (project / "hoolint-waivers.toml").write_text("not [ valid toml")
    code, out = _check(project, monkeypatch, capsys)
    assert code == 0
    assert "waiver" in (out.out + out.err).lower()


def test_git_mode_reports_malformed_waivers_without_passing(project):
    """Same malformed file in git mode must not silently pass as clean."""
    import subprocess
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    (project / "hoolint-waivers.toml").write_text("not [ valid toml")
    code = cli.main(["check", "--mode", "git", "--root", str(project)])
    assert code == 1


def test_session_mode_tolerates_malformed_config(project, monkeypatch, capsys):
    """A malformed hoolint.toml must report but never block (never exit 1).

    Session-mode exit 1 is NOT exit 2, so a crash lets Claude stop UNBLOCKED
    -- an ordinary typo in a committed config would defeat every block."""
    (project / "hoolint.toml").write_text("this is = = not toml [[[")
    code, out = _check(project, monkeypatch, capsys)
    assert code == 0
    assert "hoolint" in (out.out + out.err).lower()


def test_git_mode_reports_malformed_config_without_passing(project):
    """Same malformed hoolint.toml in git mode must fail closed (exit 1)."""
    import subprocess
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    (project / "hoolint.toml").write_text("this is = = not toml [[[")
    code = cli.main(["check", "--mode", "git", "--root", str(project)])
    assert code == 1


def test_session_mode_tolerates_waiver_missing_fingerprint(project, monkeypatch, capsys):
    """A valid-TOML waiver entry missing `fingerprint` raises KeyError, which
    the waivers-TOMLDecodeError handler does not catch; it must still not
    fail open."""
    (project / "hoolint-waivers.toml").write_text('[[waiver]]\nreason = "x"\n')
    code, out = _check(project, monkeypatch, capsys)
    assert code == 0
    assert "hoolint" in (out.out + out.err).lower()


def test_off_spec_severity_finding_is_not_silently_dropped(tmp_path, monkeypatch, capsys):
    """A trusted custom rule with an off-spec severity (not block/warn) must
    still surface, not vanish from the clean-run systemMessage."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "hoolint_rules").mkdir()
    (tmp_path / "hoolint_rules" / "x.py").write_text(
        'rule = {"id": "custom-info", "globs": ["**/*.py"], "severity": "info",\n'
        '        "stage": [{"strategy": "regex", "pattern": "TODO",\n'
        '                   "message": "leftover TODO"}]}\n')
    assert cli.main(["trust", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    (tmp_path / "m.py").write_text("x = 1  # TODO\n")
    from hoolint import journal
    journal.add(tmp_path, "s1", str(tmp_path / "m.py"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    code = cli.main(["check", "--mode", "session", "--root", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 0
    assert "custom-info" in json.loads(out.out)["systemMessage"]


def test_untrusted_custom_rules_notice_reaches_system_message(tmp_path, monkeypatch, capsys):
    """A bare print() is discarded by the Stop hook; the notice must ride the
    systemMessage JSON instead."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "hoolint_rules").mkdir()
    (tmp_path / "hoolint_rules" / "x.py").write_text(
        'rule = {"id": "custom-x", "globs": ["*.py"], "severity": "warn", "stage": []}\n')
    payload = {"session_id": "s1"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = cli.main(["check", "--mode", "session", "--root", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 0
    msg = json.loads(out.out)["systemMessage"]
    assert "hoolint trust" in msg


def test_trust_subcommand_grants_and_check_then_loads_rule(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "hoolint_rules").mkdir()
    (tmp_path / "hoolint_rules" / "x.py").write_text(
        'rule = {"id": "custom-x", "globs": ["*.py"], "severity": "warn", "stage": []}\n')
    code = cli.main(["trust", "--root", str(tmp_path)])
    assert code == 0
    assert "trusted" in capsys.readouterr().out

    from hoolint import trust
    assert trust.is_trusted(tmp_path) is True

    payload = {"session_id": "s1"}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code = cli.main(["check", "--mode", "session", "--root", str(tmp_path)])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""   # no notice, no warns -- nothing to say


def test_waive_prune_reports_malformed_waivers_without_traceback(project, capsys):
    """`waive --prune` must report a malformed waivers file, not raise.

    The git-unborn RuntimeError path shares its guard with this one but
    isn't reproduced here: an unborn-HEAD repro is finicky to build
    deterministically, while a malformed waivers file is not.
    """
    import subprocess
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "x"], cwd=project, check=True,
                   capture_output=True)
    (project / "hoolint-waivers.toml").write_text("not [ valid toml")
    code = cli.main(["waive", "--prune", "--root", str(project)])
    assert code == 1
    assert "waiver" in capsys.readouterr().err.lower()
