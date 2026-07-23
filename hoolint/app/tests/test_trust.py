import os

from hoolint import trust

RULE_PY = 'rule = {"id": "custom-x", "globs": ["*.py"], "severity": "warn", "stage": []}\n'


def test_untrusted_project_loads_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    rules, notice = trust.load_custom_rules(proj)
    assert rules == []
    assert "hoolint trust" in notice


def test_trusted_project_loads_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    trust.grant(proj)
    rules, notice = trust.load_custom_rules(proj)
    assert [r["id"] for r in rules] == ["custom-x"]
    assert notice is None


def test_modified_rule_file_revokes_trust(tmp_path, monkeypatch):
    """A later commit's rule must not inherit an earlier grant."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    trust.grant(proj)
    (proj / "hoolint_rules" / "evil.py").write_text(RULE_PY)   # added later
    rules, notice = trust.load_custom_rules(proj)
    assert rules == []
    assert "hoolint trust" in notice


def test_edited_rule_file_revokes_trust(tmp_path, monkeypatch):
    """Editing the bytes of an already-granted file must also revoke trust."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    trust.grant(proj)
    (proj / "hoolint_rules" / "x.py").write_text(
        RULE_PY.replace("custom-x", "custom-y"))
    rules, notice = trust.load_custom_rules(proj)
    assert rules == []
    assert "hoolint trust" in notice


def test_broken_rule_file_degrades_without_crashing(tmp_path, monkeypatch):
    """A rule file that raises on exec must not take down the whole check."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "good.py").write_text(RULE_PY)
    (proj / "hoolint_rules" / "bad.py").write_text("raise RuntimeError('boom')\n")
    trust.grant(proj)
    rules, notice = trust.load_custom_rules(proj)
    assert [r["id"] for r in rules] == ["custom-x"]
    assert notice is not None
    assert "bad.py" in notice


def test_rule_file_with_no_rule_dict_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    (proj / "hoolint_rules" / "empty.py").write_text("not_rule = 1\n")
    trust.grant(proj)
    rules, notice = trust.load_custom_rules(proj)
    assert [r["id"] for r in rules] == ["custom-x"]
    assert notice is None


def test_subdir_helper_edit_revokes_trust(tmp_path, monkeypatch):
    """A helper imported from a subdirectory is part of the trusted content."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules" / "sub").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    (proj / "hoolint_rules" / "sub" / "helper.py").write_text("value = 1\n")
    trust.grant(proj)
    assert trust.is_trusted(proj) is True
    (proj / "hoolint_rules" / "sub" / "helper.py").write_text("value = 2\n")
    assert trust.is_trusted(proj) is False


def test_sidecar_data_file_edit_revokes_trust(tmp_path, monkeypatch):
    """A non-.py sidecar read at runtime is part of the trusted content."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    (proj / "hoolint_rules" / "data.json").write_text('{"a": 1}')
    trust.grant(proj)
    assert trust.is_trusted(proj) is True
    (proj / "hoolint_rules" / "data.json").write_text('{"a": 2}')
    assert trust.is_trusted(proj) is False


def test_corrupt_trusted_toml_fails_closed(tmp_path, monkeypatch):
    """A hand-edited/corrupt trust store must mean 'not trusted', never crash."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    trust.grant(proj)
    cfg = tmp_path / "cfg" / "hoolint" / "trusted.toml"
    cfg.write_text("this is not [valid toml")
    assert trust.is_trusted(proj) is False


