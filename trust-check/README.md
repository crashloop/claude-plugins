# trust-check

A Claude Code plugin that audits a company website from outside, the way a careful buyer
would, and answers one question: **would you trust this site enough to hire its owners, and
what would change your mind?**

New companies appear by the thousand every day, and some of them are fake. A buyer cannot
easily tell an honest new firm with no proof from a fraudulent one. trust-check gathers the
evidence that separates them and hands the owner a ranked list of what to fix.

## Install

```
/plugin install trust-check --marketplace crashloop/claude-plugins
```

## Use

```
/trust-check:trust-check https://example.com
/trust-check:trust-check https://example.com B2B pentest firm selling in Italy
```

Or ask in plain words: "can I trust this vendor's site?", "would a buyer hire these people?".

The run writes `./trust-check-<host>-<date>/` with `report.html`, the evidence and each
analyst's findings.

## What it checks

| Analyst | Model | Question |
|---|---|---|
| tc-content | Opus | What does the page say, is it accurate against its sources, which trust signals exist, how much AI wrote it? |
| tc-reputation | Opus | Search footprint, archive history, name collisions, trademark, domains, handles |
| tc-benchmark | Opus | How 8 to 9 comparable firms prove trust, young firms included |
| tc-blocking | Opus | Will corporate web and mail filters block the site? |
| tc-email | Opus | Will mail from the domain authenticate; can others spoof it? |
| tc-legal | Opus | Mandatory disclosures, privacy notice, consent, advertising rules (not legal advice) |
| tc-market | Opus | Who would buy, at what price, which niche |
| tc-buyers | Opus | Three simulated buyers, cold and referred |
| tc-quality | Sonnet | Mobile, accessibility, speed, conversion tracking |
| tc-code-static | Sonnet | Trackers, hidden content and malware-like code in served files |
| tc-code-thirdparty | Sonnet | What third-party scripts collect; does the privacy notice match? |
| tc-code-runtime | Sonnet | What the page does in a headless browser; cloaking and redirects |

The lead session collects evidence, briefs the analysts in parallel, spot-checks the claims
the verdict rests on, merges duplicates by root cause, writes five persona verdicts
(customer, investor, partner, acquirer, owner) and builds the report. The last section of
the report counts critical, high, medium and low issues per domain: Marketing and SEO, Best
practices, Trust and brand, Legal and compliance, Email and reachability, Security and
privacy.

## Passive by design

Ordinary page loads and public lookups only: no scanning, fuzzing, form submission, login or
email. A fixed list of about fifteen well-known paths is the whole probe budget. Downloads
are read as text and never executed. The browser trace records and aborts analytics
requests, so a check never writes into the owner's statistics. Rules in
[skills/trust-check/references/safety.md](skills/trust-check/references/safety.md).

## Scripts

Standard-library Python, usable on their own:

```sh
S=trust-check/skills/trust-check/scripts
python3 -I $S/collect.py https://example.com ./run          # evidence.json, text/, raw/
python3 -I $S/slop_check.py ./run/raw/pages/index.html      # stop-slop pattern counts
node $S/runtime_trace.js --out ./run/runtime --mobile https://example.com
python3 -I $S/build_report.py ./run/findings.json ./run/report.html
```

`runtime_trace.js` needs `playwright-core` and a Chromium build (`TC_CHROME` overrides the
path). Pillow is optional; with it, screenshots are shrunk and embedded as WebP.

Tests:

```sh
cd trust-check/skills/trust-check/scripts && python3 -m pytest -q
```

## Limits

Severity ratings and persona verdicts are judgments. Legal points are preliminary research.
Many trademark registers and reputation feeds block automated queries; the report lists
each one it could not check, with the manual search link.
