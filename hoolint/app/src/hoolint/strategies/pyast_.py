"""Python AST generators for defects whose candidate set regex cannot express.

Both strategies here answer a question about a statement's *position* inside a
function, which is exactly what a pattern match over text cannot see:
`mock_echo_assert` connects an assert to an assignment made earlier in the same
function, and `permissive_recovery` reads an except handler together with the
name of the function enclosing it.

Neither decides anything on its own. Each produces candidates at roughly coin-flip
precision, measured on the repos they were derived from, and is meant to be
followed by a `local_llm` or `escalate` stage that judges them.
"""
import ast

from hoolint.findings import Finding
from hoolint.strategies.base import Context, rel_to_root

# `return None` is included deliberately: in a cascade of permission checks None
# usually means "no opinion, ask the next tier", which is correct, and in a lone
# check it means "allowed by default", which is not. Only a judge can tell them
# apart, so the generator offers both and lets the next stage decide.
_PERMISSIVE_RETURNS = (True, None)

# Values too common to carry identity. Matching an assert to a mock through one of
# these is coincidence: on the repos this was derived from, every such match paired
# an unrelated `return_value = []` with an assert about a call argument.
_VALUELESS = frozenset({"None", "True", "False", "[]", "{}", "()", "set()",
                        "0", "0.0", '""', "''", 'b""', "b''"})


def _parse(ctx: Context, strategy: str) -> ast.Module | None:
    """Parse the file, or note why it could not be read and yield nothing.

    A syntax error here is input, not a programmer error: the model is edited
    mid-file and the Stop hook fires on whatever is on disk. Raising would turn
    every half-written file into a "rule failed" finding.

    Args:
        ctx: Per-file execution context.
        strategy: Strategy name, for the note.

    Returns:
        The parsed module, or None if the file does not parse.
    """
    try:
        return ast.parse(ctx.content())
    except (SyntaxError, ValueError):
        ctx.warn(f"{strategy} skipped {rel_to_root(ctx.path, ctx.root)}: does not parse")
        return None


def _functions(tree: ast.Module):
    """Yield every function definition in the module, nested ones included."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _finding(ctx: Context, node: ast.stmt | ast.ExceptHandler, message: str) -> Finding:
    """Anchor a finding to a node's own source lines.

    The span is the offending source text rather than the whole function, so the
    fingerprint survives edits elsewhere in the file and a waiver stays pinned to
    the statement it excused.
    """
    lines = ctx.content().splitlines()
    start, end = node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno
    return Finding(rule_id=ctx.rule_id, file=rel_to_root(ctx.path, ctx.root),
                   start_line=start, end_line=end,
                   span_text="\n".join(lines[start - 1:end]),
                   message=message, severity=ctx.severity)


def _reject_chaining(candidates: list[Finding] | None, name: str) -> None:
    """Refuse to run in second position, where a generator would erase the prior set."""
    if candidates is not None:
        raise ValueError(
            f"{name} is a generator; it cannot follow another stage. "
            "Put it first, or chain it with op = \"or\".")


class MockEchoAssertStrategy:
    """Flags `assert x == v` where a mock in the same function was told to return `v`.

    Such an assertion cannot fail unless the code under test stops returning at
    all, because the value it checks is the value the test itself installed. The
    surrounding test may still be sound (a pass-through is worth pinning, and a
    sibling `assert_called_once_with` does real work), so this only shortlists.
    """

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Shortlist assertions that restate a mock's configured return value.

        Mock setups are collected per enclosing function, never module-wide: a
        module-wide map blames an assert in one test on a setup in another, which
        is how the first scan of the benchmark repos reported an assertion on
        line 81 against a setup on line 522.

        Args:
            candidates: Must be None; this strategy generates.
            stage: Stage config (unused).
            ctx: Per-file execution context.

        Returns:
            One finding per echoing assertion.

        Raises:
            ValueError: If the stage was chained after another.
        """
        _reject_chaining(candidates, "mock_echo_assert")
        tree = _parse(ctx, "mock_echo_assert")
        if tree is None:
            return []
        out = []
        for fn in _functions(tree):
            installed = {}
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(t := node.targets[0], ast.Attribute)
                        and t.attr in ("return_value", "side_effect")):
                    installed.setdefault(ast.unparse(node.value), node.lineno)
            for node in ast.walk(fn):
                if not isinstance(node, ast.Assert):
                    continue
                test = node.test
                if not (isinstance(test, ast.Compare) and len(test.comparators) == 1
                        and isinstance(test.ops[0], (ast.Eq, ast.Is))):
                    continue
                # Only a bare name holds the call's own return. A subscript,
                # attribute or call on the left means the value travelled through
                # real code first, and the assert pins where it landed.
                # ponytail: this also skips `assert f(x) == mocked`, where the call
                # under test is inline. Bind it to a name if that shape matters.
                if not isinstance(test.left, ast.Name):
                    continue
                expected = ast.unparse(test.comparators[0])
                if expected in _VALUELESS:
                    continue
                if (line := installed.get(expected)) is not None:
                    out.append(_finding(
                        ctx, node,
                        f"assertion echoes the mock configured on line {line}"))
        return out


class PermissiveRecoveryStrategy:
    """Flags except handlers that recover permissively inside authorization code.

    Fail-open and fail-closed recovery are the same three tokens of Python; only
    the function's role separates them. `name_contains` carries that role, and is
    required rather than defaulted because the vocabulary is per project.
    """

    def run(self, candidates: list[Finding] | None, stage: dict,
            ctx: Context) -> list[Finding]:
        """Shortlist permissive except handlers in functions named like auth checks.

        Args:
            candidates: Must be None; this strategy generates.
            stage: Stage config; `name_contains` is a required list of substrings
                matched case-insensitively against function names.
            ctx: Per-file execution context.

        Returns:
            One finding per permissive handler.

        Raises:
            ValueError: If the stage was chained, or `name_contains` is missing.
        """
        _reject_chaining(candidates, "permissive_recovery")
        if not (keywords := stage.get("name_contains")):
            raise ValueError(
                "permissive_recovery: name_contains is required; it names the "
                "functions whose recovery must fail closed.")
        keywords = [k.lower() for k in keywords]
        tree = _parse(ctx, "permissive_recovery")
        if tree is None:
            return []
        out = []
        for fn in _functions(tree):
            if not any(k in fn.name.lower() for k in keywords):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if (how := self._recovery(node)) is not None:
                    out.append(_finding(
                        ctx, node, f"{fn.name}() recovers with {how}; "
                                   "an authorization check should fail closed"))
        return out

    @staticmethod
    def _recovery(handler: ast.ExceptHandler) -> str | None:
        """Describe a handler's recovery if it is permissive, else None.

        Only the handler's own top-level statements are read. A `return True`
        nested inside a further `if` is a decision the handler made on evidence,
        not a blanket recovery, and belongs to whatever condition guards it.
        """
        for node in handler.body:
            if isinstance(node, ast.Return):
                value = node.value
                if value is None:
                    return "return None"
                if isinstance(value, ast.Constant) and value.value in _PERMISSIVE_RETURNS:
                    return f"return {value.value}"
                return None
            if isinstance(node, ast.Pass):
                return "pass, falling through"
            if isinstance(node, ast.Raise):
                return None
        return None
