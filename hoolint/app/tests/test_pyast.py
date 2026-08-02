"""The two Python AST generators: mock-echo assertions and permissive recovery.

Both exist because regex cannot produce the candidate set. `mock_echo_assert`
needs to connect an assert to an assignment made earlier in the same function,
and `permissive_recovery` needs to know an except handler's position inside a
function whose name it also has to read.
"""
import pytest
from hoolint.config import Config
from hoolint.engine import run

ECHO = {"id": "mock-echo", "globs": ["**/*.py"], "severity": "warn",
        "stage": [{"strategy": "mock_echo_assert"}]}

RECOVERY = {"id": "fail-open", "globs": ["**/*.py"], "severity": "warn",
            "stage": [{"strategy": "permissive_recovery",
                       "name_contains": ["permission", "authorize"]}]}


def _run(rule, tmp_path, src, name="m.py"):
    f = tmp_path / name
    f.write_text(src)
    return run(Config(rules=[rule], settings={}), [f], tmp_path, "git")


def test_assert_echoing_a_return_value_is_flagged(tmp_path):
    """The shape from structurella's test_import_csv.py:100."""
    found = _run(ECHO, tmp_path, "def test_x():\n"
                                 "    mock_get.return_value = trustee\n"
                                 "    result = resolve('a')\n"
                                 "    assert result == trustee\n")
    assert len(found) == 1
    assert found[0].start_line == 4
    assert "line 2" in found[0].message
    assert found[0].span_text.strip() == "assert result == trustee"


def test_assert_echoing_a_side_effect_literal_is_flagged(tmp_path):
    found = _run(ECHO, tmp_path, "def test_x():\n"
                                 "    m.predict.return_value = ['fake']\n"
                                 "    out = backend.predict([1])\n"
                                 "    assert out == ['fake']\n")
    assert [f.start_line for f in found] == [4]


def test_assert_against_a_value_no_mock_returned_is_ignored(tmp_path):
    """A real expectation the test author wrote down is not an echo."""
    assert _run(ECHO, tmp_path, "def test_x():\n"
                                "    m.get.return_value = trustee\n"
                                "    assert compute() == 42\n") == []


@pytest.mark.parametrize("expected", ["None", "True", "False", "[]", "{}", "()", "0", '""'])
def test_valueless_literals_never_match(tmp_path, expected):
    """Empties and singletons collide by coincidence, not by dataflow.

    Measured on the benchmark repos these were 8 of 44 findings and every one was
    unrelated: `check.return_value = []` on one line and, on another, an assert
    about a *call argument* that also happened to be `[]`.
    """
    assert _run(ECHO, tmp_path, "def test_x():\n"
                                f"    m.f.return_value = {expected}\n"
                                f"    result = compute()\n"
                                f"    assert result == {expected}\n") == []


def test_a_distinctive_literal_still_matches(tmp_path):
    """The exclusion is for valueless literals only, not for literals."""
    found = _run(ECHO, tmp_path, "def test_x():\n"
                                 "    m.f.return_value = {'baz': 'qux'}\n"
                                 "    result = compute()\n"
                                 "    assert result == {'baz': 'qux'}\n")
    assert [f.start_line for f in found] == [4]


@pytest.mark.parametrize("lhs", [
    'response.json()',                 # through a view, a serializer and JSON
    'backup_log.database_size_bytes',  # into a specific database column
    'kwargs["bedrock_creds"]',         # propagated to a collaborator's call
    'result["url"]',
])
def test_value_that_crossed_a_boundary_is_not_an_echo(tmp_path, lhs):
    """Only a bare name is the call's own return; anything else verifies wiring.

    Hand-classifying all 36 findings on the benchmark repos put 22 in this class:
    the mocked value travels through real code and the assert pins where it
    landed, which is the whole point of those tests.
    """
    assert _run(ECHO, tmp_path, "def test_x():\n"
                                "    m.f.return_value = payload\n"
                                "    thing = call_it()\n"
                                f"    assert {lhs} == payload\n") == []


def test_mock_setup_does_not_leak_between_functions(tmp_path):
    """Scoped to the enclosing function.

    A module-wide map matches an assert in one test against a mock configured in
    a different one, which is how the first scan of these repos produced an
    assert on line 81 blamed on a setup at line 522.
    """
    assert _run(ECHO, tmp_path, "def test_a():\n"
                                "    m.f.return_value = payload\n"
                                "\n"
                                "def test_b():\n"
                                "    assert result == payload\n") == []


def test_syntactically_invalid_file_is_noted_not_fatal(tmp_path):
    """A file caught mid-edit must not surface as a crashed rule."""
    found = _run(ECHO, tmp_path, "def test_x(:\n")
    assert found == []


def test_mock_echo_chained_after_a_stage_is_a_visible_error(tmp_path):
    """A generator in second position must not silently discard the prior set."""
    rule = {"id": "chained", "globs": ["**/*.py"], "severity": "warn",
            "stage": [{"strategy": "regex", "pattern": "(?m)^.*FIXME.*$",
                       "message": "fixme"},
                      {"strategy": "mock_echo_assert"}]}
    out = _run(rule, tmp_path, "# FIXME: later\n")
    assert out and "cannot follow another stage" in out[0].message


def test_permissive_return_in_named_function_is_flagged(tmp_path):
    found = _run(RECOVERY, tmp_path, "def has_permission(u):\n"
                                     "    try:\n"
                                     "        return check(u)\n"
                                     "    except AttributeError:\n"
                                     "        return True\n")
    assert len(found) == 1
    assert "has_permission" in found[0].message
    assert "return True" in found[0].message


def test_permissive_pass_is_flagged(tmp_path):
    found = _run(RECOVERY, tmp_path, "def authorize(u):\n"
                                     "    try:\n"
                                     "        check(u)\n"
                                     "    except KeyError:\n"
                                     "        pass\n"
                                     "    return False\n")
    assert len(found) == 1
    assert "pass" in found[0].message


def test_same_shape_outside_a_named_function_is_ignored(tmp_path):
    """The rule is about authorization vocabulary, not about try/except."""
    assert _run(RECOVERY, tmp_path, "def render_widget(u):\n"
                                    "    try:\n"
                                    "        return draw(u)\n"
                                    "    except AttributeError:\n"
                                    "        return True\n") == []


def test_handler_that_reraises_or_denies_is_ignored(tmp_path):
    """Fail-closed recovery is the correct shape and must stay silent."""
    assert _run(RECOVERY, tmp_path, "def has_permission(u):\n"
                                    "    try:\n"
                                    "        return check(u)\n"
                                    "    except AttributeError:\n"
                                    "        return False\n"
                                    "    except KeyError:\n"
                                    "        raise\n") == []


def test_name_contains_is_required(tmp_path):
    """Auth vocabulary is per-project; guessing it silently would be worse."""
    rule = {**RECOVERY, "stage": [{"strategy": "permissive_recovery"}]}
    out = _run(rule, tmp_path, "def has_permission(u):\n"
                               "    try:\n"
                               "        return check(u)\n"
                               "    except KeyError:\n"
                               "        return True\n")
    assert out and "name_contains" in out[0].message


@pytest.mark.parametrize("strategy", ["mock_echo_assert", "permissive_recovery"])
def test_non_python_file_never_reaches_the_parser(tmp_path, strategy):
    """Globs are the guard, but a misconfigured rule must degrade quietly."""
    rule = {"id": "r", "globs": ["**/*.md"], "severity": "warn",
            "stage": [{"strategy": strategy, "name_contains": ["x"]}]}
    assert _run(rule, tmp_path, "# just prose\n", name="doc.md") == []
