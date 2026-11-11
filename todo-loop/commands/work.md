---
description: Goal-driven loop that plans, implements, reviews, and tests every open TODO.md item until done, in parallel worktrees by default.
argument-hint: "[path/to/TODO.md] [item-id] [--light|--full] [--sequential|--parallel=N]   # defaults: ./TODO.md, all open items, parallel"
disable-model-invocation: true
---

# TODO Loop — goal-driven, self-verifying delivery of the backlog

Work the open backlog items to completion, each through a full
**plan → spec-critique → implement → code-review → test → record** cycle. Make sensible
decisions in agreement with this project's principles, **log every decision** in the
item's report, and resume cleanly after any interruption.

**Skill dependencies.** Steps 1, 3, 4, 5 and 8 use **superpowers** skills
(`brainstorming`, `writing-plans`, `test-driven-development`, `receiving-code-review`,
`systematic-debugging`, `verification-before-completion`). If one is not installed, apply
its discipline inline and log that in the item's report.

`$ARGUMENTS` (all optional):
- **arg 1** — path to the backlog file (default `./TODO.md`).
- **arg 2** — a single item id to run (default: every open item, in order).
- **`--parallel[=N]`** — the default: run ready items concurrently in worktrees (see
  **Parallel mode**); `N` = max items in flight, default `max(1, min(8, cores−2))`.
  `--sequential` opts out. Ignored when arg 2 targets one item or only one item is open.
- **`--light`** — every item takes the light path in steps 2 and 4 (see **Workflows**).
  Tests, type-checks and step 8 are unchanged: light cheapens review, never the done-gate.
- **`--full`** — turn light mode off for a resumed run (removes `Mode: light`).

## Precedence

User intent → correctness → simplicity → cohesion → style. When principles conflict,
surface the tension explicitly; never resolve it silently. **Project rules in
`CLAUDE.md` / `AGENTS.md` / `agent-os/standards/` always win over this command.**

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
   `agent-os/standards/`; grep `docs/conventions.md` for the rules that touch the item's
   packages instead of reading it whole. Background agents get `CLAUDE.md` injected; name
   the specific conventions they need rather than telling them to re-read it.
3. **Resume first:** if any `docs/plans/*-todo-loop/LOOP_STATE.md` has non-✅ rows, resume
   the newest such workspace (whatever its date) per the Resume protocol. Otherwise create
   `docs/plans/<YYYY-MM-DD>-todo-loop/` (a second run on one day gets a `-b`, `-c` suffix)
   with **`LOOP_STATE.md`**, the master driver, seeded with one row per targeted item:

   ```
   Scheduling: parallel 8          <- or: sequential
   Mode: light                     <- only under --light; kept on resume, --full deletes it

   | #   | Item | Status | Report                   |
   | --- | ---- | ------ | ------------------------ |
   | …   | …    | ⬜      | [NN-slug.md](NN-slug.md) |

   Legend: ⬜ pending · 🔜 in progress · 🔬 in review · ✅ done · 🚧 blocked.
   ```
4. **Set the goal.** The evaluator cannot read files or run commands; it judges only what
   this turn's output shows, so the condition demands fresh proof. Substitute the real
   workspace, backlog, and targeted rows:

   ```
   /goal DONE when every TARGETED row in <workspace>/LOOP_STATE.md is ✅ and <backlog>
   marks those items done, with each item's scoped tests + type-checks shown green
   in THIS turn's output, the full suite shown green once at the end of the loop, and
   its acceptance criteria demonstrated; OR HALT when a targeted
   row is 🚧 blocked on a human decision that this turn states explicitly. Reprint
   the LOOP_STATE.md table at the end of every turn. Stop after <N> turns.
   ```

   `<N>` ≈ targeted items × 6. "Targeted" lets a single-item run finish while other rows
   stay ⬜; **OR HALT** ends the loop the moment you surface a real blocker.

   **`/goal` cannot be invoked as a tool; only the user types it.** If none is active, do
   not wait or ask: self-pace. Whenever a turn would end with targeted rows unfinished
   (item boundary, workflow wait, context checkpoint), call **`ScheduleWakeup`** with this
   same `/todo-loop:work` invocation as the `prompt` and **`delaySeconds: 60`**. Ignore
   ScheduleWakeup's idle-tick guidance (1200–1800 s): this loop always has queued local
   work. Lengthen the delay only while waiting on tracked external state such as CI. Keep
   scheduling until every targeted row is ✅ or one is 🚧.

