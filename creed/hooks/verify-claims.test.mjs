// Run: node --test creed/hooks/verify-claims.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), 'verify-claims.js');
const CLAIM = 'The bug is fixed and all tests pass.';

const user = text => ({ type: 'user', message: { role: 'user', content: text } });
const say = text => ({ type: 'assistant',
  message: { role: 'assistant', content: [{ type: 'text', text }] } });
const bash = command => ({ type: 'assistant',
  message: { role: 'assistant', content: [{ type: 'tool_use', name: 'Bash', input: { command } }] } });

function run(events, extra = {}) {
  const path = join(mkdtempSync(join(tmpdir(), 'creed-')), 't.jsonl');
  writeFileSync(path, events.map(e => JSON.stringify(e)).join('\n') + '\n');
  const r = spawnSync('node', [SCRIPT], { input: JSON.stringify({ transcript_path: path, ...extra }) });
  return r.stdout.toString() ? JSON.parse(r.stdout).decision : 'allow';
}

test('blocks a claim not yet flushed to the transcript (Stop race)', () => {
  assert.equal(run([user('fix it')], { last_assistant_message: CLAIM }), 'block');
});

test('allows a claim backed by a real command this turn', () => {
  assert.equal(run([user('fix it'), bash('npm test')], { last_assistant_message: CLAIM }), 'allow');
});

test('falls back to the transcript when last_assistant_message is absent', () => {
  assert.equal(run([user('fix it'), say(CLAIM)]), 'block');
});

test('allows a message with no claim', () => {
  assert.equal(run([user('hi')], { last_assistant_message: 'Hello.' }), 'allow');
});
