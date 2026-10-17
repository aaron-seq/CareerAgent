# CV builder and public URL validation — 2026-10-17

CareerAgent helps candidates present their own facts clearly. The model-free
builder supports new profiles and edits, readiness actions, selected-job skill
comparison, encrypted persistence, restoration, and PDF/Markdown/JSON downloads.
No user CV was supplied for this validation; all candidate fixtures are synthetic.

## Confirmed defects repaired

| Problem | Result |
| --- | --- |
| New CV creation depended on model extraction | Explicit fact editor works with no model connection or API key. |
| Exports omitted social links, work technologies, project impact and secondary repository URLs | Shared Markdown/PDF content retains these fields; JSON round-trips repository URLs. |
| PDF text silently lost unsupported characters | Bundled Unicode fonts preserve supported text; unsupported glyphs/scripts produce a clear fallback message. |
| A project-only CV received a work-experience warning | Projects count as valid evidence for the linter and readiness checklist. |
| Raw names, email addresses and employer names inflated skill coverage | Raw extraction and identity/contact/employer fields are excluded from skill evidence. |
| Explicitly denied skills and C-level wording could count as experience | Conservative negative-clause handling and explicit C-language context, with regressions for contractions. |
| ‘All Data’ UI exported only local artifacts | Facade ZIP includes database-backed profiles, candidate answers, applications, companies, jobs, contacts, Gmail drafts and suppression records. |

The ZIP is an explicit readable personal-data export. Keep it private. This
does not change encryption of persisted payloads or encrypt all database metadata.

## Score interpretation

Readiness is content completeness: name 10, usable email 15, skills 15,
experience/projects 25, supporting details 15, education 10, complete entries 10.
A project-only candidate can satisfy all checks. Counts or repeated keywords
cannot raise the job-coverage percentage. A complete CV can still have poor
coverage for an unrelated job.

Job coverage reports exact recognized-skill matches and gaps, with explicit
aliases and a visible denominator. Unknown/missing job signals produce no score.
Bare Go/R/C in prose, identity fields, URLs and clearly negated English clauses
are handled conservatively. This remains a lexical aid, with incomplete skill
vocabulary and language understanding. Review context and proficiency yourself.
Neither score predicts a commercial ATS ranking or guarantees an interview.

PDF tests extract actual text with both pdfplumber and pypdf, including Latin,
Greek, Cyrillic, decomposed accents, long URLs, multipage content and all export
facts. Arabic/Hebrew/Indic shaping, CJK outside the font and unsupported symbols
get explicit errors while Markdown/JSON preserve source text. Fonts and their
license are bundled in `assets/fonts/`; nothing downloads during export.

## Real public API evidence

The recorded run read eight sources and parsed **1,535 postings**, checking every
returned title, company, description, source ID, source name and HTTP(S) original
URL. These are observed counts, not guaranteed future results.

| Source | Public board/query | Parsed postings |
| --- | --- | ---: |
| Greenhouse | Stripe | 731 |
| Lever | Palantir | 310 |
| Ashby | Ramp | 167 |
| SmartRecruiters | Ubisoft2, bounded sample | 2 |
| Remotive | Python search | 15 |
| Arbeitnow | Public jobs feed | 300 |
| Jobicy | Bounded sample | 5 |
| Himalayas | Bounded sample | 5 |

[Machine-readable evidence](validation/live-url-results-2026-10-17.json) records
timestamps, API URLs, statuses, response sizes, durations and validation totals.
It retains an earlier Netflix Lever board 404 and an empty Visa SmartRecruiters
board, followed by successful checks using current public board slugs. The
combined attempts made twelve GETs. Careers URL detection was also checked
locally for the four ATS boards; those HTML pages were not fetched. No job was
persisted, CV sent, application opened/submitted, or outreach delivered.

This evidence validates API parsing and attribution. It does not validate each
posting's application-page HTTP response, live browser autofill, model inference,
or commercial ATS ingestion/ranking. Production data and public boards change.

To repeat deliberately:

```bash
python -m scripts.live_url_smoke --live --output /tmp/careeragent-live-results.json
# Limit a follow-up to selected sources:
python -m scripts.live_url_smoke --live --sources greenhouse lever --output /tmp/ats-results.json
```

Each source is limited to three requests, a 15-second request timeout and 12 MiB
decoded response data per request. Redirects are not followed. Empty, blocked and
failed checks remain distinct and return nonzero. Ordinary pytest and CI never
perform these live checks.

## Verification boundaries

Regression tests cover core validation, no-network construction, fact retention,
score inflation, persistence/export, and Streamlit journeys (create/edit, failed
save, backup warning, restore, selected job, unsupported-script fallbacks).
Run `python -m scripts.check` and optionally `python -m scripts.check docker`.
Measured suite totals and Docker outcomes are recorded in `PROGRESS.md`.

Existing hosted-fetch/metadata privacy prerequisites remain in
[the security audit](SECURITY_AUDIT.md); matching improvements remain tracked in
[#10](https://github.com/aaron-seq/CareerAgent/issues/10). The new lexical coverage
is separate from the existing discovery ranking and truthful-tailoring gap
algorithm; the three scores/reports should not be treated as interchangeable.
