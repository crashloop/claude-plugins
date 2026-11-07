---
name: trust-check
description: Audit a company website from outside, the way a careful buyer would, and produce one HTML report on its message, trustworthiness, reputation, code safety (trackers, spyware, malware-like code), email reachability, legal gaps, market fit and AI involvement, with persona verdicts and issue counts by domain. Use when the user asks whether a site or startup can be trusted, whether a buyer would hire its owners, to vet a vendor, supplier or acquisition target, or to "trust-check" a URL.
argument-hint: <url> [context, e.g. "B2B pentest firm, Italian market"]
---

# trust-check

Runs a passive, outside-in audit of one website with a team of analysts and merges their
findings into a single self-contained HTML report. The question it answers: **would a careful
buyer trust this site enough to hire its owners, and what would change their mind?**

Read `references/safety.md` before starting and pass its rules to every analyst. Read
`references/rubric.md` for severity, domains and both JSON schemas.

## Inputs

- `URL` (required), with scheme.
- Optional context from the user: market, audience, what the company sells, worries such as
  "many new startups are fictitious". Pass it verbatim to every analyst.
- `RUN`: `./trust-check-<host>-<YYYY-MM-DD>/` in the working directory unless the user names
  another folder. `SCRIPTS`: this skill's `scripts/` directory, as an absolute path.

## Step 1: collect evidence (you)

```bash
python3 -I "$SCRIPTS/collect.py" "$URL" "$RUN"
```

This writes `RUN/evidence.json` (pages, assets with hashes and file signatures, third-party
scripts saved as text, headers, probes, cloaking variants, DNS, whois, web archive) plus
`RUN/text/*.txt` (visible text per page) and `RUN/raw/` (downloads, never executed).
Read the summary line and skim `evidence.json` so you can brief analysts precisely.

If a browser tool is available, take a full-page desktop screenshot and a 390 by 844 phone
screenshot of the homepage now, saved where that tool allows, and note their absolute paths.

## Step 2: fan out the analysts (one message)

Tell the user in one line what you are launching (12 analysts: 9 on Opus, 3 on Sonnet). Then
send every Agent call in a single message so they run in parallel. Use
`subagent_type: "trust-check:<name>"`:

| Agent | Question it answers |
|---|---|
| `tc-content` | What does the page say, is it accurate against its own sources, which trust signals exist, and how much AI wrote it (runs `slop_check.py`)? |
| `tc-reputation` | What does the web say about the company and name: search footprint, archive history, name collisions, trademark, domains, handles? |
| `tc-benchmark` | How do 8 to 9 comparable firms prove trust, and where does this site fall short? |
| `tc-blocking` | Will corporate web and mail filters block the site or its mail (reputation feeds, new-domain windows, category risk)? |
| `tc-email` | Will mail from the site's domain authenticate and reach inboxes? |
| `tc-quality` | Mobile rendering, accessibility, speed, and whether the conversion is measured. Owns the browser tool. |
| `tc-legal` | Which mandatory disclosures, privacy and advertising rules apply, and which are missing? |
| `tc-market` | Who would buy this, at what price, and which niche gives the best chance? |
| `tc-buyers` | How do three simulated buyers react, cold and referred? Brief it with the page only, not your view. |
| `tc-code-static` | Do the served files contain trackers, hidden content or malware-like code? |
| `tc-code-thirdparty` | What do the third-party scripts collect, and does the privacy notice match? |
| `tc-code-runtime` | What does the page do at run time, and does it cloak? Runs `runtime_trace.js`. |

Every brief contains: `URL`, `RUN`, `SCRIPTS`, the user's context, the path to
`evidence.json`, the facts from Step 1 that analyst needs (quote them; do not make it
re-derive them), the safety rules, and this contract:

> Write your findings to `RUN/findings/<your agent name>.json` following
> `SCRIPTS/../references/rubric.md` ("Analyst output"). Reply with at most 150 words: your
> verdict, the file path, and anything the lead must verify. Do not paste the findings.

Never hand an analyst your hypothesis to confirm. `tc-buyers` in particular gets the page,
the screenshots and the checkable facts only.

## Step 3: check the analysts' work (you)

As each analyst finishes, confirm its file parses:

```bash
python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['verdict'], len(d['issues']))" "$RUN/findings/tc-email.json"
```

If a file is missing or invalid, message that analyst (SendMessage, by name) to write it;
do not rerun the analysis yourself. Then:

- **Spot-check the claims the verdict rests on**: two or three numbers or facts per analyst
  that carry a recommendation. Re-run the command or open the source. Record what you
  confirmed and what you could not.
- **Run what analysts could not**: when a browser tool is free and the EU or national
  trademark registers were unreachable, search WIPO's Global Brand Database
  (`https://branddb.wipo.int/`) for the exact name and a fuzzy variant.
- **Reconcile conflicts** between analysts and note every correction for the report.

## Step 4: merge into `RUN/findings.json` (you)

Follow the report schema in `references/rubric.md`:

1. **Sections**, in this order, from the analysts' blocks: page at a glance (with
   `"screenshots": true`), message and conversion, content accuracy, trust signals,
   reputation and name, competitor benchmark, AI involvement, code safety, mobile and
   accessibility and tracking, email and reachability, legal and compliance, market and
   positioning, action plan. Edit for one voice; cut repetition between sections.
2. **Issues**: pool every analyst's issues, merge duplicates by root cause, set severities
   with the rubric, assign ids. Counts are computed by the builder; never write them by hand.
3. **Personas**: write the five verdicts yourself from the merged findings (rubric,
   "Personas"). Put the `tc-buyers` grid in the customer card.
4. **Summary**: the answer in one sentence, then four to six bullets. Lead with what the user
   asked.
5. **Action plan**: this week, before outreach, before the first engagement; include copyable
   DNS records and markup from the analysts as `code` blocks.
6. **Limits**, **corrections** and **sources** from all analysts, deduplicated.

## Step 5: build and check the report (you)

```bash
python3 -I "$SCRIPTS/build_report.py" "$RUN/findings.json" "$RUN/report.html"
```

Exit status 2 means the findings broke the schema; the message names the field. Fix and
rerun. If a browser tool is available, open the report over a local HTTP server and look at
the top, the persona cards and the count table. Stop the server afterwards.

## Step 6: reply

Give the report's absolute path, the count table, the persona verdicts in one table, and what
was not verified. Offer to publish the report as a private page. Do not paste the report.

## Cost and scope

One run spends about twelve analyst contexts. For a quick read of one question (for example
"is this page's email setup sound?"), run only the matching analyst and skip the report.
