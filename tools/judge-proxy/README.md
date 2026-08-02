# judge-proxy

An OpenAI-shaped `/v1/chat/completions` on loopback, answered by a real
`claude -p`. It exists so hoolint's `local_llm` judge stages can be exercised and
measured on a machine with no GPU worth using.

Forked from `llm-faker`. Everything except `openai_route.py` is inherited and left
alone so the fork stays easy to diff against upstream; hoolint only ever calls the
one route.

## This is a benchmark harness, not a hoolint feature

Two lines you should not cross with it:

**It forwards your code to Anthropic.** hoolint's `local_llm` resolves its
`base_url` and refuses anything that is not loopback or private, specifically so a
project's config cannot ship file spans to a public host. A loopback proxy that
relays to a cloud model defeats that check by construction. Nothing in the hoolint
package references this tool, and nothing should.

**It does not belong in the Stop hook.** A judged call costs seconds even at its
fastest, and a rule that leaves thinking on still costs tens of seconds. Use it
in git mode, in CI, and for measuring rule precision. For session mode use the
`escalate` stage instead, which costs nothing extra because the session model is
already running.

## Run it

```bash
uv sync
uv run uvicorn app:app --port 11435
```

Port 11435 rather than 11434, so it never collides with a real Ollama.

Then point a rule at it. Keep the timeout generous: hoolint defaults to 30s, and
a rule that leaves thinking on can exceed it, which surfaces as `local_llm
skipped (endpoint unreachable)` and demotes the rule to advisory.

```toml
[[rule.stage]]
strategy = "local_llm"
op = "and"
model = "qwen3:4b"          # ignored unless it names a Claude model
base_url = "http://localhost:11435/v1"
reasoning_effort = "none"   # omit to let the judge think
timeout = 240
```

| env var | default | meaning |
| --- | --- | --- |
| `JUDGE_PROXY_MODEL` | `haiku` | model used when the request does not name a Claude one |
| `JUDGE_PROXY_TIMEOUT` | `120` | seconds before the subprocess is killed |

## Where the seconds went

Measured on this box with a one-item judging prompt. The original build spent
almost all of its time in two places that had nothing to do with judging:

| lever | before | after |
| --- | --- | --- |
| thinking (`reasoning_effort = "none"` → `MAX_THINKING_TOKENS=0`) | 645-992 output tokens, ~10s of API time | 67-88 tokens, ~2s |
| CLI boot (warm spare) | 2.5-14s on the critical path, and the main source of variance | booted before the request arrives |
| prefill (`--system-prompt` replaces the default) | ~35k tokens | ~7.5k |

End to end, five consecutive judged calls with thinking off and a warm spare:
2.6s, 2.9s, 3.1s, 3.1s, 3.9s. The same route before these changes measured 15.7s
to 34.4s.

`--effort low` was measured and did nothing; `MAX_THINKING_TOKENS` is the knob
that moves. Replacing the system prompt did not change latency, so it is here for
cost and for isolation: with the default prompt the judge inherits the operator's
`CLAUDE.md` and hook output, which is not evidence about the span it is judging.

## How the warm spare works

Each request gets a process that has never seen another file's verdicts, but not
one it had to wait for. A `claude -p` in `--input-format stream-json` mode boots
and then sits idle until a prompt arrives, so the proxy parks exactly one booted
spare, hands it over when a request lands, kills it afterwards, and boots the
next. A plain `-p` pipe cannot be prewarmed: it starts work only when stdin
closes.

One spare, not a pool: judging is serial per file. A request whose model or
thinking setting differs from the parked spare's just pays the boot.

The spare takes 2-3s to boot, so requests arriving faster than that miss it and
pay the boot themselves. Measured: three back-to-back `hoolint check` runs cost
5.4s, 7.8s and 6.3s, against 3.2s for a run that found a ready spare. Judging
inside one hoolint run is spaced by hoolint's own work, so this mostly bites when
scripting the proxy in a tight loop.

## Why the route enforces an output format

Asked to judge without instruction, the CLI answers in prose: *"I need to see the
test code context to judge these properly."* hoolint's verdict parser matches
`[N] VIOLATION:` at the start of a line, so a discursive reply matches nothing and
every candidate is dropped. A dropped candidate never blocks, so the failure reads
as a clean check rather than as a judge that did not run.

`openai_route.py` therefore pins the format with `--system-prompt` rather than
trusting each rule's prompt to do it. It also passes `--tools ""` and
`--max-turns 1`: a judge that can read the filesystem could reach past the span it
was asked to rule on.

## Measured result

Running `mock-echo-assert` over structurella and permessa, generator plus judge:

| stage | candidates |
| --- | --- |
| after the three generator filters | 12 |
| confirmed by the judge | 8 |
| cleared by the judge | 4 |

The four it cleared were the two this repo's notes had already marked borderline,
plus two where a sibling `assert_called_once_with` carries the real verification.
That is the judge doing the job the generator cannot.
