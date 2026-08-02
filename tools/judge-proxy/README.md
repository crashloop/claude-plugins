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
| `JUDGE_PROXY_SPARES` | `4` | warm processes parked, 0 disables prewarming |
| `JUDGE_PROXY_MAX_INFLIGHT` | `8` | processes allowed in flight; excess requests queue |

`pyproject.toml` diverges from upstream `llm-faker` by two dev dependencies
(`pytest`, `pytest-asyncio`) and a `[tool.pytest.ini_options]` section. That is
deliberate, so the next person diffing the fork does not undo it.

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

## How the warm pool works

Each request gets a process that has never seen another file's verdicts, but not
one it had to wait for. A `claude -p` in `--input-format stream-json` mode boots
and then sits idle until a prompt arrives, so the proxy parks exactly one booted
spare, hands it over when a request lands, kills it afterwards, and boots the
next. A plain `-p` pipe cannot be prewarmed: it starts work only when stdin
closes.

Spares are keyed by `(model, thinking)`, because a request can only reuse a
process booted the way it wants. `JUDGE_PROXY_SPARES` caps how many are parked
(default 4, oldest evicted first, 0 turns prewarming off). A request takes the
first live spare matching its key or boots its own, and warms a replacement for
that key after answering, so within a rule only the first file pays a boot.
`JUDGE_PROXY_MAX_INFLIGHT` (default 8) separately caps requests being served at
once, since each holds a process of roughly 277MB and the parked cap says
nothing about peak. It sits above hoolint's 4-thread ceiling, so it never
engages for the real caller. Replacement spares boot outside that limit, so the
true ceiling is about `2 * MAX_INFLIGHT + SPARES` processes, not `MAX_INFLIGHT`.

Shutdown waits for prewarms still booting before it kills the pool. Without
that wait a spare lands in a pool nobody empties again and the CLI outlives the
server.

One slot was right while `verbose-comments` was the only `local_llm` rule. With
several rules judging at once, a mismatched key was killed on take and rebooted
for the key just served, so alternating rules paid a boot every request.

Measured with `bench_pool.py 4`, two rounds of four concurrent judgments, load
average 2.8 to 3.2, scoring the second round only:

| parked spares | round 2 latencies | served warm | median / 1-request baseline |
| --- | --- | --- | --- |
| 1 (the old single slot) | 3.9s, 2.7s, 7.3s, 4.0s | 1 of 4 | 1.31x |
| 4 (default) | 2.6s, 3.4s, 2.4s, 2.8s | 4 of 4 | 0.89x |

The baseline was 3.0s in both sessions. Re-run the probe rather than trusting
these figures: every number in this tool has moved with box load.

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