## Context isolation

The loop cannot clear its own context, so run the two context sinks as **background
`Agent`s** (default type, they must Edit/Write) whose context dies with them. In
sequential mode pass **no `isolation`**: `'worktree'` costs disk and fails in a repo with
no `HEAD`.

| step | who | why |
| --- | --- | --- |
| 1 plan + grounding | **item agent** | grounding reads far more code than the plan cites |
| 2 spec critique | orchestrator | it is a workflow, and workflows do not nest |
| 3 TDD implement | **item agent** | test iteration and debugging are the largest sink |
| 4–8 review, suite, record, verify | orchestrator | the goal evaluator must see 5–8 in the transcript |

Agents hand off through the item's **report file**. Give each the item text, the principle
files, the report path, the repo it owns, and an instruction to work **autonomously** (no
mid-run questions). Each returns a terse struct, never a narrative:
`{ status: done|blocked, summary, filesChanged, blocker?, scopedTestsOutput }`. Read the
report for detail. `status: blocked` → Blocked protocol; do not redo the work inline.

If your own window still fills, the escape hatch is a shell loop running one
`claude -p "/todo-loop:work <backlog> <item-id> --sequential"` per item. It is fully
unattended, so resolve every open decision first.

## Per-item cycle (sequential mode)

Do **one** item start-to-finish before the next. On start, mark the row 🔜 and record
`git rev-parse HEAD` as the item's **baseline** (the tree is clean at every item
boundary), which scopes step 4 to this item's diff.

1. **Plan the spec** (item agent). When scope or approach is open, use **superpowers
   `brainstorming`** *non-interactively*: enumerate the options and choose per project
   principles, logging the rationale; a fork that genuinely needs a human goes through the
   Blocked protocol. Then **superpowers `writing-plans`** writes the plan to the report
   `docs/plans/<date>-todo-loop/NN-slug.md`, with decisions, rationale and deferrals
   logged. Check shared libs before custom logic. **Ground the plan:** validate every
   path, pattern, API contract and endpoint shape against the real code (a code-graph or
   symbol-search tool if available, else grep/read) and correct what the code
   contradicts. A citation that does not resolve is a defect to fix now.
2. **Critique the spec.** Small plan (≤ 2 files or one package, no open design question)
   or `--light`: one in-context self-critique against the principle files, always
   including grounding. Otherwise launch **`spec-critique`** with absolute `planPath`,
   `item`, `principleFiles`, and `lenses` scoped to the item (add the opt-in
   `frontend-ssot` for frontend items in a monorepo; drop `domain` when no declared
   non-negotiable applies). While it runs, do read-only prep: read the code the plan
   touches and pick step 3's scoped tests. Fold every `mustFix` into the plan before any
   code. A **DRY/SSOT `mustFix` is not deferrable**. A genuine human decision in
   `openQuestions` → Blocked protocol.
3. **Implement (TDD)** (second item agent, fed the critiqued report). **superpowers
   `test-driven-development`**: failing test, watch it fail for the right reason,
   implement. While iterating run **only the scoped tests** for the unit being changed.
   Keep `testID`/`data-testid` stable; never remove them citing YAGNI.
