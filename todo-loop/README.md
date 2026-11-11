# todo-loop

Turns a plan into a backlog fresh agents can finish alone, sizes the run, then works every
open `TODO.md` item to completion: plan, spec critique, implement (TDD), code review, test,
record, verify. Independent items run in parallel worktrees by default.

## Install

```
/plugin marketplace add crashloop/claude-plugins
/plugin install todo-loop@crashloop-plugins
```

On Claude Code 2.1.275+ one step works: `/plugin install todo-loop --marketplace crashloop/claude-plugins`.

## Commands

| Command | Does |
|---------|------|
| `/todo-loop:prepare [TODO.md] [focus...]` | Captures the work agreed, deferred or left open in the current conversation as items, writing every chat-only decision into the backlog; asks all questions upfront |
| `/todo-loop:convert-plan <plan.md> [TODO.md]` | Appends the plan as fresh-agent-ready items: grounded `path:line` references, decisions (asks all questions upfront, in one batch), scope, a runnable verify step, size, dependencies |
| `/todo-loop:check [TODO.md] [ids...]` | Read-only: grades each open item C1 to C9 and names the exact fix for each gap |
| `/todo-loop:estimate [TODO.md] [--parallel=N\|--sequential]` | Read-only: branches, peak worktrees, waves, critical path, sequential vs parallel time, calibrated from past `loop:` commits |
| `/todo-loop:work [TODO.md] [item-id] [--light\|--full] [--sequential\|--parallel=N]` | Runs the loop: commits each item locally, never pushes |

All five share one definition of a ready item:
[`references/item-contract.md`](references/item-contract.md).

Typical flow:

```
/todo-loop:convert-plan docs/plans/my-plan.md   # or, after a design chat: /todo-loop:prepare
/todo-loop:check
/todo-loop:estimate
/todo-loop:work
```

`work` prints a `/goal` condition; type it so a fresh model verifies
completion. `/goal` cannot be invoked by the agent; without it the loop self-paces
through `/loop` dynamic mode.

## Contents

| Path | Role |
|------|------|
| `commands/work.md` | The loop |
| `commands/prepare.md`, `convert-plan.md`, `check.md`, `estimate.md` | Backlog prep and sizing |
| `references/item-contract.md` | Item shape, status markers, rubric, sizing |
| `workflows/spec-critique.js` | Step 2: multi-lens plan critique, synthesized `mustFix` list |
| `workflows/code-review.js` | Step 4: six persona reviewers, each finding adversarially verified |

`work` launches both workflows by `scriptPath` under `${CLAUDE_PLUGIN_ROOT}`.

## Requirements

- Claude Code v2.1.154+ on a paid plan (Workflow tool), trusted workspace, hooks enabled
  (for `/goal`).
- A git repo with a `HEAD` (parallel mode forks worktrees).
- Recommended: the **superpowers** plugin (brainstorming, writing-plans,
  test-driven-development, receiving-code-review, systematic-debugging,
  verification-before-completion). Missing skills are applied inline.
- Optional: **compound-engineering** (`ce-doc-review`, `ce-code-review` fallbacks when
  workflows are unavailable). With neither workflows nor these, steps 2 and 4 take the
  light path.
- Optional: **ask-all**, so `prepare` and `convert-plan` ask their questions as one form; otherwise they
  uses `AskUserQuestion`.
- `work` needs a clean git tree to start.

## Writes

`docs/plans/<date>-todo-loop/` (`LOOP_STATE.md` plus one report per item) and
`docs/conventions.md` (emergent rules), the item's done marker in the backlog, and one
local `loop: NN <slug>` commit per item (never pushed). Reads `CLAUDE.md` (or
`AGENTS.md`) and `agent-os/standards/`.

For unattended runs, approve each workflow's launch once per project with "don't ask
again", and pre-allow `git diff` and `git status` for the read-only reviewer agents.
