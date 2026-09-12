import type { Register, RenderElement } from 'claude-code'

type Option = { label: string; description?: string }
type Question = {
  id: string
  label: string
  type: 'single' | 'multi' | 'text'
  options?: (string | Option)[]
  recommended?: string
  hint?: string
  showWhen?: { id: string; eq: string }
}
type Answers = Record<string, string | string[]>
type Form = { title: string; questions: Question[]; answers: Answers }

const TOOL_PATTERN = /^mcp__ask-all__ask$/
const OPTION_SCHEMA = {
  anyOf: [
    { type: 'string' },
    {
      type: 'object',
      required: ['label'],
      properties: { label: { type: 'string' }, description: { type: 'string' } },
    },
  ],
}
const SPEC = {
  name: 'ask',
  description:
    'Ask the user several questions at once in one form drawn above the prompt. ' +
    'Use instead of repeated AskUserQuestion calls when 3+ independent decisions are open. ' +
    'Each question: id, label, type (single|multi|text), options (single/multi: strings or ' +
    '{label, description} where description states the trade-off), recommended (single: ' +
    'preselected label), hint, showWhen {id, eq} to reveal it only after a parent answer. ' +
    'The call returns at once; the answers arrive as the NEXT USER MESSAGE as JSON {id: answer}. ' +
    'After calling, end your turn and wait. Do not ask the same questions again.',
  inputSchema: {
    type: 'object',
    required: ['questions'],
    properties: {
      title: { type: 'string' },
      questions: {
        type: 'array',
        minItems: 1,
        items: {
          type: 'object',
          required: ['id', 'label', 'type'],
          properties: {
            id: { type: 'string' },
            label: { type: 'string' },
            type: { type: 'string', enum: ['single', 'multi', 'text'] },
            options: { type: 'array', items: OPTION_SCHEMA },
            recommended: { type: 'string' },
            hint: { type: 'string' },
            showWhen: {
              type: 'object',
              required: ['id', 'eq'],
              properties: { id: { type: 'string' }, eq: { type: 'string' } },
            },
          },
        },
      },
    },
  },
}

const optionsOf = (q: Question): Option[] =>
  (q.options ?? []).map(o => (typeof o === 'string' ? { label: o } : o))
const isShown = (q: Question, a: Answers) => !q.showWhen || a[q.showWhen.id] === q.showWhen.eq

export const register: Register = on => {
  let host: { invalidate: () => void; submit: (text: string) => Promise<unknown> } | null = null
  let form: Form | null = null

  on('session.start', async ($, e, next) => {
    host = { invalidate: () => $.ui.invalidate('ui.render'), submit: text => $.prompt.submit({ text }) }
    await $.tool.register(SPEC)
    return next(e)
  })

  // A tool.call hook cannot wait for a human (its budget expires at once), so
  // the call returns immediately and Submit hands the answers over as a prompt.
  on('tool.call', { tool: TOOL_PATTERN }, ($, e) => {
    const input = e as unknown as { title?: string; questions: Question[] }
    const answers: Answers = {}
    for (const q of input.questions) if (q.type === 'single' && q.recommended) answers[q.id] = q.recommended
    form = { title: input.title ?? 'Questions', questions: input.questions, answers }
    $.ui.invalidate('ui.render')
    return {
      result:
        'Form is open above the prompt. End your turn now and wait: the answers arrive as the ' +
        'next user message as JSON. Do not ask these questions again.',
    }
  })

  function submit() {
    const f = form
    if (!f || !host) return
    form = null
    host.invalidate()
    void host.submit(`Answers to "${f.title}":\n\`\`\`json\n${JSON.stringify(f.answers, null, 2)}\n\`\`\``)
  }

  // ponytail: terminal band only; desktop needs a Pane hook, mobile has no Input.
  on('ui.render', { component: 'AbovePrompt' }, ($, e, next) => {
    if (!form || e.surface !== 'terminal' || e.props.hasSurvey) return next(e)
    const f = form
    const { Box, Text, Button, Input } = $.ui.resolve(e)
    const redraw = () => $.ui.invalidate('ui.render')

    const optionRows = (q: Question) =>
      optionsOf(q).map(o => {
        const isMulti = q.type === 'multi'
        const picked = isMulti
          ? ((f.answers[q.id] as string[] | undefined) ?? []).includes(o.label)
          : f.answers[q.id] === o.label
        const mark = isMulti ? (picked ? '[x]' : '[ ]') : picked ? '(*)' : '( )'
        const rec = o.label === q.recommended ? ' (recommended)' : ''
        return h(Box, { flexDirection: 'row', gap: 1 },
          h(Button, {
            key: `${q.id}:${o.label}`,
            label: `${mark} ${o.label}${rec}`,
            onPress: () => {
              if (isMulti) {
                const set = new Set((f.answers[q.id] as string[] | undefined) ?? [])
                set.has(o.label) ? set.delete(o.label) : set.add(o.label)
                f.answers[q.id] = [...set]
              } else f.answers[q.id] = o.label
              redraw()
            },
          }),
          o.description ? h(Text, { dimColor: true, wrap: 'wrap' }, o.description) : null)
      })

    const rows = f.questions.filter(q => isShown(q, f.answers)).map(q =>
      h(Box, { flexDirection: 'column' },
        h(Text, { bold: true }, q.label,
          q.hint && q.type !== 'text' ? h(Text, { dimColor: true, bold: false }, `  ${q.hint}`) : null),
        ...(q.type === 'text'
          ? [h(Input, {
              key: q.id,
              placeholder: q.hint,
              value: f.answers[q.id] as string | undefined,
              onInput: (v: string) => { f.answers[q.id] = v },
              onSubmit: (v: string) => { f.answers[q.id] = v; redraw() },
            })]
          : optionRows(q))))

    return h(Box, { flexDirection: 'column', gap: 1 },
      h(Text, { bold: true, underline: true }, f.title),
      ...rows,
      h(Button, { key: 'submit', label: 'Submit answers', onPress: submit })) as RenderElement
  })
}
