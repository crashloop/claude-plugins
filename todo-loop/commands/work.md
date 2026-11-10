---
description: Goal-driven loop that plans, implements, reviews, and tests every open TODO.md item until done, in parallel worktrees by default.
argument-hint: "[path/to/TODO.md] [item-id] [--light|--full] [--sequential|--parallel=N]   # defaults: ./TODO.md, all open items, parallel"
disable-model-invocation: true
---

# TODO Loop — goal-driven, self-verifying delivery of the backlog

Work the remaining items in `TODO.md` to completion, **one item at a time**, each
through a full **plan → spec-critique → implement → code-review → test → record**
cycle. Make sensible decisions in agreement with this project's principles and
objectives, and **log every decision** in the item's report. Resume cleanly after
any interruption.

This command pairs two Claude Code primitives with the per-item cycle:

- **`/goal`** drives the loop across turns and *independently verifies* completion
  with a fresh model — replacing self-reported done-ness.
- **Dynamic workflows** (`todo-spec-critique`, `todo-code-review`) run the two
  review-heavy steps in the background, so dozens of reviewer outputs stay out of
  the main context window and each finding is adversarially verified before it
  reaches you.

**Plugin paths.** Both workflows ship with this plugin in `${CLAUDE_PLUGIN_ROOT}/workflows/`
and are not registered by name. Wherever this command says "launch `todo-spec-critique`" or
"launch `todo-code-review`", call the Workflow tool with
`scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/<name>.js"` plus `args`. Never use `name:`.

**Skill dependencies.** Steps 1, 3, 4 and 8 use **superpowers** skills
(`brainstorming`, `writing-plans`, `test-driven-development`, `receiving-code-review`,
`systematic-debugging`, `verification-before-completion`). If one is not installed, apply
its discipline inline and log that in the item's report. **compound-engineering** skills
are optional fallbacks.

`$ARGUMENTS` (all optional):
- **arg 1** — path to the backlog file (default `./TODO.md`).
- **arg 2** — a single item id to run (default: every non-done item, in order).
- **`--parallel[=N]`** — run independent items concurrently with a rolling,
  dependency-aware scheduler instead of strictly one at a time (**default ON**;
  pass `--sequential` to opt out; `N` = max items in flight, default
  `max(1, min(8, cores−2))`). Concurrency is further bounded by how many items are
  ready (deps merged). See **Parallel mode** below. Ignored (runs sequentially)
  when arg 2 targets a single item or only one item is not done.
- **`--light`** — quick reviews: every item takes the small-change path in steps 2
  and 4 regardless of size (see **Light mode**). Tests, type-checks and step 8 are
  unchanged: light cheapens review, never the done-gate.
- **`--full`** — turn light mode off for a resumed run (removes `Mode: light`).

## Precedence

User intent → correctness → simplicity → cohesion → style. When principles
conflict, surface the tension explicitly; never resolve it silently. **Project
rules in `CLAUDE.md` / `AGENTS.md` / `agent-os/standards/` always win over this
command.**

## Setup (once per run)

1. Read the backlog and `${CLAUDE_PLUGIN_ROOT}/references/item-contract.md`. Find the
   items, their status and their dependencies exactly as the contract's § Finding items
   defines. Target the open items in order; skip done, deferred and BLOCKED ones and list
   them. Give agents the item text plus any `Context:` section it links. With arg 2, an
   open dependency of that item is a Blocked halt (`#7 needs #3`), never a silent skip.
   **Require a clean tree:** if `git status --porcelain` is non-empty, stop and ask the
   user to commit or stash first. Every item baselines on `HEAD` and commits with
   `git add -A`, which is only safe when the tree holds nothing but loop work.
2. Read `CLAUDE.md` (or `AGENTS.md` when there is no `CLAUDE.md`) and any
   `agent-os/standards/`; read `docs/conventions.md` only for the rules that
   touch the item's packages (grep `rule #N` mentions, don't read it whole). Background
   item agents get `CLAUDE.md` injected automatically — do not tell them to re-read
   it; name the specific conventions they need. Every decision matches the project's
   principles (KISS, DRY, SSOT, YAGNI, fail-fast, library-
   first, structured errors, composition over inheritance, test behaviour not
   implementation, size smells).
