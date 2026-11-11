---
description: Quick read-only audit of a TODO.md - can a fresh agent complete each open item without guessing?
argument-hint: "[path/to/TODO.md] [item-id...]   # defaults: ./TODO.md, every open item"
---

# Check TODO.md items for fresh-agent readiness

Grade every open item in the backlog against the item contract and report which items a
fresh agent could finish autonomously, which would force it to guess, and the exact fix
for each gap. **Read-only:** never edit the backlog or any code.

`$ARGUMENTS`: arg 1 is the backlog path (default `./TODO.md`); any further args restrict the
check to those item ids.

## Steps

1. Read `${CLAUDE_PLUGIN_ROOT}/references/item-contract.md`. Its rubric (C1 to C9) is the
   only standard; do not invent criteria.
2. Read the backlog and `CLAUDE.md` (or `AGENTS.md`). Find the items and their status
   exactly as the contract's § Finding items and § Status markers define. Skip done,
   deferred and blocked items; count them in the summary.
3. **Ground every reference.** For each item, check that each cited path exists (unless
   marked `(new)`), each
   cited symbol is found in that file, each `file:line` lands near the named
   symbol, each plan section heading exists, and each `Depends on:` id is a real item.
   Run the checks with the Grep and Glob tools or `git ls-files`; never mark C2 pass from reading
   the item alone. Build the dependency graph and name any cycle.
4. **Probe sufficiency (C3, C4, C9).** For each item, ask: "starting from only this item and
   the repo, where would I edit first, and which choice would I have to make up?" If the
   answer needs a search the item gives no lead for, or a choice the item leaves open,
   that is the gap. Quote the vague phrase. **C9:** when an item leans on a plan or doc
   ("see the plan", "as designed in X"), open it: any decision or constraint the work
   needs that appears only there is a C9 fail. Name the fact to copy into the item.
5. **Fan out on big backlogs.** More than 10 open items: split them into batches of about
   8 and grade each batch in a background `Explore` agent, in parallel. Give each agent the
   contract path, the backlog path, its item ids, and the output row format below. Merge
   the rows. Do the step 3 graph check yourself, since it spans batches.

## Output

A summary line, then one row per open item, worst first:

```
Ready 11/12 (4 with warns) · not ready 1 · skipped 9 (done/deferred/blocked)
```

| Item | Verdict | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | C9 | Fix |
|------|---------|----|----|----|----|----|----|----|----|----|-----|

Verdict: **ready** (no fail) or **not ready** (any fail). Warns stay visible in the cells
and the Fix column but do not block. Cells use ✓ / ! / ✗. The Fix cell names the concrete edit, e.g.
"C2: `api/auth.py` moved to `api/auth/views.py`; C6: add `pytest api/tests/test_login.py`".

Below the table, list each failing item's quoted vague phrases and broken references
once, and end with the next step: `/todo-loop:work` if no open item fails, otherwise the
items to fix first (dependencies first).
