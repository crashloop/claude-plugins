import subprocess

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
