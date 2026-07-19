#!/usr/bin/env node
// PreToolUse gate: refuse to stage or commit files that look like secrets.
// ponytail: pattern match on the command string, not on file contents. Ceiling: catches the
// named-file case (`git add .env`), misses a secret pasted inside a normal source file, and
// misses `git add .` sweeping an untracked .env. Upgrade path: run `git diff --cached --name-only`
// after staging, or scan added lines for key-shaped strings.
const fs = require('fs');

let input = {};
try { input = JSON.parse(fs.readFileSync(0, 'utf8') || '{}'); } catch { process.exit(0); }

if (input.tool_name !== 'Bash') process.exit(0);
let cmd = (input.tool_input && input.tool_input.command) || '';
if (!/\bgit\s+(add|commit|stash)\b/.test(cmd)) process.exit(0);

// Commit messages are prose, not paths: `git commit -m "rotate credentials"` must pass.
cmd = cmd.replace(/(?:-m|--message)(?:\s+|=)("[^"]*"|'[^']*')/g, '');

// Secret-shaped paths. `.env.example` and `.env.sample` are conventional templates, not secrets.
const SECRET = /(^|[\s'"/=])(\.env(\.[\w-]+)?|[\w.-]*(id_rsa|id_ed25519|id_ecdsa)[\w.-]*|[\w.-]+\.(pem|key|p12|pfx|jks|keystore)|credentials(\.\w+)?|\.npmrc|\.pypirc|service[-_]account[\w.-]*\.json)(?=$|[\s'"])/gi;
const ALLOWED = /\.(example|sample|template|dist)$/i;

const hits = [...cmd.matchAll(SECRET)].map(m => m[2]).filter(p => !ALLOWED.test(p));
if (!hits.length) process.exit(0);

process.stdout.write(JSON.stringify({
  hookSpecificOutput: {
    hookEventName: 'PreToolUse',
    permissionDecision: 'deny',
    permissionDecisionReason:
      'Blocked: this command stages or commits secret-shaped files (' +
      [...new Set(hits)].join(', ') + '). Never commit .env files, keys, or credentials. ' +
      'Add them to .gitignore, commit a redacted .example instead, and tell the user.',
  },
}));
