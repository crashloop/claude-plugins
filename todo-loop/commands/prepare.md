---
description: Turn the work agreed or left open in this conversation into fresh-agent-ready TODO.md items.
argument-hint: "[path/to/TODO.md] [focus...]   # default backlog: ./TODO.md; focus narrows what to capture"
---

# Capture this conversation's work as TODO.md items

Read back through **this conversation**, latest messages first, and turn the work it
agreed on, deferred, or left open into backlog items a fresh agent can finish without
the conversation. That agent sees `CLAUDE.md`, the repo and the backlog, never this
chat, so **every decision, constraint and finding that lives only here must be written
into the backlog** (contract C9).

`$ARGUMENTS`: arg 1 is the backlog if it ends in `.md` (default `./TODO.md`; create it
with a `# TODO` title if absent). Any remaining words are a **focus** ("the review
findings", "batch 3 only") that limits what to capture.

The run has three phases: **analyze** (read-only), **ask** (once, before any write),
**write**. Never ask a question after writing starts.

## Analyze (read-only)

1. Read `${CLAUDE_PLUGIN_ROOT}/references/item-contract.md` and the backlog: the highest
   id, the heading style, its shared-context sections, and the open items.
2. **Harvest candidates from the conversation yourself.** Subagents cannot see it, so
   never delegate this step. Weight the latest messages most; go back only as far as the
   current topic runs. Collect:
   - work the user asked for or approved that is **not done yet**;
   - follow-ups, "left for you" lists, deferred fixes, review findings not yet applied;
   - bugs, gaps or risks found and not fixed.

   Skip work this conversation already finished: confirm with `git log`, `git status` or
   the files, not from memory. Skip options the user rejected and ideas nobody took up.
3. **Separate decisions from suggestions, and collect the context.** A choice is
   **decided** only when the user stated or approved it; one the assistant proposed that
   the user never took up is an **open question**. For each candidate, write down every
   chat-only fact the work needs: decisions with their reasons, constraints the user
   stated, measurements and reproductions, error messages, file paths and commands that
   were used. Reword them as standalone facts; a fresh agent cannot resolve "as we said
   above".
4. **Ground and draft.** Follow
   `${CLAUDE_PLUGIN_ROOT}/commands/convert-plan.md` steps 3 and 4 with the candidates as
   the plan: ground every reference in the repo and draft the items in memory. A
   candidate that matches an open item becomes a draft **amendment** to it, not a new item.
5. **Collect every question**: the open questions from step 3, plus anything step 4 found
   that only the user can settle (a contradiction between the chat and the repo or an
   existing item, an unclear scope boundary, a missing fact). A statement you could read
   two ways is a question too: never pick a reading silently.

## Ask (once)

6. **Ask everything in one batch, before writing anything** (the ask-all tool when
   available, otherwise `AskUserQuestion`): which candidates to add or amend into
   existing items (multi-select, all checked by default), plus every question from step 5,
   each with options and your recommendation. No way to ask (non-interactive run): take
   all candidates and follow `convert-plan` step 6's rule for open questions.

## Write

7. **New items:** follow `convert-plan` step 7, with the chat as the source. Every fact
   from step 3 and every answer from step 6 goes into the item (or a shared-context
   section), tagged where it came from: `(decided by the user YYYY-MM-DD)` or
   `(found YYYY-MM-DD: <evidence>)`.
8. **Amendments** are additive, never a rewrite: append each decided fact to the item's
   Decisions with the same tag, and add a `**BLOCKED:** <question>` line under its
   heading where the chat leaves a behavior choice open or contradicts its text. Leave
   existing text in place.
9. **Self-check** per `convert-plan` step 8, applied to new and amended items, with C9
   checked against the facts from step 3: none may be missing from the backlog.

## Output

A table of the appended items (id, title, size, depends on, verdict), the amended items
with what was added, the questions you asked with the answers you applied, and any
candidates you skipped because they were already done or rejected. End with:

```
Next: /todo-loop:check, then /todo-loop:work
```