3. Create or locate the loop workspace:
   `docs/plans/<YYYY-MM-DD>-todo-loop/` containing **`LOOP_STATE.md`** — the master
   driver. Seed it with one table row per item:

   | #   | Item | Status | Report                   |
   | --- | ---- | ------ | ------------------------ |
   | …   | …    | ⬜      | [NN-slug.md](NN-slug.md) |

   Legend: ⬜ pending · 🔜 in progress · 🔬 in review · ✅ done · 🚧 blocked.
   Above the table write `Scheduling: sequential` or `Scheduling: parallel <N>`, and under
   `--light` also `Mode: light`. On resume, that line keeps light mode on even if the
   flag was not re-passed; `--full` deletes the line. **Resume first:** if any
   `docs/plans/*-todo-loop/LOOP_STATE.md` has non-✅ rows, resume the newest such workspace
   (whatever its date) at its first non-✅ row's first unchecked checklist box (see
   Resume protocol) instead of seeding a new one. A second run on one day gets a
   `-b`, `-c` suffix.
4. **Set the goal** that drives the loop. The evaluator cannot read files or run
   commands — it only judges what you surface in the transcript — so the condition
   requires you to *echo fresh proof in the current turn*. Substitute the real
   workspace path and the set of targeted rows (all non-done rows, or the single
   arg-2 row):

   ```
   /goal DONE when every TARGETED row in <workspace>/LOOP_STATE.md is ✅ and <backlog>
   marks those items done, with each item's scoped tests + type-checks shown green
   in THIS turn's output, the full suite shown green once at the end of the loop, and
   its acceptance criteria demonstrated; OR HALT when a targeted
   row is 🚧 blocked on a human decision that this turn states explicitly. Reprint
   the LOOP_STATE.md table at the end of every turn. Stop after <N> turns.
   ```

   Set `<N>` to roughly `targeted items × 6` (each item spends several turns across
   plan, the two review workflows, TDD, and the full suite). Scope to "targeted
   rows," not "every row," so a single-item run (arg 2) can complete while other
   rows stay ⬜. The **OR HALT** clause lets the evaluator end the loop the moment
   you surface a real blocker instead of re-firing turns at an item it cannot finish
   unattended (see the Blocked protocol in Guardrails). After each turn the
   evaluator returns yes/no with a reason; a "no" carries that reason forward.

   *Requirements:* `/goal` needs an accepted-trust workspace and is unavailable
   under `disableAllHooks` / `allowManagedHooksOnly`. **`/goal` cannot be invoked as
   a tool — only the user types it.** If no `/goal` is already active when the loop
   starts, do NOT wait for one and do NOT ask the user to drive it: self-pace
   instead. Whenever a turn would otherwise end with targeted rows still unfinished
   — an item boundary, a background-workflow wait, or a context checkpoint — call
   **`ScheduleWakeup`** with this same `/todo-loop:work` invocation as the `prompt` (the
   `/loop` dynamic-mode mechanism), so the next firing resumes via the Resume
   protocol. **Use `delaySeconds: 60`** (the runtime floor; overridable by the user). The next item is
   always local work with no external dependency to poll, so resume promptly: queued
   work gains nothing from waiting. Do NOT apply ScheduleWakeup's idle-tick guidance
   (1200–1800s) here: this loop is never idle, it has queued work. Only lengthen the
   delay if a turn is genuinely waiting on tracked external state (e.g. a long CI run).
   Keep scheduling wake-ups until every targeted row is ✅ or one is 🚧 (Blocked).
   Verify completion yourself at step 8.

   *Unattended runs:* approve each review workflow's launch once with "Yes, and
   don't ask again for this workflow in this project" (or run in auto mode) so the
   per-run approval prompt does not stall the loop.

## Context isolation — delegate the two context sinks

The loop **cannot clear its own context**: `/clear` is a user-typed CLI command, not a
tool, and `ScheduleWakeup` re-fires a turn in the *same* session. The orchestrator's
window therefore grows monotonically across items until autocompact fires mid-item.

