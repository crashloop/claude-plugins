# hoolint Metadata Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four hoolint rules that inspect the change set and repository history rather than
the contents of a single file: companion file, change size, churn, and commit metadata.

**Architecture:** Three small engine changes expose the change set to strategies and let a rule
declare which modes it applies to. Four new generator strategies live in two modules split by
data source: `changeset_.py` is pure and reads the context, `githist_.py` shells out to git.
Git failures raise and are converted to visible warn findings by the existing `engine._guarded`.

**Tech Stack:** Python 3.13+, uv, pytest, google-re2 (already a dependency).

**Spec:** `docs/superpowers/specs/2026-07-28-hoolint-metadata-rules-design.md`. Read its
"Context for implementers" section before starting.

## Global Constraints

- Branch is `feat/hoolint-strategies`, based on `feat/hoolint` at `8bb526c`. Do not touch
  `feat/hoolint`.
- Verify with `cd hoolint/app && uv run pytest -q`. Baseline is 102 passed, 1 deselected. The
  deselected test is a slow model-download calibration test excluded by
  `addopts = "-m 'not slow'"`. Do not try to make it run.
- `src/hoolint/defaults.toml` must not change. No rule in this plan ships enabled by default.
- Never commit anything under `docs/`. A global constraint forbids it.
- Regex uses `google-re2` (`import re2`), never stdlib `re`. Patterns come from committed config
  and RE2's linear-time guarantee means no pattern can hang the check. No lookaround.
- A failure must be visible: a warn finding, a raised exception, or a notice. It must never be
  an empty list that reads as clean. This is the defect class that recurred through all 13 tasks
  of the original hoolint plan.
- Line 100 max. Google-style docstrings on public functions and classes.
- Pyright import errors in the editor are false positives. The test suite is the source of truth.

---

### Task 1: Expose the change set on Context

