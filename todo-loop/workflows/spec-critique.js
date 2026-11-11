// @ts-nocheck — workflow script: runs in the Workflow runtime's async wrapper with
// injected globals (agent/parallel/phase/args) and a top-level return; not a TS module.
export const meta = {
  name: 'spec-critique',
  description: 'Critique a TODO-item plan from several independent angles, then synthesize a prioritized revision list',
  phases: [
    { title: 'Critique', detail: 'one reviewer per lens (principles, simplicity, testability, domain, gaps, grounding; frontend-ssot opt-in)' },
    { title: 'Synthesize', detail: 'dedup and prioritize into a single actionable revision list' },
  ],
}

// args: { planPath: string, item?: string, principleFiles?: string[],
//         lenses?: string[] }  // subset of lens keys to run (default: all but opt-in ones)
// NOTE: in some launch paths `args` does not bind (e.g. a named-workflow launch),
// so degrade gracefully instead of hard-throwing — tell the agents to locate the
// in-progress plan themselves (the workflow script has no filesystem access; only
// the Explore agents can read files).
const planPath = (args && args.planPath) ||
  'AUTO — locate the plan yourself: the most recently modified file matching docs/plans/*-todo-loop/NN-*.md ' +
  'whose checklist line "2. [ ] Spec critiqued" is still UNTICKED. Read that file before critiquing.'
const item = (args && args.item) || 'the in-progress backlog item (identify it from the plan you locate)'
const principleFiles = (args && args.principleFiles) ||
  ['CLAUDE.md (or AGENTS.md when CLAUDE.md is absent)', '~/.claude/CLAUDE.md if it exists']

const lensKeys = (args && args.lenses) || null
const ALL_LENSES = [
  {
    key: 'principles',
    focus: 'compliance with the project Core Principles: library-first (check existing deps and shared code ' +
      'before custom), KISS/DRY/SSOT, dependency inversion (heavy collaborators behind ports with a Fake/Noop), ' +
      'structured errors, fail-fast, composition over inheritance, and any invariants the project docs declare',
  },
  {
    key: 'simplicity',
    focus: 'YAGNI and over-engineering: needless abstraction, speculative generality, ceremony that adds no value; ' +
      'the simplest design that satisfies the item',
  },
  {
    key: 'testability',
    focus: 'Design-for-Testability and TDD: is the behaviour stated as testable assertions? are pure-logic units ' +
      'separable from thin IO shells? are stable testIDs/data-testids specified (never removed citing YAGNI)?',
  },
  {
    key: 'domain',
    focus: 'domain non-negotiables the project itself declares as mandatory (read CLAUDE.md and docs/conventions.md, ' +
      'and any strategy or ADR docs — compliance, security, and product constraints named there). ' +
      'Flag any that the item touches but does not honor; skip if the project declares none',
  },
  {
    key: 'gaps',
    focus: 'missing scope, unhandled edge cases, ambiguous acceptance criteria, undocumented decisions or deferrals, ' +
      'and unstated assumptions that should be surfaced rather than resolved silently',
  },
  {
    key: 'grounding',
    focus: 'validate the plan against the ACTUAL codebase, not just internal consistency. READ the real code ' +
      '(use a code-graph or symbol-search tool if one is available, otherwise grep/read) and flag every assumption the plan ' +
      'makes that the codebase contradicts or does not support: cited file paths that do not exist, functions/' +
      'classes/symbols referenced that are absent or have a different signature, API/serializer/endpoint shapes ' +
      'that differ from the real server contract, existing patterns the plan misdescribes, and any existing ' +
      'library or shared-code capability the plan reinvents instead of reusing. A plan that references a path, symbol, or contract that ' +
      'does not resolve in the real code is a blocker — name the exact mismatch and the real shape',
  },
  {
    key: 'frontend-ssot',
    optIn: true, // monorepo/frontend-specific: runs only when named in args.lenses
    focus: 'for frontend items ONLY (skip if backend-only): (1) cross-package imports of RUNTIME VALUES ' +
      '(error classes, constants) — importing a value from a package barrel that re-exports heavy UI modules ' +
      'drags the whole UI framework into the importer\'s tests and breaks them; shared runtime values must ' +
      'come from a framework-free package (the repo\'s canonical shared/errors package, if one exists). ' +
      '(2) client request/response types and validation must MIRROR the verified server contract (SSOT) — never ' +
      'invent an endpoint or auth model; check the real server code. (3) money/number/date formatting must ' +
      'reuse the repo\'s shared formatters, not a second copy. (4) stable testIDs are specified for every component.',
  },
]
const LENSES = lensKeys ? ALL_LENSES.filter(l => lensKeys.includes(l.key)) : ALL_LENSES.filter(l => !l.optIn)
const unknownLenses = (lensKeys || []).filter(k => !ALL_LENSES.some(l => l.key === k))
if (unknownLenses.length) log(`ignoring unknown lenses: ${unknownLenses.join(', ')}`)
if (!LENSES.length) throw new Error(`no lenses match ${JSON.stringify(lensKeys)}; valid: ${ALL_LENSES.map(l => l.key).join(', ')}`)

