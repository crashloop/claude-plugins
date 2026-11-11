---
description: Turn the work agreed or left open in this conversation into fresh-agent-ready TODO.md items.
argument-hint: "[path/to/TODO.md] [focus...]   # default backlog: ./TODO.md; focus narrows what to capture"
---

# Capture this conversation's work as TODO.md items

Read back through **this conversation**, latest messages first, and turn the work it
agreed on, deferred, or left open into backlog items a fresh agent can finish without
the conversation. The agent that runs them will see `CLAUDE.md`, the repo and the item,
never this chat, so every decision, constraint and finding that lives only here must be
written down.

`$ARGUMENTS`: arg 1 is the backlog if it ends in `.md` (default `./TODO.md`; create it
with a `# TODO` title if absent). Any remaining words are a **focus** ("the review
findings", "batch 3 only") that limits what to capture.

## Steps

1. Read `${CLAUDE_PLUGIN_ROOT}/references/item-contract.md` and the backlog: the highest
   id, the heading style, and the open items (to avoid duplicates and wire dependencies).
2. **Harvest candidates from the conversation yourself.** Subagents cannot see it, so
   never delegate this step. Weight the latest messages most; go back only as far as the
   current topic runs. Collect:
   - work the user asked for or approved that is **not done yet**;
   - follow-ups, "left for you" lists, deferred fixes, review findings not yet applied;
   - bugs, gaps or risks found and not fixed.

   Skip work this conversation already finished: confirm with `git log`, `git status` or
   the files, not from memory. Skip options the user rejected and ideas nobody took up.
3. **Separate decisions from suggestions.** A choice is **decided** only when the user
   stated it or approved it. A choice the assistant proposed that the user never took up
   is an **open question**. For each candidate, record the facts that exist only in the
   chat: decisions with their reasons, constraints the user stated, measurements and
   reproductions, and file paths and commands that were used.
4. **Write the capture file** `docs/plans/<YYYY-MM-DD>-<slug>.md` with a `## <topic>`
   section per candidate: goal, decided facts (each tagged "decided by the user" or
   "found: <evidence>"), open questions, and pointers into the repo. This is the durable
   record that items cite for chat-only context. It is not a transcript, so drop the
   back-and-forth.
5. **Confirm and ask in one batch** (the ask-all tool when available, otherwise
   `AskUserQuestion`). Ask which candidates to add or amend into existing items
   (multi-select, all checked by default), plus every open question from step 3, each
   with options and your recommendation. Put the answers into the capture file. No way to
   ask (non-interactive run): add all candidates and follow `convert-plan` step 5's rule
   for open questions.
6. **Convert.** Follow `${CLAUDE_PLUGIN_ROOT}/commands/convert-plan.md` steps 3, 4, 6 and 7
   with the capture file as the plan: ground every reference in the repo, split into
   items with dependencies, write them in contract shape, and self-check against the
   rubric. Each item cites its capture-file section (`<capture path>` § "<topic>").
7. **Amend, don't duplicate.** A candidate that matches an open item becomes an
   **additive amendment** to it, never a new item and never a rewrite. Append each decided
   fact to its Decisions as `- <fact> (decided YYYY-MM-DD, <capture path> § "<topic>")`.
   Where the chat leaves a behavior choice open, or contradicts the item's text, add a
   `**BLOCKED:** <question>` line under its heading. Leave existing text in place.

## Output

A table of the appended items (id, title, size, depends on, verdict), the amended items
with what was added, the capture file path, the questions you asked with the answers you
applied, and any candidates you skipped because they were already done or rejected. End with:

```
Next: /todo-loop:check, then /todo-loop:work
```
