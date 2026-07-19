#!/usr/bin/env node
// ponytail: heuristic gate, not real verification. Ceiling: keyword match on the final
// assistant text + a scan of this turn's events for a real tool_use. Read-only tools and bare
// inspection commands (ls/echo/cat/...) do not count as proof; a chained command does
// (permissive). Upgrade path: extract the claimed check and re-run it instead of proxying on it.
const fs = require('fs');

let input = {};
try { input = JSON.parse(fs.readFileSync(0, 'utf8') || '{}'); } catch { process.exit(0); }

// Block at most once per turn -> no stop-loop.
if (input.stop_hook_active) process.exit(0);

const tpath = input.transcript_path;
if (!tpath || !fs.existsSync(tpath)) process.exit(0);

let events = [];
try {
  events = fs.readFileSync(tpath, 'utf8').split('\n').filter(Boolean)
    .map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
} catch { process.exit(0); }
if (!events.length) process.exit(0);

const textOf = ev => {
  const c = ev.message && ev.message.role === 'assistant' && ev.message.content;
  if (typeof c === 'string') return c;
  if (Array.isArray(c)) return c.filter(b => b && b.type === 'text').map(b => b.text).join(' ');
  return '';
};
let lastText = '';
for (let i = events.length - 1; i >= 0; i--) {
  const t = textOf(events[i]);
  if (t && t.trim()) { lastText = t; break; }
}
if (!lastText) process.exit(0);

const CLAIM = /\b(it works now|now works|works now|is fixed|is done|it'?s fixed|it'?s done|should be fixed|the fix works|tests? (now )?pass(es|ing)?|all (tests? )?(green|passing)|bug is (fixed|resolved)|done and verified)\b/i;
if (!CLAIM.test(lastText)) process.exit(0);

// Proof = a real tool_use this turn. Read-only tools verify nothing; a Bash command that is
// purely trivial inspection is discounted; a chained command (|, &&, ;) is assumed to do
// real work.
const TRIVIAL = /^\s*(ls|echo|pwd|cat|which|type|head|tail|true|:)\b/;
const READONLY = new Set(['Read', 'Glob', 'Grep', 'TodoWrite']);
const isEvidence = ev => {
  const c = ev.message && ev.message.content;
  if (!Array.isArray(c)) return false;
  return c.some(b => {
    if (!b || b.type !== 'tool_use') return false;
    if (READONLY.has(b.name)) return false;
    if (b.name !== 'Bash') return true;
    const cmd = (b.input && b.input.command) || '';
    return /[|;&]/.test(cmd) || !TRIVIAL.test(cmd);
  });
};

// Scope the scan to the current turn: everything after the last real user message.
// Tool results also arrive as role "user"; those carry tool_result blocks, so skip them.
let turnStart = 0;
for (let i = events.length - 1; i >= 0; i--) {
  const m = events[i].message;
  if (!m || m.role !== 'user') continue;
  const c = m.content;
  if (Array.isArray(c) && c.some(b => b && b.type === 'tool_result')) continue;
  turnStart = i + 1;
  break;
}
if (events.slice(turnStart).some(isEvidence)) process.exit(0);

process.stdout.write(JSON.stringify({
  decision: 'block',
  reason: 'Operating Core #5 (attack your own conclusion): you claimed the work is ' +
    'done/fixed/passing but ran no command this turn. Produce the evidence a skeptic would ' +
    'demand -- run the check (test, request, query) and show its output -- or restate the ' +
    'conclusion as unverified and name what remains unchecked.'
}));
process.exit(0);