const CRITIQUE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'nit'] },
          title: { type: 'string' },
          detail: { type: 'string' },
          principle: { type: 'string', description: 'the principle or constraint at stake, if any' },
          suggestion: { type: 'string', description: 'concrete revision to the plan' },
        },
        required: ['severity', 'title', 'detail', 'suggestion'],
      },
    },
  },
  required: ['lens', 'findings'],
}

const SYNTHESIS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    mustFix: {
      type: 'array',
      description: 'blocking/major revisions to fold into the plan before any code',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          title: { type: 'string' },
          change: { type: 'string' },
          rationale: { type: 'string' },
        },
        required: ['title', 'change', 'rationale'],
      },
    },
    optional: {
      type: 'array',
      description: 'minor/nit improvements the implementer may take or defer with a logged note',
      items: { type: 'string' },
    },
    openQuestions: {
      type: 'array',
      description: 'genuine ambiguities the plan cannot resolve without a human decision',
      items: { type: 'string' },
    },
  },
  required: ['mustFix', 'optional', 'openQuestions'],
}

const critiques = await parallel(LENSES.map(lens => () =>
  agent(
    `You are a strict plan reviewer working the "${lens.key}" lens for ${item}.\n` +
      `Read the project principles first (${principleFiles.join(', ')}), then read the plan at ${planPath}. ` +
      `If docs/conventions.md exists, grep it for rules relevant to this lens instead of reading it whole.\n` +
      `Critique ONLY through this lens: ${lens.focus}.\n` +
      `Report concrete, actionable findings tied to specific sections of the plan. Do NOT edit any file.\n` +
      `If the plan is sound on this lens, return an empty findings array.`,
    { label: `critique:${lens.key}`, phase: 'Critique', schema: CRITIQUE_SCHEMA, agentType: 'Explore',
      model: 'sonnet', effort: 'medium' },
  ),
))

// A lens agent that dies returns null. Record it so a failed critique never reads as a clean one.
const failedLenses = LENSES.filter((l, i) => !critiques[i]).map(l => l.key)
if (failedLenses.length === LENSES.length) {
  throw new Error(`every lens failed (${failedLenses.join(', ')}); the plan is NOT critiqued`)
}
const allFindings = critiques.flatMap((c, i) =>
  c ? (c.findings || []).map(f => ({ ...f, lens: LENSES[i].key })) : [])

phase('Synthesize')
// ponytail: zero findings need no synthesis agent. Non-empty sets keep it — the
// mustFix/optional/openQuestions classification is judgment, not a mechanical map.
const revision = allFindings.length === 0
  ? { mustFix: [], optional: [], openQuestions: [] }
  : await agent(
      `Synthesize these plan-critique findings into one deduplicated, prioritized revision list for ${item}.\n` +
        `Merge overlapping findings across lenses. Separate blocking/major changes (mustFix) from minor/nit (optional).\n` +
        `Put only genuine human-decision ambiguities in openQuestions — do not invent blockers.\n` +
        `Findings JSON:\n${JSON.stringify(allFindings, null, 2)}`,
      { label: 'synthesize', schema: SYNTHESIS_SCHEMA, effort: 'low' },
    )

return {
  planPath,
  totalFindings: allFindings.length,
  failedLenses,
  revision,
}
