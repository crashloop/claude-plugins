# TODO.md item contract

The single definition of a **fresh-agent-ready** item. `/todo-loop:convert-plan` writes
items to it, `/todo-loop:check` grades items against it, `/todo-loop:estimate` reads its
fields, and `/todo-loop:work` consumes it.

A fresh agent has `CLAUDE.md`, the repo, and this one item. Nothing else. The item must let
it finish the work without asking a question or guessing an answer.

## Shape

```markdown
## #<id> — <imperative title>

Size: S | M | L
Depends on: #<a>, #<b>            <!-- omit the line when there are none -->
Context: [Shared context](#shared-context-<slug>) <!-- optional, see DRY below -->

**Goal.** One or two sentences: the outcome and why it matters.

**References.**
- `path/to/file.py:120` `function_name` — what it does today, why it matters here
- `docs/plans/2026-11-10-foo.md` § "Data model" — the decided schema
- <URL or doc> — the external contract this must honor

**Decisions.** Choices already made, each with a one-line reason. The agent applies them,
it does not revisit them.

**Scope.** In: the files/packages/behaviors to change. Out: tempting neighbors to leave alone.

**Steps.** Optional ordered hints when the order is not obvious.

- [ ] Verified: <observable behavior> — `<command>` shows <expected result>
```

## Status markers (in the heading)

| Marker | Meaning |
|--------|---------|
| none | open |
| `✅ DONE (YYYY-MM-DD)` | done; skipped by every command |
| a `**DEFERRED (date, reason).**` line under the heading | out of scope; skipped |
| a `**BLOCKED:** <question>` line under the heading | needs a human answer first |

Ids are unique integers, never reused. New items continue from the highest existing id.

## Rubric

`check` grades each criterion **pass / warn / fail**. An item is **ready** when it has no
fail. `convert-plan` must not emit an item with a fail.

| # | Criterion | Fail when |
|---|-----------|-----------|
| C1 | **Goal** | no stated outcome, or the outcome is a topic ("auth stuff") rather than a result |
| C2 | **References resolve** | a cited path, symbol, line, or plan section does not exist in the repo, unless the item marks it `(new)`: a file the item itself creates |
| C3 | **References suffice** | the work touches code or contracts the item never points to, so the agent must search blind for where to start |
| C4 | **Decisions made** | the item contains an open choice ("X or Y", "TBD", "decide", "maybe", "?") with no decision, or a choice that changes behavior is left implicit |
| C5 | **Scope bounded** | no In/Out, or In is unbounded ("refactor as needed", "clean up") |
| C6 | **Verifiable** | no `- [ ] Verified:` line, or it names no runnable command or observable result |
| C7 | **Dependencies sound** | `Depends on:` cites a missing id, forms a cycle, or the item plainly needs another open item's output without declaring it |
| C8 | **Sized** | no `Size:`, or the work spans more than one cohesive change (split it) |

Warn when a criterion is met but thin: a reference with no "why", a verify step that is
manual only, an L item that could reasonably split.

## Sizing

One item = one cohesive change a single loop cycle can plan, implement, review and test.

| Size | Rough shape |
|------|-------------|
| S | one file or function, < ~100 changed lines |
| M | one package or feature slice, < ~400 changed lines |
| L | several packages or a migration, < ~1000 changed lines; above that, split |

## DRY

When three or more items share the same background (principles, an architecture section,
an environment trap), write it once as a `## Shared context: <slug>` section above them and
link it from each item's `Context:` line. Do not copy it into every item.
