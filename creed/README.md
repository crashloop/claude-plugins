# creed

A Claude Code plugin that keeps a working discipline **present, persistent, and enforced** across
every session, instead of hoping the model remembers it.

## The problem

A behavioral manual sitting in a file enforces nothing. Even loaded into context, prose decays:
long conversations get summarized, and a manual in the middle is the first thing dropped.
Reminding is not enforcing.

## What it does

creed compresses the disciplines of `OPERATING_MANUAL.md` into an always-on core and wires it
into hooks, one per failure mode:

| Layer | Hook | Effect |
|-------|------|--------|
| **Persistence** | `UserPromptSubmit` | Injects the core every turn, so it survives a filling, summarized context. |
| **Presence** | `SessionStart` (`compact`) | Re-injects after a context compaction, the one moment `UserPromptSubmit` cannot cover. |
| **Enforcement** | `Stop` | Blocks a "done / fixed / passing" claim when no real command ran that turn. A reminder becomes a hard gate. |
| **Enforcement** | `PreToolUse` (`Bash`) | Denies a `git add`/`commit`/`stash` that names a secret-shaped file (`.env`, `*.pem`, `id_rsa`, credentials). |

The first two keep the rules in front of the model. The last two *enforce* rather than *ask*.

## The claim gate

`hooks/verify-claims.js` runs when the model finishes a turn. It blocks only when **both** hold:

1. The final message asserts completion (keyword match: "is fixed", "tests pass", "it works now", …).
2. No real command ran this turn. Read-only tools and bare inspection commands (`ls`, `echo`,
   `cat`, ...) do **not** count as proof; a test, request, or query does.

On a block, the model is told to produce the evidence a skeptic would demand or restate the claim as
unverified. It blocks **at most once per turn** (honors `stop_hook_active`), so it never loops.

**Ceiling (by design).** This is a heuristic, not real verification: the keyword list misses many
phrasings and can occasionally false-positive, and "a real command ran" is a proxy for "the right
check ran." It catches the common failure: declaring victory with nothing executed. Upgrade path:
have the gate extract the claimed check and re-run it, or escalate flagged turns to a small-model
judge.

## The secrets gate

`hooks/block-secrets.js` runs before every Bash call and denies `git add`/`commit`/`stash`
commands that name a secret-shaped path. `.env.example` and friends are allowed through.

**Ceiling (by design).** It matches the command string, not file contents: it catches
`git add .env`, but not a key pasted into a source file and not `git add .` sweeping an
untracked `.env`. Upgrade path: inspect `git diff --cached --name-only` instead of the command.

## Install

```sh
claude plugin marketplace add crashloop/claude-plugins   # or /path/to/repo for a local checkout
claude plugin install creed@crashloop-plugins
```

Then restart Claude Code so the hooks load at startup.

## Enable / disable

```sh
claude plugin disable creed@crashloop-plugins
claude plugin enable  creed@crashloop-plugins
```

## Updating

The marketplace install is pinned to a git commit; editing local files changes nothing until you
push and refresh:

```
git push                                    # publish the change
/plugin marketplace update crashloop-plugins
/reload-plugins
```

For a tight dev loop, add the marketplace from the local repo path instead of GitHub.
