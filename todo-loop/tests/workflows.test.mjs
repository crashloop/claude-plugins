// Runs both workflow scripts against stubbed Workflow globals. Usage: node tests/workflows.test.mjs
import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'

const dir = new URL('../workflows/', import.meta.url)
const AsyncFn = Object.getPrototypeOf(async () => {}).constructor

// Wraps a script body in the runtime's shape: injected globals, top-level return allowed.
function load(name) {
  const src = readFileSync(new URL(name, dir), 'utf8').replace(/^export const meta/m, 'const meta')
  const fn = new AsyncFn('args', 'agent', 'parallel', 'pipeline', 'phase', 'log', src)
  return (args, agent) => {
    const logs = []
    const parallel = fns => Promise.all(fns.map(f => f()))
    const pipeline = (items, a, b) => Promise.all(items.map(async x => b(await a(x), x)))
    return fn(args, agent, parallel, pipeline, () => {}, m => logs.push(m)).then(r => ({ r, logs }))
  }
}

const review = load('code-review.js')
const critique = load('spec-critique.js')
const finding = { severity: 'major', location: '/r/a.py:1', title: 't', detail: 'd', fix: 'f' }

// Every reviewer dead -> throw, never an empty "clean" result.
await assert.rejects(review({ baseline: 'abc' }, async () => null), /every reviewer failed/)
await assert.rejects(critique({ planPath: '/p.md' }, async () => null), /every lens failed/)

// One reviewer dead -> named in failedPersonas; a dead verifier -> unverified, not refuted.
{
  const { r } = await review({ baseline: 'abc', repoDir: '/r' }, async (prompt, o) => {
    if (o.label === 'review:security') return null
    if (o.phase === 'Review') return { findings: o.label === 'review:correctness' ? [finding] : [] }
    if (o.phase === 'Verify') {
      assert.match(prompt, /repo at \/r/)
      return null
    }
  })
  assert.deepEqual(r.failedPersonas, ['security'])
  assert.equal(r.unverified.length, 1)
  assert.equal(r.confirmedCount, 0)
}

// Untracked files are listed per file, not collapsed per directory.
{
  const prompts = []
  await review({ baseline: 'abc' }, async (p, o) => { prompts.push(p); return { findings: [] } })
  assert.ok(prompts.every(p => p.includes('--untracked-files=all')))
}

// Missing baseline is logged; unknown personas are logged.
{
  const { logs } = await review({ personas: ['correctness', 'test'] }, async () => ({ findings: [] }))
  assert.ok(logs.some(l => /no baseline/.test(l)))
  assert.ok(logs.some(l => /unknown personas: test/.test(l)))
}

// frontend-ssot is opt-in; lens keys come from the script, not the model.
{
  const labels = []
  const { r } = await critique({ planPath: '/p.md' }, async (p, o) => {
    labels.push(o.label)
    if (o.label === 'synthesize') return { mustFix: [], optional: [], openQuestions: [] }
    return { lens: 'whatever', findings: o.label === 'critique:gaps' ? [{ ...finding, suggestion: 's' }] : [] }
  })
  assert.ok(!labels.includes('critique:frontend-ssot'))
  assert.deepEqual(r.failedLenses, [])
  const { r: r2 } = await critique({ planPath: '/p.md', lenses: ['frontend-ssot'] }, async () =>
    ({ lens: 'x', findings: [] }))
  assert.equal(r2.totalFindings, 0)
}

console.log('workflows: all checks passed')
