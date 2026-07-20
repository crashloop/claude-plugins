from hoolint.findings import Finding


def make(span="# a\n# b\n# c\n"):
    return Finding(rule_id="verbose-comments", file="src/x.py", start_line=3,
                   end_line=5, span_text=span, message="verbose comment")


def test_fingerprint_stable_and_prefixed():
    a, b = make(), make()
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint.startswith("verbose-comments:src/x.py:")


def test_fingerprint_changes_with_span():
    assert make().fingerprint != make("# other\n").fingerprint
