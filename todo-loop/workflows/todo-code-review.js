// @ts-nocheck — workflow script: runs in the Workflow runtime's async wrapper with
// injected globals (agent/pipeline/parallel/phase/args) and a top-level return; not a TS module.
export const meta = {
  name: 'todo-code-review',
  description: 'Multi-persona code review of a change with adversarial verification of every finding before it is reported',
  phases: [
    { title: 'Review', detail: 'one persona per dimension (correctness, security, perf, simplicity, architecture, tests)' },
    { title: 'Verify', detail: 'independent skeptics confirm or refute each finding against the real code' },
    { title: 'Synthesize', detail: 'filter to confirmed findings, dedup, prioritize into a fix list' },
  ],
}

// args: { scope?: string, baseline?: string, item?: string, principleFiles?: string[], repoDir?: string,
//         personas?: string[] }  // subset of persona keys to run (default: all six)
// baseline = a git ref/sha captured before this item started (e.g. from `git stash create`),
// so the review sees ONLY this item's diff and not prior uncommitted items.
// repoDir = the repo the code actually lives in. For a monorepo whose code sits in a git
// SUBMODULE, the baseline is a submodule commit and the diff MUST run there (`git -C <repoDir>`),
// not in the superrepo — otherwise the diff silently targets the wrong tree.
const repoDir = (args && args.repoDir) || '.'
const gitC = repoDir === '.' ? 'git' : `git -C "${repoDir}"`
const baseline = (args && args.baseline) || ''
const scope = (args && args.scope) ||
  (baseline
    ? `this item's change ONLY, in the repo at ${repoDir} (use absolute paths under it for every file read). ` +
      `Run \`${gitC} --no-pager diff ${baseline}\` for modified tracked files. CRITICAL: a NEW package is almost ` +
      `entirely UNTRACKED, so a diff alone shows nothing — you MUST also run \`${gitC} status --porcelain\` and ` +
      `READ every new/untracked file added since the baseline. Review both.`
    : `the working-tree change in the repo at ${repoDir}: run \`${gitC} --no-pager diff HEAD\` AND ` +
      `\`${gitC} status --porcelain\`, then READ new/untracked files (a new package appears only as untracked).`)
const item = (args && args.item) || 'the in-progress change (identify it from the diff/status)'
const principleFiles = (args && args.principleFiles) || ['CLAUDE.md']
// Reviewers run as Explore agents (no CLAUDE.md injection), so they read the principle files
// themselves; project conventions (docs/conventions.md when present) are consulted per persona,
// not read whole — that file is the bulk of the old payload.
const MAX_FINDINGS_PER_PERSONA = (args && args.maxFindings) || 5
const SEV_RANK = { blocker: 0, major: 1, minor: 2, nit: 3 }

const personaKeys = (args && args.personas) || null
const ALL_PERSONAS = [
  { key: 'correctness', focus: 'logic bugs, wrong assumptions, unhandled edge cases, error handling, off-by-one, race conditions, broken invariants the codebase declares (docstrings, model comments, ADRs)' },
  { key: 'security', focus: 'OWASP Top 10: injection, broken object-level authorization, missing input sanitization, leaked secrets/stack traces, SSRF, insecure direct object refs, signed-URL/token bypass' },
  { key: 'performance', focus: 'N+1 queries, unbounded loops/allocations, blocking I/O on hot paths, missing timeouts/retries/circuit breakers on I/O' },
  { key: 'simplicity', focus: 'KISS/DRY/SSOT/YAGNI violations, duplicated logic, dead code introduced by this change, needless ceremony, missed library-first reuse of existing deps and shared code' },
  { key: 'architecture', focus: 'cohesion vs fragmentation, composition over inheritance, dependency inversion (ports + Fake/Noop), correct layering, size smells (>500-line files, >50-line funcs, >200-line classes)' },
  { key: 'tests', focus: 'asserts behaviour not implementation, stable testIDs/data-testids preserved, the change is actually covered, no fragile CSS/structure assertions, scoped tests exist for changed units' },
]
const PERSONAS = personaKeys ? ALL_PERSONAS.filter(p => personaKeys.includes(p.key)) : ALL_PERSONAS
if (!PERSONAS.length) throw new Error(`no personas match ${JSON.stringify(personaKeys)}; valid: ${ALL_PERSONAS.map(p => p.key).join(', ')}`)

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'nit'] },
          location: { type: 'string', description: 'file:line of the problem' },
          title: { type: 'string' },
          detail: { type: 'string', description: 'what is wrong and why' },
          fix: { type: 'string', description: 'concrete change to make' },
        },
        required: ['severity', 'location', 'title', 'detail', 'fix'],
      },
    },
  },
  required: ['findings'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    confirmed: { type: 'boolean', description: 'true only if the finding is real and reproducible in the actual code' },
    reason: { type: 'string' },
  },
  required: ['confirmed', 'reason'],
}

