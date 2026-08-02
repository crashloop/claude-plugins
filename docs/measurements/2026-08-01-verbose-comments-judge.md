# verbose-comments: what the judge stage actually removes

Measured 2026-08-01 with `tools/judge-proxy` on port 11435, `haiku` with
`reasoning_effort = "none"`, against the shipped `verbose-comments` rule in
`defaults.toml`. The endpoint was pointed at the proxy with
`HOOLINT_LLM_BASE_URL`, so the rule config itself was not modified.

```bash
cd tools/judge-proxy && uv run uvicorn app:app --port 11435   # in another shell
cd hoolint/app
HOOLINT_LLM_BASE_URL=http://localhost:11435/v1 \
  uv run hoolint check --mode git --ref <root-commit> --root <repo>
```

## Two corpora, opposite results

**This repository.** Ten candidates across five files cleared regex and
semantic. Three judge runs confirmed 0, 0 and 1. Reading all ten
spans, every one carries a measurement, a trade-off, or a reason for a
non-obvious choice, so the correct answer is 0 and the single hit was noise.
The generator's precision here is 0.00 and the judge recovers it entirely.
That is expected: this repo's own standard forbids the comments the rule hunts,
so the corpus has no positives and this measures specificity, not precision.

**structurella (914 tracked Python files, comments written to no such standard).**

| stage | before the cap fix | after |
| --- | --- | --- |
| after regex and semantic | 170 | 170 |
| unjudged, over `max_candidates` | 58 (4 whole files) | 18 (the overflow only) |
| actually judged | 112 | 152 |
| confirmed VIOLATION | 59 | 70 |
| cleared OK | 53 | 82 |
| reported to the user | 117 | 88 |

The judged run cost 3m18s for 67 files before the fix and 3m38s after, every
request served from a warm spare. The "before" column is what prompted the fix
described below; the sampling that follows was done against it.

## Ground truth on a sample

Twelve confirmed and twelve cleared spans were read and labelled by hand
against the rule's own criterion: violation if the comment merely restates the
adjacent code or pads with filler, OK if it carries intent, a constraint, a
reference, a warning, or a reason.

- **Confirmed: 10 of 12 agreed.** Seven were section banners
  (`# =====` around a title). One was a commented-out class. The two
  disagreements both mixed filler with real content: a `SECURITY:` note
  explaining why `split_part` replaces `LIKE`, and an arithmetic derivation of
  an expected test constant.
- **Cleared: 10 of 12 agreed.** The two disagreements were an English gloss of
  a regex and an authorization rule restated line by line above the code that
  implements it. The judge correctly cleared PEP 723 inline script metadata
  (`# /// script`), which is machine-read, not prose.

So roughly 0.83 either way on a sample of 12. The interval is wide and the
labels are one person's, so treat the figure as "most of what it removes should
go" rather than as a calibrated rate.

## Two findings worth acting on

**The budget cap inverted on the files that needed it most (fixed).**
`max_candidates = 10` is per file, and a file over the cap used to skip the
judge entirely rather than judging the first ten. On structurella that sent 58
of 170 candidates (34%) to the user unjudged, and they came from the four
noisiest files in the repository. The cap is meant to bound wall time, but its
effect was that the worst files got the least scrutiny.

`local_llm` now judges the first N and passes the overflow through, still
disarming blocking for that file because the overflow was never vetted.
Re-measured: unjudged candidates fell from 58 to 18 (34% to 11%), judged rose
from 112 to 152, and reported findings fell from 117 to 88 for 20s more wall
time.

**A regex caught most of the true positives for free (shipped).** Section
banners are the dominant true positive, measured over the whole population
rather than the sample. A loose `^[ \t]*#[ =-]{10,}$` matches a line in 40 of
the 59 confirmed spans and 5 of the 53 cleared. Tightening it to the whole
block, a rule line then exactly one title line then another rule line, splits
the two classes almost perfectly: 39 of 59 confirmed, 1 of 53 cleared.

That pattern shipped as the `comment-banners` rule, and `verbose-comments` now
excludes any span fenced by a banner rule. Re-measured on structurella:

| | before | after |
| --- | --- | --- |
| verbose-comments candidates | 170 | 106 |
| judged | 152 | 97 |
| unjudged overflow | 18 | 9 |
| confirmed | 70 | 26 |
| wall time | 3m38s | 2m41s |

The cost side went as predicted. The volume side did not: `comment-banners`
reports 205 findings across 45 files, five times what the judge ever saw,
because the semantic stage had been gating most banners out before they reached
it. Fourteen sampled were all genuine. They are warn, never blocking, and
`modes = ["git"]` keeps them out of the session hook.

## Scope

One model, one prompt, two repositories, samples of 12. The structurella
numbers are the interesting ones; this repository's corpus contains no
positives by construction.