Fix: run the two heaviest steps as **background `Agent`s** (default agent type — they must
Edit/Write) whose context dies with them. In sequential mode pass **no `isolation`**: only
one item is ever in flight, so there is nothing to isolate from, and `'worktree'` costs
disk and fails outright in a repo with no `HEAD`. Parallel mode keeps its worktrees.

| step | who runs it | why |
| --- | --- | --- |
| 1 plan + codebase grounding | **item agent** | grounding reads far more code than the plan ends up citing |
| 2 spec critique | orchestrator | it *is* a workflow; workflows do not nest, and it is already context-cheap |
| 3 TDD implement | **item agent** | test iteration and debugging are the largest single sink |
| 4–8 review, suite, record, verify | orchestrator | step 4 is a workflow; 5–8 must be visible in the transcript for the goal evaluator |

Both agents hand off through the item's **report file** — durable, and already the loop's
resume unit. Give each: the item text, the principle files, the report path, the repo it
owns, and an instruction to work **autonomously** (no mid-run questions). Each returns a
**terse struct**, never a narrative:
`{ status: done|blocked, summary, filesChanged, blocker?, scopedTestsOutput }`.
Read the report file for detail; never ask an agent to replay its working context.
`status: blocked` → invoke the Blocked protocol, do not re-derive the work inline.

If the orchestrator's own window still fills (long review payloads, a failing suite), the
escape hatch is one `claude -p "/todo-loop:work <backlog> <item-id> --sequential"` process **per item**
driven from a shell loop — a fresh process is the only true reset. That run is fully
unattended, so resolve every open decision first: a Blocked halt has no one to answer it.

## Per-item cycle (repeat until every row is ✅)