const SUMMARY_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    blockers: { type: 'array', items: { type: 'string' } },
    fixes: {
      type: 'array',
      description: 'prioritized, deduplicated fixes for the implementer',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'nit'] },
          location: { type: 'string' },
          change: { type: 'string' },
          principle: { type: 'string' },
        },
        required: ['severity', 'location', 'change'],
      },
    },
  },
  required: ['blockers', 'fixes'],
}

// Pipeline: each persona's findings are verified as soon as that persona finishes —
// no barrier, so a slow dimension never blocks verification of a fast one.
const reviewed = await pipeline(
  PERSONAS,
  persona => agent(
    `You are a strict ${persona.key} code reviewer for ${item}.\n` +
      `Read the project principles first (${principleFiles.join(', ')}); if docs/conventions.md exists, ` +
      `grep it for the rules relevant to this dimension instead of reading it whole.\n` +
      `Review ${scope}.\n` +
      `Focus exclusively on: ${persona.focus}.\n` +
      `Report only real, actionable findings, each with an exact file:line. Do NOT edit any file.\n` +
      `If nothing is wrong on this dimension, return an empty findings array.`,
    { label: `review:${persona.key}`, phase: 'Review', schema: FINDINGS_SCHEMA, agentType: 'Explore',
      model: 'sonnet', effort: 'medium' },
  ),
  // Cap the verify fan-out: nits are never worth a verifier, and a chatty persona is bounded
  // to its top-N by severity. Dropped findings are logged, never silently lost.
  (review, persona) => {
    const all = (review && review.findings ? review.findings : [])
    const kept = all
      .filter(f => f.severity !== 'nit')
      .sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity])
      .slice(0, MAX_FINDINGS_PER_PERSONA)
    if (kept.length < all.length) log(`${persona.key}: verifying ${kept.length}/${all.length} findings (nits + overflow dropped)`)
    return parallel(kept.map(f => () =>
    agent(
      `Adversarially verify a ${persona.key} review finding. Default to confirmed=false unless you can ` +
        `confirm it against the actual code. Read the cited location and surrounding context before deciding.\n` +
        `Location: ${f.location}\nTitle: ${f.title}\nClaim: ${f.detail}\nProposed fix: ${f.fix}`,
      { label: `verify:${f.location}`, phase: 'Verify', schema: VERDICT_SCHEMA, agentType: 'Explore', effort: 'low' },
    ).then(v => ({ ...f, persona: persona.key, verdict: v })),
  ))
  },
)

const confirmed = reviewed
  .flat()
  .filter(Boolean)
  .filter(f => f.verdict && f.verdict.confirmed)

phase('Synthesize')
// ponytail: <=3 findings need no dedup agent — map them straight into the summary shape.
const summary = confirmed.length <= 3
  ? {
      blockers: confirmed.filter(f => f.severity === 'blocker').map(f => f.title),
      fixes: confirmed
        .slice()
        .sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity])
        .map(f => ({ severity: f.severity, location: f.location, change: `${f.title}: ${f.fix}` })),
    }
  : await agent(
      `Synthesize these CONFIRMED code-review findings into one deduplicated, prioritized fix list for the implementer ` +
        `of ${item}. Merge overlapping findings. Order by severity (blocker > major > minor > nit). Each fix must name a ` +
        `file:line and the concrete change. List any blocker titles separately.\n` +
        `Confirmed findings JSON:\n${JSON.stringify(confirmed, null, 2)}`,
      { label: 'synthesize', schema: SUMMARY_SCHEMA, effort: 'low' },
    )

return {
  verifiedCount: reviewed.flat().filter(Boolean).length,
  confirmedCount: confirmed.length,
  findings: confirmed,
  summary,
}
