# Rubric and schemas

## Severity

Rate each issue by its effect on a buyer deciding whether to hire the site's owners.

| Severity | Meaning | Examples from calibration runs |
|---|---|---|
| `critical` | Stops a buyer from hiring, or creates legal exposure now. Fix before any promotion. | Nobody named anywhere on the site; no legal identity where the law requires one |
| `high` | Likely to lose a qualified buyer or cause real damage. Fix before outreach. | Headline reads as a threat with no consent wording; absolute promise ("so nobody else can"); no DMARC record; replies cannot authenticate; privacy notice describes processing that does not happen |
| `medium` | Weakens the result. Fix before the full launch. | News hook overstates its sources; conversion not measured; new-domain filters for 30 days; analytics script loaded unpinned from a third party |
| `low` | Polish. | Text under 12 px; unused CSS; favicon not cached; residual AI copy patterns |

Rules:

- **One row per root cause.** When two analysts report the same cause, keep one issue and the
  stronger evidence. Do not split one cause across domains to inflate a count.
- **Only what the site shows.** Preconditions nobody can see from outside (contracts,
  insurance, internal processes) go into a report section, not the register.
- **Inferred issues are allowed** when the evidence names the inference.
- **Severity is a judgment.** Say so in the report; never present counts as measurements.

## Domains

Every issue belongs to exactly one domain. The first two are always present.

| Key | Name | Covers |
|---|---|---|
| `mkt` | Marketing and SEO | Message, headline, offer, audience, copy accuracy, conversion path and measurement, search snippet, sitemap, soft 404s, design distinctiveness |
| `bp` | Best practices | Accessibility, performance, console errors, caching, unused code, motion |
| `trust` | Trust and brand | People, credentials, proof of work, process, footprint, name collisions, trademark |
| `legal` | Legal and compliance | Mandatory disclosures, privacy notice, consent, advertising rules |
| `mail` | Email and reachability | SPF, DKIM, DMARC, sending path, new-domain filtering, web-filter category |
| `sec` | Security and privacy | Supply chain (unpinned third-party code), headers, trackers, anything malware-like |

Add a domain only when several issues fit none of these.

## Analyst output: `RUN/findings/<agent>.json`

Each analyst writes one file and replies with a short summary only. Files cannot be
truncated; long replies were cut off in calibration runs, so the file is the contract.

```json
{
  "agent": "tc-email",
  "verdict": "One sentence: the answer to the analyst's question.",
  "sections": [
    {"id": "email", "title": "Email and reachability", "blocks": [
      {"p": "Text with **bold** and `code`."},
      {"h3": "Sub-heading"},
      {"ul": ["item", "item"]},
      {"ol": ["step", "step"]},
      {"table": {"head": ["Check", "Result"],
                 "rows": [["DMARC", {"text": "No record", "tone": "bad"}]]}},
      {"note": "Caveat text", "kind": "warn"},
      {"code": "_dmarc.example.com. TXT \"v=DMARC1; p=none\"", "lang": "dns"}
    ]}
  ],
  "issues": [
    {"domain": "mail", "severity": "high", "title": "No DMARC record",
     "evidence": "dig TXT _dmarc.example.com returned nothing",
     "fix": "Publish p=none with reporting, then tighten", "basis": "verified"}
  ],
  "limits": ["What could not be checked, and why"],
  "sources": ["https://..."]
}
```

Cell tones: `ok`, `warn`, `bad`, `dim`. Inline markup: `**bold**` and `` `code` `` only; all
other text is escaped. `basis` is `verified` (a command, page or measurement shows it) or
`inferred` (reasoned from evidence).

## Report document: `RUN/findings.json`

The lead merges the analyst files into this and runs `build_report.py`, which validates it
and computes every count.

```json
{
  "target": "https://example.com",
  "title": "example.com: message, trust and readiness",
  "lede": "One sentence on what was reviewed.",
  "date": "2026-11-06",
  "meta": {"Domain registered": "2026-11-05", "Method": "passive, read-only checks"},
  "summary": {"lead": "The answer in one sentence.", "bullets": ["**Point.** Detail."]},
  "screenshots": [{"path": "/abs/desktop.png", "alt": "...", "caption": "Desktop", "width": 1100}],
  "domains": [{"key": "mkt", "name": "Marketing and SEO"}, {"key": "bp", "name": "Best practices"}],
  "sections": [{"id": "message", "title": "Message and conversion", "blocks": [],
                "screenshots": true}],
  "personas": [{"name": "A potential customer", "tone": "no",
                "verdict": "What I do after visiting.",
                "fields": [["What I see", "..."], ["What I do next", "..."],
                           ["What would change my mind", "..."]],
                "blocks": []}],
  "issues": [{"id": "M1", "domain": "mkt", "severity": "high", "title": "...",
              "evidence": "...", "fix": "..."}],
  "limits": ["..."],
  "corrections": ["..."],
  "sources": ["https://..."]
}
```

- Persona `tone`: `no` (would not proceed), `hold` (would wait or proceed only with conditions),
  `go` (would proceed).
- Issue ids: a domain letter plus a number (`M1`, `B1`, `T1`, `L1`, `E1`, `S1`), unique.
- Reserved section ids: `summary`, `personas`, `limits`, `corrections`, `sources`,
  `register`, `counts`. The builder adds them itself: the summary first, then your sections,
  then the rest in that order, so the count table is always last.

## Personas

Default five, each answering "what would I do after visiting this page?":

1. A potential customer
2. A potential investor
3. A potential business partner
4. A potential acquirer
5. The company owner

For each: a one-line verdict, what they see, what they do next, what would change their mind.
The owner persona's fields are "What I see", "What I do this week", "What I keep" and
"What I decide before spending". Use the simulated buyer grid from `tc-buyers` inside the
customer card. Label every persona verdict as a reasoned judgment, not an interview.
