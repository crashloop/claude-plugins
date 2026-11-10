---
description: Convert an existing plan into context-rich TODO.md items that a fresh agent can complete on its own.
argument-hint: "<path/to/plan.md> [path/to/TODO.md]   # default backlog: ./TODO.md"
---

# Convert a plan into fresh-agent-ready TODO.md items

Turn the plan into backlog items that each carry enough context, references and decisions
for a fresh agent, with only `CLAUDE.md` and the repo, to take the item through
`/todo-loop:work` to completion without guessing. **Append** them to the backlog; never
rewrite, renumber or reorder existing items.

`$ARGUMENTS`: arg 1 is the plan path (required; stop and ask if missing). Arg 2 is the
backlog (default `./TODO.md`; create it with a `# TODO` title if absent).

## Steps

1. Read `${CLAUDE_PLUGIN_ROOT}/references/item-contract.md`. Every item you write follows
   its shape and must pass its rubric with no fail.
2. **Read the inputs.** Read the whole plan, `CLAUDE.md`, and the backlog: note the
   highest existing id, the item heading style, any `## Shared context` sections, and the
   open items (to avoid duplicates and to wire dependencies).
3. **Ground the plan in the repo.** For every file, symbol, endpoint, package and command
   the plan names, confirm it exists (`ls`, `rg`, `git ls-files`) and record the exact
   `path:line`. Note new files the plan creates as new. When the plan says "the X
   module" without a path, find it. When the plan is wrong about the repo, the repo
   wins: record the correction in the item's Decisions. If the plan spans more than about
   six areas, ground the areas in parallel background `Explore` agents, each returning
   `{area, references: [{path, line, symbol, why}], corrections}`.
4. **Split into items.** One item = one cohesive change at the contract's sizing (S/M/L);
   split anything larger. Order them so each item's prerequisites come first, and add
   `Depends on:` only for real output dependencies (an item that needs code, schema or an
   API another item creates). A plan step that is already covered by an open backlog item
   becomes a `Depends on:` or a note on that item in your summary, never a duplicate.
5. **Collect open questions before writing.** Every choice the plan leaves open (C4) is a
   question for the user, not for the fresh agent. Gather them all and ask them in **one
   batch** (the ask-all tool when available, otherwise `AskUserQuestion`), each with
   options and your recommendation. Put the answers into the items' Decisions. A question
   the user declines to answer → write that item with a `**BLOCKED:** <question>` line.
   No way to ask (non-interactive run): decide internal details yourself (placement,
   naming, helper shape) with a logged reason, but write a `**BLOCKED:**` line for any
   choice that changes observable behavior, data or an external contract.
6. **Write the items.** Use ids from highest + 1, in dependency order. Each item gets:
   the goal; references with `path:line` and a "why" each, including the plan section it
   came from (`<plan path>` § "<heading>"); decisions with reasons; In/Out scope; a
   `- [ ] Verified:` line with a runnable command and expected result; `Size:`. Background
   shared by three or more items goes once into a `## Shared context: <slug>` section
   placed above them, linked from each item's `Context:` line. Append under a
   `## <plan title> (added YYYY-MM-DD)` divider.
7. **Self-check.** Grade the new items against the rubric exactly as
   `/todo-loop:check` would, re-running the C2 reference checks against the repo. Fix
   every fail and rerun; do not finish with a fail.

## Output

A table of the appended items (id, title, size, depends on, verdict), the questions you
asked with the answers you applied, any corrections to the plan, and plan steps you
mapped onto existing items. End with:

```
Next: /todo-loop:estimate, then /todo-loop:work
```
