---
description: Convert an existing plan into context-rich TODO.md items that a fresh agent can complete on its own.
argument-hint: "<path/to/plan.md> [path/to/TODO.md]   # default backlog: ./TODO.md"
---

# Convert a plan into fresh-agent-ready TODO.md items

Turn the plan into backlog items that a fresh agent, with only `CLAUDE.md`, the repo and
the backlog, can take through `/todo-loop:work` to completion without guessing. **The
backlog must carry all the context the work needs** (contract C9): the plan is a
reference for extra detail, never the only place a decision lives. **Append** new items;
never rewrite, renumber or reorder existing ones.

`$ARGUMENTS`: arg 1 is the plan path (required; stop and ask if missing). Arg 2 is the
backlog (default `./TODO.md`; create it with a `# TODO` title if absent).

The run has three phases: **analyze** (read-only), **ask** (once, before any write),
**write**. Never ask a question after writing starts.

## Analyze (read-only)

1. Read `${CLAUDE_PLUGIN_ROOT}/references/item-contract.md`. Every item you write follows
   its § Shape and must pass its rubric, C9 included, with no fail.
2. **Read the inputs.** Read the whole plan, `CLAUDE.md` (or `AGENTS.md`), and the
   backlog: the highest id, the item heading style, its shared-context sections, and the
   open items (to avoid duplicates and wire dependencies).
3. **Ground the plan in the repo.** For every file, symbol, endpoint, package and command
   the plan names, confirm it exists (Grep and Glob tools, `git ls-files`) and record the
   exact `path:line`. Mark each file the plan creates with the literal `(new)`. When the
   plan says "the X module" without a path, find it. When the plan is wrong about the
   repo, the repo wins: note the correction. If the plan spans more than about six areas,
   ground them in parallel background `Explore` agents, each returning
   `{area, references: [{path, line, symbol, why}], corrections}`.
4. **Draft the items in memory.** One item = one cohesive change at the contract's sizing;
   split anything larger, order prerequisites first, and add `Depends on:` only for real
   output dependencies. A plan step already covered by an open item becomes a
   `Depends on:` or a note in your summary, never a duplicate. For each draft, list the
   **context it needs**: every decision with its reason, constraint, external contract
   detail and finding from the plan that the work depends on.
5. **Collect every question.** Open choices the plan leaves (C4), plan-vs-repo
   contradictions that change behavior, unclear scope boundaries, and missing facts a
   draft's context list cannot fill from the plan or the repo. A statement you could read
   two ways is a question too: never pick a reading silently. These are questions for the
   user, not for the fresh agent.

## Ask (once)

6. **Ask everything in one batch, before writing anything** (the ask-all tool when
   available, otherwise `AskUserQuestion`), each with options and your recommendation. An
   empty list → skip the ask. A question the user declines → that item gets a
   `**BLOCKED:** <question>` line. No way to ask (non-interactive run): decide internal
   details yourself (placement, naming, helper shape) with a logged reason, and write a
   `**BLOCKED:**` line for any choice that changes observable behavior, data or an
   external contract.

## Write

7. **Write the items** in the contract's § Shape, ids from highest + 1, in dependency
   order, under a `<plan title> (added YYYY-MM-DD)` divider heading with no id. Match the
   backlog's item heading level (`##` when it has none). **Copy each draft's context into
   the backlog:** decisions with reasons and the user's answers go in Decisions;
   constraints, contracts and findings go in Goal, References or Decisions. Background
   shared by three or more items goes once into a shared-context section per the
   contract's § DRY. Each item also cites its plan section (`<plan path>` § "<heading>")
   for extra detail.
8. **Self-check.** Grade the new open items against the rubric exactly as
   `/todo-loop:check` would, re-running the C2 reference checks against the repo and the
   C9 check against the plan. Fix every fail and rerun; do not finish with a fail.
   BLOCKED items are not graded. A gap found here that only the user can fill becomes a
   `**BLOCKED:**` line, not a late question.

## Output

A table of the appended items (id, title, size, depends on, verdict), the questions you
asked with the answers you applied, any corrections to the plan, and plan steps you
mapped onto existing items. End with:

```
Next: /todo-loop:estimate, then /todo-loop:work
```
