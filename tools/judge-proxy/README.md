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

**It does not belong in the Stop hook.** Measured on this machine, one judging
prompt costs 15.7s to 34.4s. That is the wrong order of magnitude for something
that runs when the model stops. Use it in git mode, in CI, and for measuring rule
precision. For session mode use the `escalate` stage instead, which costs nothing
extra because the session model is already running.

## Run it

```bash
uv sync
uv run uvicorn app:app --port 11435
```

Port 11435 rather than 11434, so it never collides with a real Ollama.

Then point a rule at it. Note the timeout: hoolint defaults to 30s and a judged
call here regularly exceeds that, which surfaces as `local_llm skipped (endpoint
unreachable)` and demotes the rule to advisory.

```toml
[[rule.stage]]
strategy = "local_llm"
op = "and"
model = "qwen3:4b"          # ignored unless it names a Claude model
base_url = "http://localhost:11435/v1"
timeout = 240
```

| env var | default | meaning |
| --- | --- | --- |
| `JUDGE_PROXY_MODEL` | `haiku` | model used when the request does not name a Claude one |
| `JUDGE_PROXY_TIMEOUT` | `120` | seconds before the subprocess is killed |

## Why the route enforces an output format

Asked to judge without instruction, the CLI answers in prose: *"I need to see the
test code context to judge these properly."* hoolint's verdict parser matches
`[N] VIOLATION:` at the start of a line, so a discursive reply matches nothing and
every candidate is dropped. A dropped candidate never blocks, so the failure reads
as a clean check rather than as a judge that did not run.

`openai_route.py` therefore pins the format with `--append-system-prompt` rather
than trusting each rule's prompt to do it. It also passes `--allowed-tools ""` and
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
