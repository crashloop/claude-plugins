# Hoolint

Checks code and documentation whenever the model signals it finished working,
using stackable analysis strategies of increasing cost.

## Language

**Rule**:
A named check with a file scope, a severity, and a pipeline of stages.
_Avoid_: check, lint, policy

**Stage**:
One step in a rule's pipeline; applies a strategy to the candidate set
produced by the previous stage.
_Avoid_: step, phase

**Strategy**:
A reusable analysis technique a stage applies (regex, semantic, escalate).
_Avoid_: analyzer, engine

**Finding**:
One violation a rule reports, anchored to a span in a file.
_Avoid_: issue, error, offense

**Fingerprint**:
Stable identity of a finding: rule id + file path + hash of the offending
span. Changing the span changes the fingerprint.

**Escalation**:
Handing a shortlist of findings to the session model for judgment instead of
deciding in Python. Distinct from local judgment.
_Avoid_: LLM check, AI review

**Local judgment**:
A `local_llm` stage judging candidates via a local OpenAI-compatible
endpoint (Ollama, vLLM, LM Studio). Runs anywhere, including CI; never a
cloud provider.

**Waiver**:
A team-visible, committed dismissal of a finding, keyed by fingerprint and
carrying a mandatory reason. Expires automatically when the excused span
changes. Git review is the approval gate.
_Avoid_: suppression, ignore, baseline

**Stand-down**:
Hoolint releasing a blocked stop after N consecutive stops with an unchanged
finding-set, so the human arbitrates instead of two machines fighting.
_Avoid_: give-up, bail

**Trusted project**:
A project the user has explicitly allowed to load custom Python rules.
Custom rules never run in untrusted projects.

**Journal**:
The per-session record of files the model touched since the last check.
_Avoid_: log, history

**Session mode**:
Change detection from the journal — only files the model touched.

**Git mode**:
Change detection from `git diff` against a ref — for verification pipelines.