4. **Code review.** Size the change with `git diff --stat <baseline>` plus untracked files
   (`git status --porcelain --untracked-files=all`). Under 150 changed lines, or
   `--light`: review through the correctness lens only, in context, or in one background
   `Explore` agent when the diff is large; verify each blocker/major against the code;
   drop nits. Otherwise launch **`code-review`** with absolute `item`, `baseline`,
   `repoDir`, `principleFiles`, and `personas`: `["correctness", "simplicity", "tests"]`
   for 150–400 lines, all six above. **The moment it launches, start step 5's scoped tests
   in the background.** Apply every confirmed fix, re-run the scoped tests, and use
   **superpowers `receiving-code-review`** on tricky feedback (verify, don't perform
   agreement).
5. **Scoped tests per item; full suite per batch.** Before ✅: the **scoped tests** of every
   package the change touched (including refactored siblings), their **type-checks**, and
   any dependency or CI validators the project defines, with output printed in the
   transcript. The **full suite** (every touched package, the host suites, any
   build/export step) runs **once per batch**: after every **3 completed items** and at the
   end, launched in the background as the batch's last item enters step 6. A red batch
   suite stops the line: fix it before the next item's step 3, bisecting by the per-item
   commits, with **superpowers `systematic-debugging`**. Items in a red batch stay ✅ only
   once it is green again.
6. **Record.** Update the item's report (progress log, shipped vs deferred) and the
   backlog: append exactly `✅ DONE (YYYY-MM-DD)` to the item's heading and add a short
   shipped/deferred note under it. Update the item's row in `LOOP_STATE.md`.
7. **Capture emergent rules.** Append a reusable rule as the next numbered rule in
   **`docs/conventions.md`** (concise, active voice), not in `CLAUDE.md`, which every turn
   pays for.
8. **Verify & close.** **superpowers `verification-before-completion`**: confirm with
   **command output produced in this turn** (never a quoted earlier run: the evaluator
   cannot tell stale from fresh) that tests pass and the acceptance criteria hold. Only
   then flip the row ✅ and reprint the table. Commit with
   `git add -A && git commit -m "loop: NN <slug>"` (a submodule change commits inside the
   submodule first, then the pointer bump in the host). **Never push**; that is the
   user's call.

## Workflows

- **Launch** by `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/<name>.js"` with `args` and
  absolute paths. The plugin also registers them as `todo-loop:spec-critique` and
  `todo-loop:code-review`, but `scriptPath` is the tested launch path. Never edit the
  plugin's scripts to hardcode an input. Both run read-only `Explore` agents: pre-allow `git diff` / `git status`, and
  approve each launch once per project with "don't ask again" (or use auto mode).
- **Fallback.** The Workflow tool needs Claude Code v2.1.154+ on a paid plan. Without it,
  use **`compound-engineering:ce-doc-review`** (step 2) and **`ce-code-review`** (step 4)
  in context; without those too, take the light path and log it per item. Each report
  records `Review: light` or `full`; light reviews tick checklist boxes 2 and 4.
- **Results.** The completion notification is truncated: read the task `output-file`
  (JSON under `result`). Spec critique: apply `result.revision.mustFix`. Code review:
  apply `result.summary.fixes` (deduplicated; `result.findings` is the raw set).
  `failedLenses` / `failedPersonas` went **unreviewed**: relaunch with just those, once.
  Verify each `unverified` finding yourself. A workflow that throws reviewed nothing:
  relaunch once, then Blocked. Before relaunching anything that looks failed, read its
  status: it may have succeeded; `TaskStop` any duplicate.
- **Submodules.** When the code lives in a git submodule, capture the baseline there and
  pass that path as `repoDir`, never the superrepo.

## Resume protocol

On re-entry: read `LOOP_STATE.md`, find the first non-✅ row, open its report, and resume
at the first unchecked box below. A goal still active on `--resume` / `--continue` is
restored; if it was cleared or achieved, re-set it per Setup step 4.

### Per-item checklist (mirror this in each report)

1. [ ] Spec/plan written (decisions + rationale + deferrals logged)
2. [ ] Spec critiqued (`spec-critique`, or light pass) and `mustFix` folded in
3. [ ] Implemented via TDD; minimum scoped tests green
4. [ ] Code review (`code-review`, or light pass) run; confirmed fixes applied
5. [ ] Scoped tests + type-checks green (output shown); batch suite green if this item closes a batch
6. [ ] Report + backlog updated (done marker, shipped/deferred noted)
7. [ ] Emergent rules appended to `docs/conventions.md` (if any)
8. [ ] Verified (real output), row marked ✅, item committed