def test_rule_file_calling_sys_exit_degrades_without_crashing(tmp_path, monkeypatch):
    """A trusted rule file calling sys.exit() must not kill the whole check."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "good.py").write_text(RULE_PY)
    (proj / "hoolint_rules" / "exits.py").write_text("import sys\nsys.exit(3)\n")
    trust.grant(proj)
    rules, notice = trust.load_custom_rules(proj)
    assert [r["id"] for r in rules] == ["custom-x"]
    assert notice is not None
    assert "exits.py" in notice


def test_grant_is_scoped_per_project(tmp_path, monkeypatch):
    """Trusting one project must not trust an unrelated one that reuses a path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj_a = tmp_path / "a"
    (proj_a / "hoolint_rules").mkdir(parents=True)
    (proj_a / "hoolint_rules" / "x.py").write_text(RULE_PY)
    trust.grant(proj_a)

    proj_b = tmp_path / "b"
    (proj_b / "hoolint_rules").mkdir(parents=True)
    (proj_b / "hoolint_rules" / "x.py").write_text(RULE_PY)
    assert trust.is_trusted(proj_a) is True
    assert trust.is_trusted(proj_b) is False


def test_symlinked_dir_under_rules_is_untrustable(tmp_path, monkeypatch):
    """A symlinked directory hides content from rglob; must fail closed, not bypass.

    Regression for a confirmed bypass: rglob("*") does not descend into a
    symlinked directory, so content reached only through the link was
    invisible to the digest and swappable post-grant without detection.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "helper.py").write_text("value = 1\n")
    os.symlink(outside, proj / "hoolint_rules" / "linkeddir")

    assert trust.rules_digest(proj) is None
    assert trust.grant(proj) is False
    assert trust.is_trusted(proj) is False

    # Swap the link's target for something malicious; still never trusted.
    (outside / "helper.py").write_text("import os\nos.system('echo PWNED')\n")
    assert trust.is_trusted(proj) is False


def test_symlinked_file_under_rules_is_untrustable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    outside = tmp_path / "outside_file.py"
    outside.write_text(RULE_PY)
    os.symlink(outside, proj / "hoolint_rules" / "link.py")

    assert trust.rules_digest(proj) is None
    assert trust.grant(proj) is False
    assert trust.is_trusted(proj) is False


def test_normal_subdir_tree_digest_is_still_a_hex_string(tmp_path, monkeypatch):
    """Regression: a real (non-symlinked) subdir tree must still digest and trust."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules" / "sub").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    (proj / "hoolint_rules" / "sub" / "helper.py").write_text("value = 1\n")

    digest = trust.rules_digest(proj)
    assert digest is not None
    assert trust.grant(proj) is True
    assert trust.is_trusted(proj) is True


def test_is_trusted_fails_closed_on_os_error_reading_store(tmp_path, monkeypatch):
    """A trust store that can't be read (permissions, I/O error) must mean untrusted.

    Simulated via a monkeypatched read_text rather than real chmod, since
    permission enforcement is unreliable across filesystems/CI users; the
    corrupt-TOML case above already exercises the decode-error branch.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj = tmp_path / "proj"
    (proj / "hoolint_rules").mkdir(parents=True)
    (proj / "hoolint_rules" / "x.py").write_text(RULE_PY)
    trust.grant(proj)

    from pathlib import Path as _Path
    cfg = tmp_path / "cfg" / "hoolint" / "trusted.toml"
    orig_read_text = _Path.read_text

    def boom(self, *a, **kw):
        if self == cfg:
            raise PermissionError("simulated permission error")
        return orig_read_text(self, *a, **kw)

    monkeypatch.setattr(_Path, "read_text", boom)
    assert trust.is_trusted(proj) is False


def test_grant_refuses_rather_than_wiping_corrupt_store(tmp_path, monkeypatch):
    """A corrupt store must not be silently overwritten and lose other grants."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    proj_a = tmp_path / "a"
    (proj_a / "hoolint_rules").mkdir(parents=True)
    (proj_a / "hoolint_rules" / "x.py").write_text(RULE_PY)
    trust.grant(proj_a)

    cfg = tmp_path / "cfg" / "hoolint" / "trusted.toml"
    cfg.write_text("this is not [valid toml")

    proj_b = tmp_path / "b"
    (proj_b / "hoolint_rules").mkdir(parents=True)
    (proj_b / "hoolint_rules" / "x.py").write_text(RULE_PY)
    assert trust.grant(proj_b) is False
    assert cfg.read_text() == "this is not [valid toml"