**Files:**
- Modify: `hoolint/app/src/hoolint/strategies/base.py`
- Modify: `hoolint/app/src/hoolint/engine.py`
- Test: `hoolint/app/tests/test_engine.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Context.changed: list[Path]` (the full change set) and
  `Context.matched: list[Path]` (this rule's glob subset). Also
  `base.anchored_finding(ctx: Context, message: str) -> Finding`, which every metadata strategy
  in later tasks uses to build its finding.

- [ ] **Step 1: Write the failing test**

Add to `hoolint/app/tests/test_engine.py`:

```python
def test_context_carries_changed_and_matched(tmp_path):
    """Strategies need the whole change set, not just the file they run on."""
    from hoolint.config import Config
    from hoolint.engine import run
    from hoolint.strategies import STRATEGIES

    py = tmp_path / "a.py"
    py.write_text("x = 1\n")
    md = tmp_path / "notes.md"
    md.write_text("hello\n")
    seen = {}

    class Probe:
        def run(self, candidates, stage, ctx):
            seen["changed"] = sorted(p.name for p in ctx.changed)
            seen["matched"] = sorted(p.name for p in ctx.matched)
            return []

    STRATEGIES["probe"] = Probe()
    try:
        cfg = Config(rules=[{"id": "probe-rule", "globs": ["**/*.py"],
                             "severity": "warn",
                             "stage": [{"strategy": "probe"}]}],
                     settings={})
        run(cfg, [py, md], tmp_path, "git")
    finally:
        del STRATEGIES["probe"]

    assert seen["changed"] == ["a.py", "notes.md"]   # full change set
    assert seen["matched"] == ["a.py"]               # only the glob subset
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd hoolint/app && uv run pytest tests/test_engine.py::test_context_carries_changed_and_matched -v`
Expected: FAIL with `TypeError` about unexpected keyword, or a `KeyError` on `seen`, because
`Context` has no `changed` or `matched` field yet.

- [ ] **Step 3: Add the fields to Context**

In `src/hoolint/strategies/base.py`, add the import and the two fields. Both have defaults, so
they must come after the existing non-default fields:

```python
from dataclasses import dataclass, field
from pathlib import Path

from hoolint.findings import Finding


@dataclass
class Context:
    path: Path
    root: Path
    mode: str            # "session" | "git"
    settings: dict
    rule_id: str
    severity: str
    changed: list[Path] = field(default_factory=list)
    matched: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    filter_skipped: bool = False
    _content: str | None = None
```

Leave the existing `content`, `warn`, and `skip_filter` methods untouched.

- [ ] **Step 4: Add the shared finding helper**

Append to `src/hoolint/strategies/base.py`, after the `Context` class:

```python
def anchored_finding(ctx: Context, message: str) -> Finding:
    """Build a finding anchored to the file itself, for rules with no code span.

    Metadata rules describe how a file relates to other files, not a span inside it. The span is
    the file's own relative path, so the fingerprint is stable for that file. Waivers on metadata
    findings are therefore durable by design: they do not expire when the file's contents change.

    Args:
        ctx: Per-file execution context.
        message: The finding's human-readable message.

    Returns:
        A Finding anchored to ctx.path, carrying the rule's configured severity.
    """
    rel = str(ctx.path.relative_to(ctx.root))
    return Finding(rule_id=ctx.rule_id, file=rel, start_line=1, end_line=1,
                   span_text=rel, message=message, severity=ctx.severity)
```

- [ ] **Step 5: Wire the fields in the engine**

In `src/hoolint/engine.py`, inside `_run_rule`, pass both new fields when building the context.
`files` is the full change set and `matched` is already computed just above:

```python
        ctx = Context(path=path, root=root, mode=mode, settings=settings,
                      rule_id=rule["id"], severity=rule.get("severity", "warn"),
                      changed=files, matched=matched)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd hoolint/app && uv run pytest tests/test_engine.py::test_context_carries_changed_and_matched -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 103 passed, 1 deselected

- [ ] **Step 8: Commit**

```bash
git add hoolint/app/src/hoolint/strategies/base.py hoolint/app/src/hoolint/engine.py \
        hoolint/app/tests/test_engine.py
git commit -m "feat(hoolint): expose the change set on Context for metadata rules"
```

---

### Task 2: Rule-level mode filtering

**Files:**
- Modify: `hoolint/app/src/hoolint/config.py`
- Modify: `hoolint/app/src/hoolint/engine.py`
- Test: `hoolint/app/tests/test_config.py`, `hoolint/app/tests/test_engine.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: a rule-level `modes` key, a list containing `"session"`, `"git"`, or both. Omitting
  the key means the rule runs in both modes. `load_config` raises `ValueError` on an unknown or
  malformed value. Later tasks use `modes = ["git"]` in their documented example config.

- [ ] **Step 1: Write the failing tests**

Add to `hoolint/app/tests/test_config.py`:

```python
import pytest


def test_unknown_mode_raises_at_config_load(tmp_path):
    """A typo in modes must fail loudly. Silently never running is a silent pass."""
    (tmp_path / "hoolint.toml").write_text(
        '[[rule]]\nid = "r"\nglobs = ["*.py"]\nmodes = ["sesion"]\n'
    )
    with pytest.raises(ValueError, match="unknown mode"):
        load_config(tmp_path)


def test_empty_modes_list_raises_at_config_load(tmp_path):
    """An empty list would disable the rule everywhere while looking configured."""
    (tmp_path / "hoolint.toml").write_text(
        '[[rule]]\nid = "r"\nglobs = ["*.py"]\nmodes = []\n'
    )
    with pytest.raises(ValueError, match="non-empty list"):
        load_config(tmp_path)
```

Add to `hoolint/app/tests/test_engine.py`:

```python
def test_modes_restricts_which_rules_run(tmp_path):
    """A git-only rule must not run in session mode, and must run in git mode."""
    from hoolint.config import Config
    from hoolint.engine import run
    from hoolint.strategies import STRATEGIES

    py = tmp_path / "a.py"
    py.write_text("x = 1\n")
    calls = []

    class Probe:
        def run(self, candidates, stage, ctx):
            calls.append(ctx.mode)
            return []

    STRATEGIES["probe2"] = Probe()
    try:
        cfg = Config(rules=[{"id": "git-only", "globs": ["**/*.py"],
                             "severity": "warn", "modes": ["git"],
                             "stage": [{"strategy": "probe2"}]}],
                     settings={})
        run(cfg, [py], tmp_path, "session")
        assert calls == []            # skipped: wrong mode
        run(cfg, [py], tmp_path, "git")
        assert calls == ["git"]       # ran: right mode
    finally:
        del STRATEGIES["probe2"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd hoolint/app && uv run pytest tests/test_config.py -k "mode" tests/test_engine.py -k "modes" -v`
Expected: FAIL. The config tests fail because nothing raises. The engine test fails on
`assert calls == []` because the rule runs in both modes.

- [ ] **Step 3: Validate modes at config load**

In `src/hoolint/config.py`, add the constant at module level and the validation loop inside
`load_config`, immediately before the `return Config(...)`:

```python
VALID_MODES = ("session", "git")
```

```python
    for r in rules.values():
        modes = r.get("modes")
        if modes is None:
            continue
        if not isinstance(modes, list) or not modes:
            raise ValueError(
                f"rule {r['id']}: modes must be a non-empty list of {list(VALID_MODES)}")
        unknown = [m for m in modes if m not in VALID_MODES]
        if unknown:
            raise ValueError(
                f"rule {r['id']}: unknown mode(s) {unknown}; valid modes are "
                f"{list(VALID_MODES)}")
```

Note: `load_config` raising is already handled. `cli._cmd_check` wraps the whole check in a
fail-safe that reports via systemMessage and returns 0 in session mode, and returns 1 in git
mode. No CLI change is needed.

- [ ] **Step 4: Filter rules by mode in the engine**

In `src/hoolint/engine.py`, replace the body of `run`:

```python
def run(cfg: Config, files: list[Path], root: Path, mode: str) -> list[Finding]:
    """Execute all rules that apply to this mode; rules run in parallel, stages sequentially."""
    applicable = [r for r in cfg.rules if mode in r.get("modes", list(VALID_MODES))]
    # ponytail: thread pool; process pool only if CPU-bound rules dominate
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(_guarded, r, files, root, mode, cfg.settings)
                   for r in applicable]
        return [f for fut in futures for f in fut.result()]
```

Add the import at the top of `engine.py`:

```python
from hoolint.config import Config, VALID_MODES
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd hoolint/app && uv run pytest tests/test_config.py tests/test_engine.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 106 passed, 1 deselected

- [ ] **Step 7: Commit**

```bash
git add hoolint/app/src/hoolint/config.py hoolint/app/src/hoolint/engine.py \
        hoolint/app/tests/test_config.py hoolint/app/tests/test_engine.py
git commit -m "feat(hoolint): rule-level modes filtering, validated at config load"
```

---

### Task 3: The companion strategy

**Files:**
- Create: `hoolint/app/src/hoolint/strategies/changeset_.py`
- Modify: `hoolint/app/src/hoolint/strategies/__init__.py`
- Test: `hoolint/app/tests/test_changeset.py`

**Interfaces:**
- Consumes: `Context.changed`, `Context.matched`, and `anchored_finding` from Task 1.
- Produces: `CompanionStrategy`, registered as `"companion"`. Stage config keys: `requires` (a
  fixed path), or `requires_from` plus `requires_to` (an re2 pattern and substitution), plus an
  optional `message`. Task 4 adds a second class to this same module.

- [ ] **Step 1: Write the failing tests**

Create `hoolint/app/tests/test_changeset.py`:

```python
import pytest
from pathlib import Path

from hoolint.strategies.base import Context
from hoolint.strategies.changeset_ import CompanionStrategy


def _ctx(tmp_path, name, changed_names):
    """Build a Context as the engine would, with a synthetic change set."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n")
    changed = []
    for n in changed_names:
        p = tmp_path / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n")
        changed.append(p)
    return Context(path=path, root=tmp_path, mode="git", settings={},
                   rule_id="companion-rule", severity="warn",
                   changed=changed, matched=[path])


def test_fixed_target_missing_is_flagged(tmp_path):
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py"])
    out = CompanionStrategy().run(None, {"requires": "CHANGELOG.md"}, ctx)
    assert len(out) == 1
    assert "CHANGELOG.md" in out[0].message
    assert out[0].file == "src/api.py"      # anchored to the changed file
    assert out[0].severity == "warn"        # takes the rule's severity


def test_fixed_target_present_is_silent(tmp_path):
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py", "CHANGELOG.md"])
    assert CompanionStrategy().run(None, {"requires": "CHANGELOG.md"}, ctx) == []


def test_derived_target_missing_is_flagged(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"tests/test_\1.py"}
    out = CompanionStrategy().run(None, stage, ctx)
    assert len(out) == 1
    assert "tests/test_foo.py" in out[0].message


def test_derived_target_present_is_silent(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py", "tests/test_foo.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"tests/test_\1.py"}
    assert CompanionStrategy().run(None, stage, ctx) == []


def test_derived_pattern_that_does_not_match_is_silent(tmp_path):
    """A rule whose glob is wider than its pattern must not flag unrelated files."""
    ctx = _ctx(tmp_path, "docs/guide.py", ["docs/guide.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"tests/test_\1.py"}
    assert CompanionStrategy().run(None, stage, ctx) == []


def test_mutually_exclusive_config_raises(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    stage = {"requires": "CHANGELOG.md", "requires_from": "a", "requires_to": "b"}
    with pytest.raises(ValueError, match="mutually exclusive"):
        CompanionStrategy().run(None, stage, ctx)


def test_incomplete_derived_config_raises(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    with pytest.raises(ValueError, match="requires_from and requires_to"):
        CompanionStrategy().run(None, {"requires_from": r"src/(.*)\.py"}, ctx)


def test_derived_path_escaping_the_root_raises(tmp_path):
    ctx = _ctx(tmp_path, "src/foo.py", ["src/foo.py"])
    stage = {"requires_from": r"src/(.*)\.py", "requires_to": r"../outside/\1.py"}
    with pytest.raises(ValueError, match="escapes the project root"):
        CompanionStrategy().run(None, stage, ctx)


def test_companion_ignores_incoming_candidates(tmp_path):
    """Generators never filter. A non-None candidate list means a misconfigured stage."""
    ctx = _ctx(tmp_path, "src/api.py", ["src/api.py"])
    assert CompanionStrategy().run([], {"requires": "CHANGELOG.md"}, ctx) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd hoolint/app && uv run pytest tests/test_changeset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hoolint.strategies.changeset_'`

- [ ] **Step 3: Write the module**

Create `src/hoolint/strategies/changeset_.py`:

```python
"""Change-set strategies: rules about which files changed together.

Pure. These read the change set already on the Context and perform no I/O beyond resolving
paths, so they have no failure mode other than invalid configuration, which raises.
"""
from pathlib import Path

import re2

from hoolint.findings import Finding
from hoolint.strategies.base import Context, anchored_finding


def _rel(p: Path, ctx: Context) -> str:
    """The path relative to the project root, resolving both sides."""
    try:
        return str(p.resolve().relative_to(ctx.root.resolve()))
    except ValueError:
        return str(p)


class CompanionStrategy:
    """Generator: flags a changed file whose required companion did not also change."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag this file if the companion it requires is absent from the change set.

        Args:
            candidates: Ignored; this strategy generates rather than filters.
            stage: Stage config: `requires`, or `requires_from` plus `requires_to`, and an
                optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding if the companion did not change, otherwise an empty list.

        Raises:
            ValueError: If the stage config is contradictory or incomplete, or if a derived
                path escapes the project root.
        """
        if candidates is not None:
            return []
        target = self._target(stage, ctx)
        if target is None:
            return []
        if target in {_rel(p, ctx) for p in ctx.changed}:
            return []
        message = stage.get("message", f"changed without {target}")
        return [anchored_finding(ctx, message)]

    def _target(self, stage: dict, ctx: Context) -> str | None:
        """The companion path this file requires, or None if the rule does not apply.

        Args:
            stage: Stage config.
            ctx: Per-file execution context.

        Returns:
            The required companion's path relative to the root, or None when a derived
            pattern does not match this file.

        Raises:
            ValueError: On contradictory or incomplete config, or an escaping path.
        """
        fixed = stage.get("requires")
        frm, to = stage.get("requires_from"), stage.get("requires_to")
        if fixed and (frm or to):
            raise ValueError(
                "companion: `requires` and `requires_from`/`requires_to` are mutually exclusive")
        if fixed:
            return fixed
        if not (frm and to):
            raise ValueError(
                "companion: set `requires`, or both `requires_from` and `requires_to`")
        rel = _rel(ctx.path, ctx)
        if not re2.fullmatch(frm, rel):
            return None
        derived = re2.sub(frm, to, rel)
        if not (ctx.root / derived).resolve().is_relative_to(ctx.root.resolve()):
            raise ValueError(f"companion: derived path escapes the project root: {derived}")
        return derived
```

- [ ] **Step 4: Register the strategy**

In `src/hoolint/strategies/__init__.py`, add the import and the registry entry:

```python
from hoolint.strategies.changeset_ import CompanionStrategy
```

```python
    "companion": CompanionStrategy(),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd hoolint/app && uv run pytest tests/test_changeset.py -v`
Expected: PASS, 9 tests

- [ ] **Step 6: Run the full suite**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 115 passed, 1 deselected

- [ ] **Step 7: Commit**

```bash
git add hoolint/app/src/hoolint/strategies/changeset_.py \
        hoolint/app/src/hoolint/strategies/__init__.py \
        hoolint/app/tests/test_changeset.py
git commit -m "feat(hoolint): companion strategy for files that must change together"
```

---

### Task 4: The change_size strategy

**Files:**
- Modify: `hoolint/app/src/hoolint/strategies/changeset_.py`
- Modify: `hoolint/app/src/hoolint/strategies/__init__.py`
- Test: `hoolint/app/tests/test_changeset.py`

**Interfaces:**
- Consumes: `Context.changed`, `Context.matched`, `anchored_finding` from Task 1; the
  `changeset_` module created in Task 3.
- Produces: `ChangeSizeStrategy`, registered as `"change_size"`. Stage config keys: `max_files`
  (default 20) and an optional `message`.

- [ ] **Step 1: Write the failing tests**

Append to `hoolint/app/tests/test_changeset.py`:

```python
def test_change_size_under_limit_is_silent(tmp_path):
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.py"])
    assert ChangeSizeStrategy().run(None, {"max_files": 5}, ctx) == []


def test_change_size_over_limit_is_flagged(tmp_path):
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.py", "c.py"])
    out = ChangeSizeStrategy().run(None, {"max_files": 2}, ctx)
    assert len(out) == 1
    assert "3" in out[0].message


def test_change_size_emits_exactly_once_across_matched_files(tmp_path):
    """The check describes the whole change set, so it must not repeat per file."""
    from hoolint.config import Config
    from hoolint.engine import run

    files = []
    for i in range(5):
        p = tmp_path / f"f{i}.py"
        p.write_text("x = 1\n")
        files.append(p)
    cfg = Config(rules=[{"id": "blast-radius", "globs": ["**/*.py"], "severity": "warn",
                         "stage": [{"strategy": "change_size", "max_files": 2}]}],
                 settings={})
    out = run(cfg, files, tmp_path, "git")
    assert len(out) == 1, f"expected one set-level finding, got {len(out)}"


def test_change_size_counts_the_whole_change_set_not_the_glob_subset(tmp_path):
    """Blast radius is about the whole change, even when the rule's globs are narrow."""
    from hoolint.strategies.changeset_ import ChangeSizeStrategy
    ctx = _ctx(tmp_path, "a.py", ["a.py", "b.md", "c.md", "d.md"])
    out = ChangeSizeStrategy().run(None, {"max_files": 3}, ctx)
    assert len(out) == 1
    assert "4" in out[0].message
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd hoolint/app && uv run pytest tests/test_changeset.py -k "change_size" -v`
Expected: FAIL with `ImportError: cannot import name 'ChangeSizeStrategy'`

- [ ] **Step 3: Add the strategy**

Append to `src/hoolint/strategies/changeset_.py`:

```python
class ChangeSizeStrategy:
    """Generator: flags a change set that touches too many files."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag an oversized change, reporting once for the whole set.

        The engine invokes a strategy once per matched file, but this check describes the whole
        change set. It therefore emits only from a deterministic anchor, the first matched file
        in sorted order, so the run yields exactly one finding with a stable fingerprint.

        `max_files` counts the entire change set, not the rule's glob subset, because blast
        radius is the point. Line counts are deliberately unsupported: the session journal
        records paths only, so a line threshold would silently mean nothing in session mode.

        Args:
            candidates: Ignored; this strategy generates rather than filters.
            stage: Stage config: `max_files` (default 20) and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding when the change set exceeds `max_files`, otherwise an empty list.
        """
        if candidates is not None:
            return []
        if not ctx.matched or ctx.path != sorted(ctx.matched)[0]:
            return []
        max_files = stage.get("max_files", 20)
        count = len(ctx.changed)
        if count <= max_files:
            return []
        message = stage.get(
            "message", f"change touches {count} files (max {max_files})")
        return [anchored_finding(ctx, message)]
```

- [ ] **Step 4: Register the strategy**

In `src/hoolint/strategies/__init__.py`, extend the existing import and add the entry:

```python
from hoolint.strategies.changeset_ import ChangeSizeStrategy, CompanionStrategy
```

```python
    "change_size": ChangeSizeStrategy(),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd hoolint/app && uv run pytest tests/test_changeset.py -v`
Expected: PASS, 13 tests

- [ ] **Step 6: Run the full suite**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 119 passed, 1 deselected

- [ ] **Step 7: Commit**

```bash
git add hoolint/app/src/hoolint/strategies/changeset_.py \
        hoolint/app/src/hoolint/strategies/__init__.py \
        hoolint/app/tests/test_changeset.py
git commit -m "feat(hoolint): change_size strategy with set-level anchoring"
```

---

### Task 5: The churn strategy and a public git runner

**Files:**
- Modify: `hoolint/app/src/hoolint/changes.py`
- Create: `hoolint/app/src/hoolint/strategies/githist_.py`
- Modify: `hoolint/app/src/hoolint/strategies/__init__.py`
- Test: `hoolint/app/tests/test_githist.py`

**Interfaces:**
- Consumes: `anchored_finding` from Task 1.
- Produces: `changes.run_git(root, *args, check=True) -> subprocess.CompletedProcess`, the
  renamed public form of the existing private `_run`. It raises `RuntimeError` when `check` is
  True and git exits nonzero. Also `ChurnStrategy`, registered as `"churn"`. Stage config keys:
  `max_commits` (default 5), `window` (default `"30.days"`), and an optional `message`. Task 6
  adds a second class to `githist_.py`.

- [ ] **Step 1: Write the failing tests**

Create `hoolint/app/tests/test_githist.py`:

```python
import subprocess
from pathlib import Path

from hoolint.config import Config
from hoolint.engine import run
from hoolint.strategies.base import Context
from hoolint.strategies.githist_ import ChurnStrategy


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _repo(tmp_path):
    """An initialised repo with an identity configured, and no commits yet."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _ctx(root, name):
    path = root / name
    return Context(path=path, root=root, mode="git", settings={},
                   rule_id="churn-rule", severity="warn",
                   changed=[path], matched=[path])


def _commit_n_times(repo, name, n):
    for i in range(n):
        (repo / name).write_text(f"x = {i}\n")
        _git(repo, "add", name)
        _git(repo, "commit", "-m", f"change {i}")


def test_churn_under_threshold_is_silent(tmp_path):
    repo = _repo(tmp_path)
    _commit_n_times(repo, "a.py", 2)
    out = ChurnStrategy().run(None, {"max_commits": 5}, _ctx(repo, "a.py"))
    assert out == []


def test_churn_over_threshold_is_flagged(tmp_path):
    repo = _repo(tmp_path)
    _commit_n_times(repo, "a.py", 4)
    out = ChurnStrategy().run(None, {"max_commits": 2}, _ctx(repo, "a.py"))
    assert len(out) == 1
    assert "a.py" in out[0].message
    assert out[0].file == "a.py"


def test_churn_on_unborn_head_is_silent_not_a_crash(tmp_path):
    """A repo with no commits has no history. Zero churn is a result, not an error."""
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    out = ChurnStrategy().run(None, {"max_commits": 0}, _ctx(repo, "a.py"))
    assert out == []


def test_git_failure_is_visible_never_a_silent_clean(tmp_path):
    """The discriminating test: a broken git invocation must surface as a finding.

    tmp_path is deliberately not a git repository. An implementation that swallows the error
    and returns [] makes a broken check read as a clean one, which is the defect class this
    codebase treats as unacceptable.
    """
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    cfg = Config(rules=[{"id": "churn-rule", "globs": ["**/*.py"], "severity": "warn",
                         "stage": [{"strategy": "churn", "max_commits": 0}]}],
                 settings={})
    out = run(cfg, [f], tmp_path, "git")
    assert out, "a git failure produced no findings: a broken check read as clean"
    assert "rule failed" in out[0].message
    assert out[0].severity == "warn"


def test_churn_ignores_incoming_candidates(tmp_path):
    repo = _repo(tmp_path)
    _commit_n_times(repo, "a.py", 4)
    assert ChurnStrategy().run([], {"max_commits": 0}, _ctx(repo, "a.py")) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd hoolint/app && uv run pytest tests/test_githist.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hoolint.strategies.githist_'`

- [ ] **Step 3: Make the git runner public**

In `src/hoolint/changes.py`, rename `_run` to `run_git` and update its four internal call sites.
No test references the old name, so this rename is safe. The body and docstring are unchanged
apart from the name:

```python
def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
```

The four call sites inside `git_changed` become:

```python
        head = run_git(root, "rev-parse", "--verify", "HEAD", check=False)
```
```python
                r = run_git(root, "merge-base", "HEAD", base, check=False)
```
```python
        diff = _split_nul(run_git(root, "diff", "--name-only", "-z", diff_ref).stdout)
```
```python
    untracked = _split_nul(
        run_git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout)
```

- [ ] **Step 4: Write the module**

Create `src/hoolint/strategies/githist_.py`:

```python
"""Git-history strategies: rules about how a file has changed over time.

Every git failure raises. `engine._guarded` converts the exception into a visible warn finding,
so a missing binary, a non-repository, or a non-zero exit can never read as a clean check. That
reuses one tested degradation path rather than adding a second.
"""
from hoolint.changes import run_git
from hoolint.findings import Finding
from hoolint.strategies.base import Context, anchored_finding


def _has_commits(ctx: Context) -> bool:
    """Whether HEAD resolves, distinguishing an unborn HEAD from a broken environment.

    `rev-parse --verify HEAD` fails for both an unborn HEAD and a non-repository, so probing it
    alone would swallow a real error as "no history" and return a clean result from a check that
    never ran. The `--git-dir` probe runs with check=True first, so a missing git binary or a
    non-repository raises and surfaces as a visible warn finding.

    Args:
        ctx: Per-file execution context.

    Returns:
        True if HEAD resolves to a commit, False for a valid repository with no commits yet.

    Raises:
        RuntimeError: If the directory is not a git repository, or git is unavailable.
    """
    run_git(ctx.root, "rev-parse", "--git-dir")
    return run_git(ctx.root, "rev-parse", "--verify", "HEAD", check=False).returncode == 0


class ChurnStrategy:
    """Generator: flags a file revised too many times within a window."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Flag this file when its recent commit count exceeds the threshold.

        Args:
            candidates: Ignored; this strategy generates rather than filters.
            stage: Stage config: `max_commits` (default 5), `window` (default "30.days",
                passed to `git log --since`), and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding when the file is churning, otherwise an empty list.

        Raises:
            RuntimeError: If git fails. The engine's guard turns this into a visible warn.
        """
        if candidates is not None:
            return []
        if not _has_commits(ctx):
            return []
        rel = str(ctx.path.relative_to(ctx.root))
        window = stage.get("window", "30.days")
        out = run_git(ctx.root, "log", f"--since={window}", "--format=%H", "--", rel)
        count = len([line for line in out.stdout.splitlines() if line.strip()])
        max_commits = stage.get("max_commits", 5)
        if count <= max_commits:
            return []
        message = stage.get(
            "message",
            f"{rel} changed {count} times in {window} (max {max_commits})")
        return [anchored_finding(ctx, message)]
```

Note: this module has no `re2` import yet. Task 6 adds one when it adds `CommitMetaStrategy`.

- [ ] **Step 5: Register the strategy**

In `src/hoolint/strategies/__init__.py`:

```python
from hoolint.strategies.githist_ import ChurnStrategy
```

```python
    "churn": ChurnStrategy(),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd hoolint/app && uv run pytest tests/test_githist.py -v`
Expected: PASS, 5 tests

- [ ] **Step 7: Run the full suite**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 124 passed, 1 deselected

- [ ] **Step 8: Commit**

```bash
git add hoolint/app/src/hoolint/changes.py \
        hoolint/app/src/hoolint/strategies/githist_.py \
        hoolint/app/src/hoolint/strategies/__init__.py \
        hoolint/app/tests/test_githist.py
git commit -m "feat(hoolint): churn strategy; make the git runner public for reuse"
```

---

### Task 6: The commit_meta strategy

**Files:**
- Modify: `hoolint/app/src/hoolint/strategies/githist_.py`
- Modify: `hoolint/app/src/hoolint/strategies/__init__.py`
- Test: `hoolint/app/tests/test_githist.py`

**Interfaces:**
- Consumes: `run_git` and `_has_commits` from Task 5, `anchored_finding` from Task 1.
- Produces: `CommitMetaStrategy`, registered as `"commit_meta"`. Stage config keys:
  `subject_pattern` (an re2 pattern matched against the full commit subject) and an optional
  `message`.

- [ ] **Step 1: Write the failing tests**

Append to `hoolint/app/tests/test_githist.py`:

```python
CONVENTION = r"(feat|fix|docs|test|chore)(\(.+\))?: .+"


def test_commit_meta_accepts_a_conforming_subject(tmp_path):
    from hoolint.strategies.githist_ import CommitMetaStrategy
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "feat(api): add the thing")
    out = CommitMetaStrategy().run(None, {"subject_pattern": CONVENTION},
                                   _ctx(repo, "a.py"))
    assert out == []


def test_commit_meta_flags_a_malformed_subject(tmp_path):
    from hoolint.strategies.githist_ import CommitMetaStrategy
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-m", "did some stuff")
    out = CommitMetaStrategy().run(None, {"subject_pattern": CONVENTION},
                                   _ctx(repo, "a.py"))
    assert len(out) == 1
    assert "did some stuff" in out[0].message


def test_commit_meta_on_unborn_head_is_silent(tmp_path):
    """No commit exists yet, so there is no subject to judge."""
    from hoolint.strategies.githist_ import CommitMetaStrategy
    repo = _repo(tmp_path)
    (repo / "a.py").write_text("x = 1\n")
    out = CommitMetaStrategy().run(None, {"subject_pattern": CONVENTION},
                                   _ctx(repo, "a.py"))
    assert out == []


def test_commit_meta_emits_exactly_once_across_matched_files(tmp_path):
    """The commit subject describes the whole change, so it must not repeat per file."""
    repo = _repo(tmp_path)
    files = []
    for i in range(4):
        p = repo / f"f{i}.py"
        p.write_text("x = 1\n")
        files.append(p)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "did some stuff")
    cfg = Config(rules=[{"id": "commit-subject", "globs": ["**/*.py"], "severity": "warn",
                         "stage": [{"strategy": "commit_meta",
                                    "subject_pattern": CONVENTION}]}],
                 settings={})
    out = run(cfg, files, repo, "git")
    assert len(out) == 1, f"expected one set-level finding, got {len(out)}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd hoolint/app && uv run pytest tests/test_githist.py -k "commit_meta" -v`
Expected: FAIL with `ImportError: cannot import name 'CommitMetaStrategy'`

- [ ] **Step 3: Add the strategy**

First add the `re2` import at the top of `src/hoolint/strategies/githist_.py`, above the
`from hoolint.changes import run_git` line:

```python
import re2
```

Then append the class:

```python
class CommitMetaStrategy:
    """Generator: flags a commit subject that breaks the project's convention."""

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Judge the most recent commit subject against a pattern, once per run.

        The subject describes the whole change, so this emits only from a deterministic anchor,
        the first matched file in sorted order. In practice this rule belongs in git mode: at
        Stop time in a session there is usually no new commit to inspect.

        Args:
            candidates: Ignored; this strategy generates rather than filters.
            stage: Stage config: `subject_pattern`, an re2 pattern matched against the whole
                subject, and an optional `message`.
            ctx: Per-file execution context.

        Returns:
            One finding when the subject does not match, otherwise an empty list.

        Raises:
            RuntimeError: If git fails. The engine's guard turns this into a visible warn.
            KeyError: If `subject_pattern` is absent, which is a config error.
        """
        if candidates is not None:
            return []
        if not ctx.matched or ctx.path != sorted(ctx.matched)[0]:
            return []
        if not _has_commits(ctx):
            return []
        subject = run_git(ctx.root, "log", "-1", "--format=%s").stdout.strip()
        if re2.fullmatch(stage["subject_pattern"], subject):
            return []
        message = stage.get(
            "message", f"commit subject does not match the convention: {subject!r}")
        return [anchored_finding(ctx, message)]
```

- [ ] **Step 4: Register the strategy**

In `src/hoolint/strategies/__init__.py`, extend the import and add the entry:

```python
from hoolint.strategies.githist_ import ChurnStrategy, CommitMetaStrategy
```

```python
    "commit_meta": CommitMetaStrategy(),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd hoolint/app && uv run pytest tests/test_githist.py -v`
Expected: PASS, 9 tests

- [ ] **Step 6: Run the full suite**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 128 passed, 1 deselected

- [ ] **Step 7: Commit**

```bash
git add hoolint/app/src/hoolint/strategies/githist_.py \
        hoolint/app/src/hoolint/strategies/__init__.py \
        hoolint/app/tests/test_githist.py
git commit -m "feat(hoolint): commit_meta strategy for commit subject conventions"
```

---

### Task 7: Document the rules as opt-in config

**Files:**
- Modify: `hoolint/README.md`

**Interfaces:**
- Consumes: the four registered strategy names and their stage config keys from Tasks 3 to 6,
  and the `modes` key from Task 2.
- Produces: user-facing documentation. Nothing depends on this task.

- [ ] **Step 1: Confirm defaults.toml was never touched**

Run: `git diff 8bb526c -- hoolint/app/src/hoolint/defaults.toml`
Expected: no output. If anything appears, revert it. No rule in this plan ships enabled.

- [ ] **Step 2: Add the documentation section**

In `hoolint/README.md`, insert this section immediately before the `## Custom rules` heading:

````markdown
## Metadata rules

These check the change set and repository history rather than the contents of one file. None is
enabled by default, because CHANGELOG paths and test layouts differ per project. Copy what you
need into `hoolint.toml`.

`modes` restricts a rule to `session` (the model's edits since the last check) or `git` (the
diff against a ref). Omit it and the rule runs in both. Note that "changed" differs between
them: in git mode a CHANGELOG entry added earlier on the branch satisfies a companion rule,
while in session mode only files touched since the last check count.

```toml
# Public API changed without a CHANGELOG entry.
[[rule]]
id = "api-changelog"
globs = ["src/api/**/*.py"]
severity = "warn"
modes = ["git"]
[[rule.stage]]
strategy = "companion"
requires = "CHANGELOG.md"
message = "public API changed without a CHANGELOG entry"

# Source changed without its test. `requires_to` is an re2 substitution.
[[rule]]
id = "source-needs-test"
globs = ["src/**/*.py"]
severity = "warn"
[[rule.stage]]
strategy = "companion"
requires_from = "src/(.*)\\.py"
requires_to = "tests/test_\\1.py"

# Too much at once.
[[rule]]
id = "blast-radius"
globs = ["**/*"]
severity = "warn"
[[rule.stage]]
strategy = "change_size"
max_files = 20

# A file being revised over and over.
[[rule]]
id = "churning-file"
globs = ["src/**/*.py"]
severity = "warn"
[[rule.stage]]
strategy = "churn"
max_commits = 5
window = "30.days"

# Commit subject convention. Git mode only: at Stop time there is usually no new commit.
[[rule]]
id = "commit-subject"
globs = ["**/*"]
severity = "warn"
modes = ["git"]
[[rule.stage]]
strategy = "commit_meta"
subject_pattern = "(feat|fix|docs|test|chore)(\\(.+\\))?: .+"
```

Waivers on metadata findings are **durable**. A metadata finding has no code span, so it is
anchored to the file's path and its fingerprint does not change when the file's contents do.
Waiving one records a lasting decision, such as "this file is exempt from needing a CHANGELOG
entry", rather than an exception that expires on the next edit. This is deliberate, and differs
from span-anchored code rules, whose waivers stop matching once the excused span changes.
````

- [ ] **Step 3: Verify every documented name exists in the code**

Run:
```bash
cd hoolint/app && uv run python -c "
from hoolint.strategies import STRATEGIES
for name in ('companion', 'change_size', 'churn', 'commit_meta'):
    assert name in STRATEGIES, f'{name} is documented but not registered'
print('all four strategies registered')
"
```
Expected: `all four strategies registered`

- [ ] **Step 4: Verify the documented TOML actually parses and loads**

Run:
```bash
cd hoolint/app && uv run python -c "
import re, tomllib, pathlib, tempfile
from hoolint.config import load_config
md = pathlib.Path('../README.md').read_text()
block = re.search(r'## Metadata rules.*?\`\`\`toml\n(.*?)\`\`\`', md, re.S).group(1)
tomllib.loads(block)
d = pathlib.Path(tempfile.mkdtemp())
(d / 'hoolint.toml').write_text(block)
cfg = load_config(d)
ids = {r['id'] for r in cfg.rules}
assert {'api-changelog','source-needs-test','blast-radius','churning-file',
        'commit-subject'} <= ids, ids
print('documented config parses and loads')
"
```
Expected: `documented config parses and loads`

- [ ] **Step 5: Run the full suite**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 128 passed, 1 deselected

- [ ] **Step 6: Commit**

```bash
git add hoolint/README.md
git commit -m "docs(hoolint): metadata rules as opt-in config, and durable waiver semantics"
```

---

## Final verification

- [ ] **Full suite green**

Run: `cd hoolint/app && uv run pytest -q`
Expected: 128 passed, 1 deselected

- [ ] **defaults.toml untouched**

Run: `git diff 8bb526c -- hoolint/app/src/hoolint/defaults.toml`
Expected: no output

- [ ] **Nothing under docs/ was committed**

Run: `git diff --stat 8bb526c..HEAD -- docs/`
Expected: no output

- [ ] **The anti-silent-pass guarantee holds**

Run: `cd hoolint/app && uv run pytest tests/test_githist.py::test_git_failure_is_visible_never_a_silent_clean -v`
Expected: PASS. This test fails against any implementation that swallows a git error and returns
an empty list.