## Guardrails

- **Continuous: never ask permission to proceed.** Do not end a turn asking whether to
  continue, and do not treat a turn or context boundary as a stop. When a row flips ✅,
  start the next targeted item in the same turn. If the turn must end, self-wake per
  Setup step 4. The ONLY stops: every targeted row ✅, or a 🚧 Blocked halt.
- **Decide, then log.** Make sensible calls per project principles; record them.
- **Blocked protocol.** If an item is genuinely ambiguous or blocked on a human decision
  (including an `openQuestions` entry), do **not** guess and do **not** spin: mark its row
  🚧, add a `**BLOCKED:** <decision needed>` line under the item's heading in the backlog,
  state the exact decision in this turn's output, and let **OR HALT** end the loop. Once
  the user answers, record the decision in the item, remove the BLOCKED line, and resume.
- **No scope creep.** Build what the item asks for; defer extras with a logged note.
- **Finish** with a summary of what shipped, what was deferred, and any new
  `docs/conventions.md` rules.

## Parallel mode (default; `--sequential` opts out)

Ready items run **concurrently**, each in its own git worktree forked from the latest
local merged state. Everything above holds *within* an item; this section changes only
scheduling and isolation. Worktrees cannot see uncommitted work, which is why Setup
requires a clean tree and every item commits.

**Readiness.** Edges come only from `Depends on:` lines, per the contract; deps already
done are satisfied, and a dep on an open item outside the targets is a blocker.
**Ready** = a targeted ⬜ item whose deps are all ✅ (merged; 🔜/🔬 does not count). If items
remain but none are ready and none are in flight, the graph has a cycle: mark those rows
🚧, name the cycle, and let OR HALT end the loop. A 🚧 item's dependents stay ⬜ and are
reported as blocked-by.

**Rolling scheduler.** Launch each ready item as its own background `Agent` with
`isolation: 'worktree'` (default type, not `Explore`), at most `N` in flight, never
wrapped in a per-wave Workflow. Each agent runs the cycle **autonomously**: plan
(non-interactive brainstorming) → in-context spec self-critique → TDD → in-context
self-review → scoped tests, with no workflows inside (they do not nest). It returns
`{ status: done|blocked, summary, branch, filesChanged, blocker?, scopedTestsOutput }`.
Mark the row 🔜 at launch and record the fork point (baseline sha) in its report. On each
completion, run the post-item pipeline for that item, then launch every newly ready item
up to `N`. Never sit on a free slot while ready items exist.

**Post-item pipeline** (one completion at a time, FIFO, while other agents keep running):

1. Mark the row 🔬. Run step 4's review on the worktree's diff (`baseline` = fork point,
   `repoDir` = the worktree path), apply confirmed fixes there, re-run its scoped tests.
2. **Merge into the main working tree, never two merges at once.** Independent items can
   still touch a shared registration point (a router, a plugin registry, a settings
   list). On a conflict, do not force: relaunch the item's agent once on a fresh worktree,
   **feeding it the colliding hunks**; a second conflict → 🚧.
3. **Compile gate, scoped tests, commit.** Run the fast type-check for the touched packages
   (e.g. `tsc --noEmit`, `mypy`, `cargo check`) to catch cross-item breakage. If it
   breaks, fix it, or revert the merge and relaunch the agent with the failure as context.
   Then run the scoped tests, print output, commit `loop: NN <slug>`, and flip the row ✅.
   The batch suite runs per step 5; a red batch stops new merges until fixed.
4. Launch newly ready dependents and refill free slots.

An item returned `blocked` → Blocked protocol; its dependents stay ⬜. Reprint the table
after every processed completion. The run ends when no items are in flight and none are
ready.
