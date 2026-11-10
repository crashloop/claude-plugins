---
description: Estimate the branches, worktrees and wall-clock time /todo-loop:work needs for the open TODO.md items.
argument-hint: "[path/to/TODO.md] [--parallel=N|--sequential]   # defaults: ./TODO.md, N = max(1, min(8, cores-2))"
---

# Estimate the remaining backlog

Predict what `/todo-loop:work` will need to finish every open item: how many branches and
worktrees it will create, how many waves it will run, and how long it will take
sequentially and in parallel. **Read-only.** State every assumption and where each number
came from.

`$ARGUMENTS`: arg 1 is the backlog path (default `./TODO.md`). `--parallel=N` or
`--sequential` mirror the `work` flags; the default is parallel with
N = `max(1, min(8, cores−2))` (`nproc`).

## Steps

1. Read `${CLAUDE_PLUGIN_ROOT}/references/item-contract.md` for the item shape, status
   markers and sizes. Parse the backlog the way `/todo-loop:check` does: level-2 work
   headings are items; skip done, deferred and blocked items, and list blocked ones.
2. **Size each open item.** Use its `Size:` line. Missing: infer S/M/L from the contract's
   sizing table by counting the files, packages and endpoints it references, and mark the
   size *inferred*.
3. **Build the dependency graph** from `Depends on:` lines (deps already done are
   satisfied). Compute topological **waves** (wave 1 = no open deps), the **critical
   path** (the longest chain by estimated time), and the **max width** (the largest
   wave). A cycle → report it and estimate the acyclic part only.
4. **Calibrate durations from history, not guesses.** In the repo, collect previous runs:
   `git log --format='%at %s' | rg ' loop: \d+ '` gives one commit per finished item.
   For each `docs/plans/*-todo-loop/LOOP_STATE.md`, take its mode (light/full,
   sequential/parallel). In sequential runs, the gap between consecutive item commits is
   that item's duration; drop gaps over 4 h as idle time. Match items to their size via
   the run's report files or the old TODO.md entry when you can. Use the **median per
   size** (or the overall median if sizes cannot be matched) and report the sample count.
   With fewer than 3 samples, fall back to S 20 min, M 45 min, L 90 min, and say plainly
   that these are **uncalibrated defaults**.
5. **Compute.**
   - **Branches:** parallel mode makes one worktree branch per open item; sequential
     makes none (it commits on the current branch).
   - **Worktrees at peak:** `min(N, max width)`; total worktrees created = open items.
   - **Sequential time:** sum of item durations.
   - **Parallel time:** simulate the rolling scheduler. Start each ready item when a slot
     is free; after an item finishes, its post-item review and merge run **serially** in
     the orchestrator, about 25% of an item's duration (or the measured share from
     parallel history), before its dependents become ready. Report the simulated
     makespan, the critical-path floor, and which bound binds.
   - **Light mode** (`--light`): if history has light runs, use their median; otherwise
     note that light only cheapens reviews and leave the estimate unchanged.
6. Run `/todo-loop:check`'s C2 and C4 checks on each item, without fanning out. Items
   that fail are **at risk**; list them and count them in a "± risk" line. Do not drop
   them from the estimate.

## Output

```
Open 12 · blocked 1 · waves 4 · critical path #3 → #7 → #11 (3 items)
Branches 12 · worktrees peak 6 (N=10, width 6)
Sequential ≈ 9 h 10 min · parallel ≈ 3 h 40 min (critical path floor 2 h 50 min)
Calibration: 14 past items, median S 18 min / M 41 min / L 1 h 35 min
At risk: #5 (C4 open choice), #9 (C2 broken ref)
```

Then a per-wave table (wave, items with sizes, estimated duration) and a timeline on a
▏───▏ axis showing the parallel schedule lane by lane, in a fenced block whose opening
line is exactly ```figure (nothing after it). End with the
assumptions in one short list.