Do **one** item start-to-finish before touching the next. When you start: mark the
row 🔜 in `LOOP_STATE.md`, and **capture the item's review baseline** — run
`git rev-parse HEAD` and record the sha (the tree was clean at Setup and each finished
item is committed, so HEAD is the previous item's end state). This baseline isolates
*this* item's diff in step 4.

1. **Plan the spec.** Run this step in a **per-item background agent** (see Context
   isolation) so the grounding reads never enter your window; it writes the report file
   and returns the struct. When scope or approach is open, use the **superpowers
   `brainstorming`** skill to turn the item into a design — but run it
   *non-interactively*: enumerate the options and choose per project principles,
   logging the rationale, rather than pausing for user answers (the loop is
   unattended; a genuine fork that needs a human goes through the Blocked protocol).
   Then use **superpowers `writing-plans`** to write the plan. Save it as the item's
   report
   `docs/plans/<date>-todo-loop/NN-slug.md`, with **decisions, rationale, and
   explicit deferrals logged**. Check shared libs before writing custom logic
   (library-first). **Ground the plan in the real codebase before critiquing it:**
   validate every assumption the plan makes — file paths, existing patterns, API
   contracts, serializer/endpoint shapes — against the actual code (a code-graph or
   symbol-search tool if one is available, otherwise grep/read), and correct any the
   codebase contradicts. A
   plan that cites a path, symbol, or contract that does not exist is a defect to
   fix now, not a finding to discover in review.
2. **Critique the spec (workflow).** **Light mode:** always the in-context
   self-critique below; never launch the workflow. **Threshold:** if the plan touches ≤ 2 files or
   one package and has no open design question, skip the workflow and do a single
   in-context self-critique against the principle files — do not fan seven lenses at
   a one-file plan. The self-critique always covers **grounding**: every path, symbol
   and contract the plan cites resolves in the real code.
   Otherwise launch the **`todo-spec-critique`** dynamic
   workflow on the report with **absolute paths** (`planPath`, `item`, `principleFiles`).
   Pass `lenses` scoped to the item (e.g. add the opt-in `frontend-ssot` for frontend
   items in a monorepo, drop `domain` for items touching no domain non-negotiable;
   omit for the default set). **While the workflow runs, do read-only prep** — read the
   code paths the plan touches and identify step 3's scoped tests; write no code
   yet. Then **wait for its completion notification and read the returned
   result** — the workflow runs in the background and does not block your turn on
   its own. It critiques the plan from independent lenses (principles, simplicity,
   testability, domain non-negotiables, gaps) and returns a synthesized `mustFix` /
   `optional` / `openQuestions` list. Fold every `mustFix` into the plan before any
   code and re-record changed decisions. A **DRY/SSOT `mustFix` is not deferrable** —
   resolve it now (in the plan *and* the consolidation), never "later for scope": a
   deferred SSOT fix reliably resurfaces as a code-review finding in step 4 and costs
   more to land then. If `openQuestions` contains a genuine human-decision ambiguity,
   **invoke the Blocked protocol** (Guardrails) — do not guess.
3. **Implement (TDD).** Run this step in a **second per-item background agent** (see
   Context isolation), fed the critiqued report file. Use the **superpowers
   `test-driven-development`** skill:
   write a failing test, watch it fail for the right reason, implement. **Run only
   the minimum set of tests** for the unit you are changing while iterating — never
   the whole suite in the inner loop. Keep IDs stable (`testID`/`data-testid`);
   never remove them citing YAGNI.
4. **Comprehensive code review (workflow).** **Light mode:** never launch the
   workflow. Start step 5's scoped tests + type-checks in the background, then review
   through the correctness lens only: in-context under 150 changed lines, otherwise in
   **one background `Explore` agent** that returns only findings (keeps the diff out of
   your window). Verify each blocker/major finding against the real code before fixing
   it; drop nits. Otherwise launch the **`todo-code-review`**
   dynamic workflow on *this item's* diff with `item`, `baseline` (the item's sha),
   `repoDir` and `principleFiles`, all **absolute**. Pass
   `personas` scoped to the
   diff (e.g. `["correctness", "simplicity", "tests"]` for a small single-package
   change; omit for all six). **The moment it is launched, run step 5's scoped tests
   + type-checks in the background** — the two are independent. Then **wait for the
   workflow's completion notification and read the result.** If the review returns
   no confirmed findings, the background result stands as step 5; if it returns
   fixes, apply them and re-run the scoped tests. Passing `baseline` scopes the review to
   `git diff <baseline>` (plus new untracked files) so prior uncommitted items are
   excluded. The workflow runs per-dimension persona reviewers (correctness,
   security, performance, simplicity, architecture, tests), verifies each finding
   against the real code with an independent skeptic, and returns only confirmed,
   prioritized fixes. For a trivial change (a few lines, one dimension), skip the
   workflow and do a single in-context review — do not fan out six personas at a
   one-line edit. **Threshold:** `git diff --stat <baseline>` (plus untracked files)
   under **150 changed lines** → in-context review; 150–400 lines → pass 3 personas
   (`correctness`, `simplicity`, `tests`); above → all six. **Apply every confirmed fix** per the project's principles; re-run
   the scoped tests after fixes. For tricky feedback, apply **superpowers
   `receiving-code-review`** (verify, don't perform agreement).
5. **Scoped tests + type-check per item; the full suite per batch.** Per item, what
   must be green before ✅ is: the **scoped tests** of every package the change touched
   (including sibling packages you refactored), their **type-checks**, and any
   dependency or CI validators the project defines. Print the output in the
   transcript (the goal evaluator reads it there). The **complete suite** (every touched
   package's whole test run, the host suites, any build/export step) runs **once per batch**:
   after every **3 completed items** and at the end of the loop — launched in the
   background the moment the batch's last item enters step 6, so it overlaps the next
   item's plan agent. A batch-suite failure is a stop-the-line event: fix it before the
   next item's step 3 (bisect by item using the per-item commits), with **superpowers
   `systematic-debugging`**; fix root causes, not symptoms. Items in a red batch stay ✅
   only after the batch suite is green again.
6. **Record.** Update the item's report (progress log, shipped vs deferred) and the
   backlog: append exactly `✅ DONE (YYYY-MM-DD)` to the item's heading and add a short
   shipped/deferred note under it. Update the item's row in `LOOP_STATE.md`.
7. **Capture emergent rules.** If a reusable rule, convention, or process
   improvement emerged, append it as the next numbered rule in **`docs/conventions.md`**
   (concise, active voice, Strunk) — not in `CLAUDE.md`, which every agent turn pays
   for. Optionally also run the **`compound-engineering:ce-compound`**
   skill to persist a richer learning under `docs/solutions/`.
8. **Verify & close.** Apply **superpowers `verification-before-completion`**:
   confirm with **command output produced in this turn** (never a quoted earlier
   run — the goal evaluator cannot tell stale output from fresh) that tests pass and
   the work meets the item's acceptance criteria. Only then flip the row to ✅ in
   `LOOP_STATE.md`, and reprint the table so the evaluator sees current state.
   Evidence before assertions — never claim done without showing the output.
   Then **commit the item** on the current branch — `git add -A && git commit -m
   "loop: NN <slug>"` (a submodule change is committed inside the submodule first,
   then the pointer bump in the host). **Never push**: worktrees fork from the local
   merged state, so dependents already see this commit. Pushing is the user's call.

## Light mode

`--light` (or `Mode: light` in `LOOP_STATE.md`) forces steps 2 and 4 onto their
light paths: no `todo-spec-critique`, no `todo-code-review`. Step 2 self-critiques with
grounding; step 4 reviews through the correctness lens only.
It is a branch in this command, not a workflow arg, because workflow `args` can fail to
bind and a dropped flag would silently run the full review. Each item report records
`Review: light` so a reader knows the depth. Checklist boxes 2 and 4 are ticked by the
light review. In parallel mode, step 1 of the post-item review is the same light pass.

## Resume protocol

On re-entry: read `LOOP_STATE.md`, find the first non-✅ row, open its report, and
resume at the first unchecked box of the per-item checklist below. Per-item
progress detail lives in each report's "Progress log" section. A goal still active
on `--resume` / `--continue` is restored automatically (its turn/token counters
reset); if it was cleared or achieved, re-set it per Setup step 4.

### Per-item checklist (mirror this in each report)

1. [ ] Spec/plan written (decisions + rationale + deferrals logged)
2. [ ] Spec critiqued (`todo-spec-critique`, or light pass) and `mustFix` folded in
3. [ ] Implemented via TDD; minimum scoped tests green
4. [ ] Code review (`todo-code-review`, or light pass) run; confirmed fixes applied
5. [ ] Scoped tests + type-checks green (output shown); batch suite green if this item closes a batch
6. [ ] Report + `TODO.md` updated (shipped/deferred noted)
7. [ ] Emergent rules appended to `docs/conventions.md` (if any)
8. [ ] Verified (real output) and row marked ✅

## Guardrails

- **One item at a time (sequential mode).** Finish the full cycle before starting
  the next; the review workflows fan out *within* an item, not across items. In
  parallel mode this holds per agent: each worktree agent runs exactly one item.
- **Continuous — never ask permission to proceed.** The loop is unattended. Do
  **not** end a turn by asking the user whether to continue to the next item, and do
  **not** treat a turn or context boundary as a stop condition. The moment an item's
  row flips ✅, start the next targeted item in the same turn (capture its baseline,
  begin its cycle). If the turn genuinely must end first (length/context), schedule a
  self-wake per Setup step 4 instead of handing back to the user. The ONLY stop
  conditions are: every targeted row ✅, or a 🚧 Blocked halt awaiting a human
  decision. A clean checkpoint is a reason to keep going, not a reason to ask.
- **Decide, then log.** Make sensible calls per project principles; record them.
- **Blocked protocol.** If an item is genuinely ambiguous or blocked on a human
  decision (including a workflow `openQuestions` entry), do **not** guess and do
  **not** silently spin: mark its row 🚧 in `LOOP_STATE.md`, add a
  `**BLOCKED:** <decision needed>` line under the item's heading in the backlog, state
  the exact decision you need in this turn's output, and let the goal's **OR HALT** clause end
  the loop. Once the user answers, record the decision in the item, remove the BLOCKED
  line, and resume.
- **Workflows are review-only here.** `todo-spec-critique` and `todo-code-review`
  run their agents as the read-only **`Explore`** agent type (no Edit/Write — they
  critique and report; you apply fixes interactively). They inherit your tool
  allowlist; pre-allow the commands they need (e.g. `git diff`) and approve each
  workflow's launch once ("don't ask again") to keep the loop unattended. Workflows
  require Claude Code v2.1.154+ on a paid plan; if unavailable, fall back to
  **`compound-engineering:ce-doc-review`** (step 2) and
  **`compound-engineering:ce-code-review`** (step 4) as in-context skills, and if those
  are missing too, take the Light-mode path for steps 2 and 4 and log it per item.
- **Workflow mechanics.**
  - *Args.* Always launch by `scriptPath` with `args` and **absolute paths**; never
    edit the plugin's script files to hardcode an input.
  - *Submodule/monorepo diffs.* If the code lives in a git **submodule**, the baseline
    is a submodule commit — pass `repoDir` to `todo-code-review` (or hardcode it) so the
    diff runs with `git -C <submodule>`, never in the superrepo. Capture the item
    baseline in the **same repo the code lives in**.
  - *New packages are mostly untracked.* `git diff` shows nothing for a brand-new
    package — the review must also `git status --porcelain` and **read untracked files**.
  - *Check before relaunch.* Before patching-and-relaunching a workflow that looks
    failed, read its task status/output — it may have **succeeded on defaults**;
    relaunching duplicates the run (and the cost). `TaskStop` any redundant run.
  - *Reading results.* The completion notification is **truncated**; the full payload is
    the task `output-file` (JSON, nested under `result`). Always read the file, never act
    on the truncated summary alone. Spec critique: apply `result.revision.mustFix`.
    Code review: apply `result.summary.fixes` (deduplicated; `result.findings` is the raw
    set). Check `result.failedLenses` / `result.failedPersonas`: those dimensions went
    **unreviewed**, so relaunch with just them once. Verify each `result.unverified`
    finding yourself. A workflow that throws reviewed nothing: relaunch once, then Blocked.
- **Commit each finished item, never push.** Step 8 ends with one local commit
  (`loop: NN <slug>`), so the tree is clean at every item boundary and parallel mode can
  fork worktrees from it. Finish the loop with a summary of what shipped, what deferred,
  and any new `docs/conventions.md` rules.
- **No scope creep.** Build what the item asks for; defer extras with a logged note.

## Parallel mode — rolling, dependency-aware (DEFAULT; opt out via `--sequential`)

Parallel is the default: independent items run **concurrently**, in dependency
order, each in its own git worktree. `--sequential` restores the strictly serial,
shared-tree cycle. Everything above still holds *within* an item; this section only
changes how items are **scheduled** and **isolated**. Worktrees fork from HEAD, so
**uncommitted work in the main tree is invisible to item agents**. Setup requires a clean
tree and every finished item is committed, so the tree is clean at item boundaries.

**Safety model shift.** A worktree item-agent takes **no mid-run input**: "stop and
ask when blocked" becomes "return the blocker as a finding for the orchestrator."
The expensive *verified adversarial* review (`todo-code-review`) cannot run inside
an item agent (workflows do not nest), so it runs in the orchestrator's post-item
pipeline, against each item's real diff — quality is preserved, timing moves.
Within an item, the spec critique becomes a cheap in-agent self-critique instead of
the `todo-spec-critique` workflow.

**Scheduling is rolling, not wave-based:** there is no barrier where all in-flight
items must finish together. Each item completion immediately (a) enters the
post-item pipeline and (b) frees a slot for the next ready item, which forks from
the freshly merged state. The serialized review/merge/test tail therefore overlaps
with still-running implementations instead of following them.

### 1. Dependencies and readiness

After Setup, before running anything:

- **Targeted items** = the not-done rows you would otherwise run (all, or the arg-2 one).
- **Edges:** only `Depends on:` lines, per the contract. Declaration order and `#N`
  mentions in prose ("shipped with #30") are **not** dependencies. Deps already done are
  satisfied and dropped; a dep on an open item outside the targets is a blocker.
- **Ready** = a targeted ⬜ item whose declared deps are all ✅ (i.e. merged into the
  main tree — 🔜/🔬 does not satisfy a dep). No dependency declarations → every
  targeted item is ready at start.
- **Cycle check:** if items remain, none are ready, and none are in flight, the graph
  has a cycle → mark those rows 🚧, name the cycle in this turn's output, and let the
  goal's OR HALT clause end the loop. A 🚧 item's dependents stay ⬜ and are reported
  as blocked-by.

### 2. Rolling scheduler (per-item background agents)

Launch each ready item as its **own background `Agent`** — `isolation: 'worktree'`,
default agent type (it must Edit/Write, so **not** the read-only `Explore` type the
review workflows use) — keeping at most `N` in flight. Do **not** wrap items in a
per-wave Workflow: per-item agents complete independently, and each completion
notification is what drives the loop. Give each agent: the item text, the principle
files, its report path, and an instruction to run the per-item cycle
**autonomously** — plan (non-interactive brainstorming) → in-context spec
self-critique → TDD implement → in-context self-review → scoped tests — and to
return a **structured, terse result**:
`{ status: done|blocked, summary, branch, filesChanged, blocker?, scopedTestsOutput }`.
No `todo-spec-critique`/`todo-code-review` from inside the agent (no nesting). Mark
the row 🔜 at launch and record its worktree fork point (baseline sha) in the row's
report.

On **each completion notification**: run the post-item pipeline (below) for that
item, then top up — launch every item that just became ready, up to `N`. Never sit
on a free slot while ready items exist.

### 3. Post-item pipeline (orchestrator, serialized per item)

Process completions one at a time, FIFO; other agents keep running meanwhile —
that overlap is the point of rolling. For an item returned `done`:

1. Mark the row 🔬. Launch **`todo-code-review`** on that worktree's diff
   (`baseline` = the recorded fork point; `repoDir` = the worktree path so `git -C`
   runs there; scope `personas` to the diff). These are real workflows launched from
   the main loop — fine, not nested. Apply confirmed fixes in the worktree; re-run
   scoped tests there.
2. **Merge the worktree branch into the main working tree — never two merges
   concurrently.** "Independent by DAG" does **not** guarantee disjoint files — two
   unrelated items can still touch a shared registration point (a router, a plugin
   registry, a settings list). On a merge **conflict**, do not force: relaunch that item's
   agent once against the now-updated tree (a fresh worktree), **feeding the specific
   colliding hunks back as added context** so the retry resolves the real conflict
   rather than re-deriving it blind; if it conflicts again, mark it 🚧.
3. **Cheap compile gate, scoped tests, then commit.** Run the fast type-check /
   compile for the merged item's touched packages (e.g. `tsc --noEmit`, `mypy`,
   `cargo check`) to catch cross-item breakage — stale imports, type mismatches at a
   shared registration point — at the lowest cost. If it breaks, fix it (or revert
   this item's merge and relaunch its agent with the failure as added context). Then
   run the merged item's **scoped tests** (per step 5 above), print output, commit
   (`loop: NN <slug>`), and flip the row ✅ in `LOOP_STATE.md`. The **full suite**
   runs per batch exactly as in step 5: after every 3 merges and at the end, in the
   background, overlapping the next launches; a red batch stops new merges until fixed.
4. Launch newly-ready dependents (they fork from the just-merged state) and refill
   free slots.

An item returned `blocked` → mark 🚧, state the needed decision in this turn's
output, leave its dependents ⬜. Reprint the `LOOP_STATE.md` table after every
processed completion. If the turn must end while agents are still in flight,
`ScheduleWakeup` per Setup step 4. The OR HALT / all-✅ stop conditions are
unchanged; the run ends when no items are in flight and none are ready.

### Preserved vs. sacrificed vs. sequential

| | `--sequential` | Parallel rolling (default) |
| --- | --- | --- |
| Items in flight | 1 | up to `N`, topped up per completion |
| Context isolation | two background agents per item (plan, implement) | one background agent per item (whole cycle) |
| Edit isolation | shared tree + HEAD baseline | one git worktree per item |
| Fork point | n/a (shared tree) | latest merged state at launch |
| Spec critique | `todo-spec-critique` workflow | in-agent self-critique |
| Verified diff review | `todo-code-review` per item | `todo-code-review` per item, **post-item, overlapped** |
| `--light` review | in-context / one agent | same light pass, post-item |
| Merges | n/a | strictly one at a time |
| Blocked handling | stop and ask mid-item | return as finding; resolve post-item |
| Dependent items | natural (run in order) | launch when deps merge; never early |
