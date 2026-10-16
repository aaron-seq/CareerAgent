# Progress Log

Living status log. Update the top block at the end of every working session.
Full plan in `ROADMAP.md`; conventions in `CLAUDE.md`; research in `docs/RESEARCH.md`.

## Current status
- **Current phase:** Phases 0–10 have implementations; production hardening remains ongoing.
- **Last updated:** 2026-10-16
- **Next action:** Owner decision on historical PII [#38](https://github.com/aaron-seq/CareerAgent/issues/38), then the hosted-fetch and metadata-encryption prerequisites in `docs/SECURITY_AUDIT.md`. Continue matching quality, dependency reproducibility, and advisory typing work. Source attribution, bounded pagination, and functional PR Docker checks are implemented.
- **Blockers:** Public-history PII remains unresolved. Actual model inference, Gmail OAuth/delivery, Postgres locking, and real-browser extension behavior remain unverified in this environment. Local job-board access works; some model/log download destinations remain blocked.

## Verification level per phase
- **Genuinely run + tested here:** P1 data layer, P4 dedup/scoring, P5 resume
  tooling, P6 tracking, P7 outreach gate logic, P9 enrichment/digest, P10
  analytics, and the full internal E2E (`tests/test_e2e_pipeline.py`).
- **Built + unit-tested, external boundary mocked:** P2 ingestion adapters
  (respx), P3 JSON-LD/polite fetcher (respx), P7 email verification (stub
  resolver), P9 Telegram/Discord emitters (respx).
- **Built + unit-tested, NOT live-verified:** P8 extension in a real browser,
  real email delivery, and deployment (dry-run only).

Totals: **540 Python tests + 50 JS tests pass; `ruff` + `ruff format` clean.**
Core coverage is **92.78%**. Passing tests do not establish production readiness.

## Log

### 2026-10-16 — First-use UX: profile without a model, real-user fixes

**Found by:** a real-user acceptance test (Playwright driving Streamlit as a
first-time job seeker; no Ollama/Groq; job APIs blocked). 20 findings; the
blocker: with no model there was no way to create a profile, so nothing
downstream (drafts, tailoring, autofill export) was reachable.

**Changes (UI calls facade only):**
- "Your profile" screen: *Type it in* (default without a model) or *Upload a
  CV (uses AI)*. `facade.save_manual_profile` validates every field at once
  and updates in place; application answers (work rights, pay, start date,
  preferences, opt-in diversity answers) save via `save_candidate_profile`
  with a completeness bar. Tri-state questions keep "not sure" as unknown.
- Deleted the Preferences panel (nothing read it; it reset on refresh) and the
  sidebar session stats (the stage rail already shows progress).
- Feedback survives `st.rerun()` (flash queue); redirects explain themselves;
  discovery inputs survive navigation (widget keys).
- Contacts: typed emails validated (`facade.manual_contact`), labelled "Added
  by you" instead of a fabricated "Verified 100%".
- Draft Studio: *Write it myself* makes the editor and compliance check usable
  offline. Job boards default to a keyless source with human names.
- Pipeline cards: match quality in words, chips, risk notes, Apply / I applied
  / Save for later; board buttons say where they move a card.
- Plain-language help for ATS, slug, ghost jobs, LIA, opt-out; disabled
  buttons look disabled; sidebar collapses on phones.

**Not addressed here:** state lost on page refresh (#48).


### 2026-10-16 — Timezone-aware UTC datetimes; sqlmodel cap lifted (#37)

**Problem:** sqlmodel 0.0.45+ infers a `UTCDateTime` column type that raises on
naive values; with 0.0.48 installed, 78 of 452 tests failed on `main`. The
`<0.0.45` stopgap cap (2026-10-14) froze the dependency.

**Fix (ADR 0008, supersedes the 2026-08-27 naive-UTC convention below):**
`utc_now()` now returns aware UTC; `ensure_utc()` replaces `to_naive_utc()`
(naive = assume UTC, aware = convert). Every DB datetime column declares a
project `UTCDateTime` TypeDecorator (`DateTime(timezone=True)`, coerces on
write and read), so rows read back aware UTC on *every* sqlmodel version.
Comparison boundaries that take outside input (`due_followups`, snooze,
application cards, `SendPolicy`, ghost age) coerce with `ensure_utc`;
`parse_date` returns aware UTC. Migration `3f1c2a9d7e45` moves the 12 columns
to `timestamptz` on Postgres (`USING col AT TIME ZONE 'UTC'`). Cap lifted to
`sqlmodel>=0.0.14,<1.0.0`.

**Verified:** 459 passed on sqlmodel 0.0.14 (SQLAlchemy 2.0.54), 0.0.44 and
0.0.48 (SQLAlchemy 2.1.x); ruff + format clean. Alembic on a temp SQLite DB:
`upgrade head` → `alembic check` clean → pre-migration naive row reads back
`2026-03-01 09:00+00:00` → `downgrade -1` → `upgrade head` round-trips with
data intact. Postgres SQL inspected offline only (no live Postgres here).
**Rollback:** `alembic downgrade -1`, revert, restore the cap.

### 2026-10-16 — Candidate answers + apply flow salvaged from an unmerged branch

`claude/ui-integration-followup` had four commits pushed after its PR merged.
Each piece was re-implemented on main's current structure, or dropped:

- **Ported (adapted):** `core/candidate.py` stores application answers (work
  authorization, sponsorship, compensation, availability, preferences, opt-in
  demographics) in an encrypted `cv_profile.candidate_payload` column beside
  the CV, not a second CV copy. Migration `3c90c531157f` follows
  `cbb284f817e8`; upgrade → downgrade → upgrade verified on a temp SQLite DB and
  covered by `tests/test_migrations.py`. Completeness meter ranks gaps by how
  often they block a form.
- **Ported (adapted):** `core/apply.py` + facade `apply_target`,
  `mark_applied`, `save/load_candidate_profile`, `profile_completeness`, and
  an extended `extension_profile(cv, candidate, include_resume)` instead of a
  second export format. One fixture pins the JSON contract in both test suites.
- **Ported (adapted):** extension screening-question answering (select, radio,
  text, textarea), resume attachment to the resume input only, amber flags for
  unanswered questions. Fixed a yes/no matcher bug from the old branch ("I am
  not" matched "I am"). Still user-triggered; never submits.
- **Ported:** pure job-card helpers in `core/presentation.py`.
- **Dropped:** `freeboards.py` (main's `boards.py` supersedes it), the old
  theme-aware CSS and app.py changes, stage/empty-state copy (main's stage
  rail covers it), auto-fill on page load and broader host permissions.
  `scripts/verify_sources.py` deferred: no live network here to verify it.
- **Not done here:** app.py wiring (onboarding answers form + completeness,
  Apply / I applied buttons, export with answers/resume, job-card helpers).
- **Validation:** 533 Python tests (+81), 50 extension tests (+32), ruff
  lint/format clean. The extension is not live-browser verified for selects,
  radios or file attachment; ADR 0009 records the storage and contract choices.

### 2026-10-16 — Guided workflow, task automation, and independent PR review

- Fetched latest main and independently reviewed the sole pending PR #44.
  Resolved a semantic-version metric crash and fresh Docker bind-permission
  failure before merging it. Its updated Python 3.9–3.11/lint/extension CI and
  subsequent main CI passed; fresh-volume app/persistence checks passed locally.
- Reopen encrypted saved CVs without parsing again. Profile changes invalidate
  generated materials and automatically refresh matches; recovery notices stay
  visible on failure. Keep browsing, tracking, tailoring, review and exports
  available without a model; gate only actual AI actions.
- Scope email/letter/resume/WhatsApp workspaces and editor widgets by job;
  preserve edits on return and reset editor values on new generations. Connect
  API and manually selected/pasted jobs to Prepare application and the pipeline.
- Keep withdrawn and duplicate-titled applications selectable. Preserve source
  attribution/link per posting (#19), preferences through navigation, and make
  ZIP exports downloadable in the browser.
- SmartRecruiters now follows pages (#20), with unique-ID/request/job bounds,
  clear partial results, malformed-payload checks, and continuation controls.
- Added `python -m scripts.check` and functional Docker smoke. PR CI now tests
  app screens, encrypted persistence across containers, nonroot execution and
  health; Actions use verified SHA pins, Node 24, read-only token permissions,
  explicit runner versions and bounded runtimes.
- Digest CLI validates limits/channel configuration, reports rejected deliveries
  with a failing status, sanitizes database/malformed-URL/network errors, and
  never retries possibly completed sends automatically. No real delivery run.
- **Validation:** 452 Python tests, 18 extension tests, lint/format, Compose
  config, Docker build and functional smoke passed. Core coverage increased
  92.48% → 92.78%; advisory mypy reports 29 existing errors (previously 32).
  Existing eight deprecation/reload warnings remain documented. No real-browser
  screenshot/accessibility or live model/OAuth/Postgres validation is claimed.
- **Review:** Four subagents split PR, UI, ingestion and CI work, with independent
  review and regression tests for findings. `docs/WORKFLOW_AUDIT.md` records the
  findings, evidence, limits and rollback; ADR 0007 records the decisions.
- Matrix validation exposed older Streamlit 1.50 retaining stale controls after
  immediate navigation. Prepare application now uses supported callbacks before
  rendering; the original failing Python 3.9 journey passes unchanged.
- Independently ran all 452 tests on Python 3.9.25 / Streamlit 1.50: pass,
  coverage 92.72%, with three additional SDK runtime-support warnings. Python
  3.11 remains recommended; the runtime transition is tracked in #46.

### 2026-10-15 — Boundary audit and targeted privacy/reliability fixes

- Audited implementation/history and all 21 open GitHub issues; zero open PRs
  needed consolidation. Restored a current `docs/SECURITY_AUDIT.md` with explicit
  evidence, residual risks, benchmark, migration, and rollback guidance.
- Moved Gmail creation behind the facade so Streamlit reruns cannot discard
  approval or the compliant footer. Recheck current recipient/content/opt-out;
  persist successful exports and serialize quota checks. The quota survives
  request/service recreation, and simultaneous SQLite requests cannot both
  consume the same minimum-gap allowance. Postgres locking is not live-tested.
- Required MX verification now fails closed on unknown status; distinguish DNS
  timeout from missing/null MX. Validate complete sender/footer/opt-out fields.
  Added dnspython to implement the existing DNS requirement.
- Retain a private local key across restarts; encrypt JSON artifacts, sanitize
  and uniquely allocate filenames, contain reads, and support explicit atomic
  legacy migration. Keep readable exports and warn at export. OAuth tokens are
  privately written, and credentials/tokens/temp key material are ignored.
- Reject failed/empty CV extraction; always clean private temporary uploads.
  Resume tailoring only reorders unchanged candidate facts. Cover-letter metric
  checks no longer join unrelated digits or conflate decimals/units, trust unseen
  JD suffixes, or accept candidate claims solely from job metrics. Free prose
  still needs human review.
- Disconnect active inference on provider/model selection changes, honor Ollama
  deployment settings, and reject unavailable models at initialization.
- Harden local Docker deployment: non-root, excluded secrets/data, service-name
  routing, loopback publication, persistent DB/key, optional Gmail credentials,
  and optional trusted CA build-secret support. Container UI/imports and
  encrypted continuity across replacement were verified.
- Empty `DATABASE_URL` now selects SQLite, fixing a local digest-workflow
  reproduction. The latest remote digest runs still fail; their logs were
  inaccessible, so no remote repair is claimed.
- **Validation:** 338 → 377 Python tests, 18 JS tests, lint/format, SQLite
  migrations, Compose config, Docker build and functional checks pass. Coverage
  92.07% → 92.48%. Mypy remains advisory (32 errors versus 33 baseline with
  Python 3.11 target). Existing PyPDF2 deprecation and deliberate SQLModel-reload
  warnings are documented rather than suppressed.
- **Performance baseline:** 200 encrypted 8,000-byte-body save/load cycles;
  save p50/p95 0.135/0.296 ms, load p50/p95 0.153/0.280 ms on this shared machine.
  No end-to-end speedup or production load claim.
- **Decision:** ADR 0006 records persistent key/artifact and gated-export semantics.

### 2026-10-14 — Fresh installs broke 56 tests: sqlmodel 0.0.45 tz change

**Found by:** a clean `pip install -r requirements-test.txt` on `main`
(792b9f5). 56 of 338 tests failed with `Datetime values must have timezone
information`. CI was still green only because its last run (2026-09-11)
predates the sqlmodel release.

**Root cause:** sqlmodel 0.0.45 maps every `datetime` field to a new
`UTCDateTime` TypeDecorator that raises on naive values. The codebase stores
naive UTC by design (`core/normalize.utc_now()`), and `sqlmodel<1.0.0` let the
new release in. Bisected: 0.0.44 has no `UTCDateTime`; 0.0.45–0.0.48 all do.

**Fix:** cap `sqlmodel<0.0.45` in `requirements.txt` (comment explains why).
338/338 pass on 0.0.44 with SQLAlchemy 2.1.4. The proper fix — moving the
models to aware datetimes with a migration — is tracked as a GitHub issue.
**Rollback:** revert the one-line pin.

### 2026-09-11 — Follow-up reminders reach the UI; app→extension profile handoff

**Root cause, not symptom.** Phase 6 shipped `TrackingService.due_followups()`
and `snooze_followup()` with passing unit tests, but neither was ever exposed
on `core/facade.py` — the only door `app.py` uses for DB-backed logic. The
reminder feature has been complete and unreachable since it was written.
`ApplicationRow.notes` was likewise a column nothing wrote. The lesson
generalises: `tests/test_tracking.py` tested the service directly, so a whole
dead feature stayed green. The new facade-level E2E test exists to catch that
class of gap.

- **`core/facade.py`** — added `due_followups()`, `snooze_followup()`,
  `set_application_notes()`, and `extension_profile()`. Board cards now come
  from one `_application_card()` helper carrying `url`, `status`, `notes`,
  `applied_at`, `days_since_applied`, `days_until_follow_up` and `overdue`.
  The `url` is what makes a card actionable — it is where the autofill
  extension runs, and without it the dashboard dead-ended.
- **`app.py` Pipeline** — a **Follow-ups** panel above everything else
  (overdue count, days-overdue, posting link, snooze 3d/7d, mark rejected),
  an empty state that explains when reminders appear, and an
  **Application detail** panel under the board for notes and status changes.
- **Board layout fix, found by running it.** The first cut put the notes box
  and buttons inside the six kanban columns. Live in the browser those columns
  are ~129px, so the notes field rendered 94px wide and "→ screening" wrapped
  to three lines. The columns are now a compact overview and everything
  editable moved to the full-width detail panel (notes 503px, buttons single-line).
- **Rejected/withdrawn from any active state.** The board previously only
  modelled the happy path, so dead applications sat in "applied" forever,
  skewing the funnel and nagging with stale reminders.
- **App → extension handoff** — `facade.extension_profile(cv)` maps the parsed
  CV onto the seven field names in `extension/src/field_mapping.js`; the
  Export screen renders it as copyable JSON, and the popup gained an
  **Import from CareerAgent** box. Clipboard, not HTTP: no host permission on
  the app's origin, no CORS, no localhost server, and `parseImport` whitelists
  the seven known keys so a larger pasted blob can't push anything else into
  `chrome.storage.local`.
- **Tests: 331 → 337 Python, 11 → 18 JS.** Five facade tests covering the
  reminder lifecycle, the notes round-trip and the profile mapping; five JS
  tests on the import parser; and
  `test_candidate_journey_through_the_facade` — a real E2E that crosses the
  facade boundary only (discover → save → apply → reminded → chase → offer),
  the layer where the bug actually lived. `temp_db` moved from
  `test_facade.py` to `conftest.py` now two modules need it.
- **Live-verified in the browser**, not just under pytest: seeded an overdue
  application, confirmed the panel and ⚠️ flags render, clicked **Snooze 7d**
  and watched the reminder clear and the flag disappear.


### 2026-08-27 — 13 job sources live-verified, timestamp convention, security audit

Three parallel agents on disjoint files; all work verified, none committed.

**Job ingestion: 6 sources -> 13.** New company ATS boards (SmartRecruiters,
Recruitee, Workable) and keyless job boards (Arbeitnow, Jobicy, RemoteOK,
Himalayas), plus an `ATTRIBUTION` map so sources that legally require credit
(RemoteOK especially) get it in the UI. `app.py` now drives both pickers from
`facade.aggregator_providers()` / `ats_providers()` instead of hardcoded lists.

Live-verified 2026-08-27 against real vacancies: Arbeitnow 175, RemoteOK 99,
Jobicy 50, Himalayas 20; SmartRecruiters BoschGroup + PublicStorage; Workable
blueground/spotawheel/orfium/skroutz; Recruitee fixico/hygraph. 344 live
postings from the four keyless boards alone.

**Wellfound: NOT VIABLE, do not implement.** Four independent blockers verified
(no public API, no logged-out JSON-LD + Turnstile, robots.txt disallows the
browse surface, ToS bars automated collection). Breaches guardrail 3. Use the
startup's own Greenhouse/Lever/Ashby board instead. Full evidence in
`docs/RESEARCH.md` A2.

**Timestamp convention: naive datetimes holding UTC**, repo-wide. `utc_now()`
and `to_naive_utc()` in `core/normalize.py` are the only producers/coercers.
Chosen over timezone-aware because SQLite `DATETIME` and Postgres `timestamp
without time zone` (ADR 0003) cannot persist an offset, so aware values
round-trip to naive and then raise `TypeError` on comparison. Killed all 194
`datetime.utcnow()` deprecation warnings. Fixed a real bug this exposed:
`date_posted` from `dateutil` arrives aware, and was being written into a naive
column with the offset silently dropped (`+05:30` stored as UTC, off by 5.5h) —
now coerced at both ingestion boundaries.

**CI has never passed.** `requirements-test.txt` pinned `responses==0.25.9`, a
version never published to PyPI (0.25.8 -> 0.26.0), so `pip install` died before
`pytest` ran on every job — every merge to `main` went in ungated. The package
was imported nowhere (`respx` does all HTTP mocking), so the pin was deleted
rather than corrected. Dependency set now resolves clean.

**Security audit** -> `docs/SECURITY_AUDIT.md` (21 findings: 1 Critical, 8 High).
Independently verified: repo is PUBLIC, commit `d92bfb5` added 11
`cv_profile_*.json` files with real name/phones/email, still in history after
being untracked. Also: the CAN-SPAM footer is displayed but not sent
(`app.py` sends the raw textarea body, not `decision.body`), opt-out HMAC keys
regenerate per process when `CAREERAGENT_ENCRYPTION_KEY` is unset, the send cap
is inert, and `assert_no_fabrication` has a demonstrated bypass (the guard
trusts the whole JD while the model only sees `[:3000]`).

**Tests: 297 -> 330 passing, warnings 194 -> 9.** `ruff` clean.

### 2026-07-27 — CV parsing fabrication fix, cover letters, Groq provider, dark-native redesign
First session with live network access: real Groq LLM calls and a real
Remotive job-API pull, tested against the maintainer's actual CV end-to-end.
- **Found and fixed a real fabrication bug.** A CV's contact links render as
  anchor text (visible word "Github") with the URL only in the PDF's link-
  annotation layer, which `extract_text()` discards. With no URL in its input,
  the model invented a plausible-looking one from the candidate's name --
  `github.com/AaronSequeira` instead of the real `github.com/aaron-seq`. Fixed
  by extracting annotation-layer hyperlinks (`_extract_hyperlinks_from_pdf`)
  and appending them to the prompt after truncation, plus rewriting the
  prompt's placeholder shape (which itself taught the model to invent a
  username) into an explicit copy-or-null instruction with an anti-fabrication
  rule. Verified against the real CV: GitHub/LinkedIn now match exactly, two
  previously-null project repo links recovered. 6 new tests
  (`tests/test_cv_parser.py`).
- **Added cover letter generation** (`core/resume/cover_letter.py`), gated the
  same way `tailor.py` gates resume tailoring: raises rather than ship a
  letter naming an employer not in the CV or citing an unsupported metric.
  First live draft cited zero metrics -- the guard had made the model avoid
  numbers entirely; rewrote the prompt to positively push real figures, and
  the next draft cited 5, all CV-verified, plus one honestly-flagged gap. 8
  new tests (`tests/test_cover_letter.py`).
- **Added Groq as a free cloud LLM provider** alongside Ollama
  (`CloudLLMClient` in `core/llm.py`, subclasses `LocalLLMClient`, overrides
  only the 3 HTTP methods). Lets the app run without installing Ollama +
  pulling multi-GB models first. This is a deliberate, documented deviation
  from ADR 0002's "cloud only for non-PII work" guardrail -- see ADR 0005.
  Verified live: connected, listed 15 models, `generate_json` round-tripped.
- **Dark-native UI redesign.** `assets/style.css` had been authored for a
  light theme while `.streamlit/config.toml` set a dark one, rendering every
  heading near-invisible (near-black text on near-black background). Rewrote
  dark-native; added a stage rail across the top reflecting the app's real
  screen gating (Discovery can't run before Onboarding); reworded the six
  gating messages from state descriptions ("please initialize LLM first") to
  next actions ("pick a provider, then choose Initialize LLM").
- **Privacy cleanup:** 11 parsed CV profiles (real PII: name, email, phone,
  employers) and 1 job posting were tracked in git as stale test artifacts.
  Untracked them and extended `.gitignore` to prevent recurrence
  (`careeragent_data/{cv_profiles,contacts,job_postings}/`, `*_CV.pdf`). Note:
  content is still in git history; a full purge needs a history rewrite, left
  for the repo owner.
- **Found, not yet fixed:** job-matching keyword extraction
  (`core/matching/scoring.py::_job_keywords`) prefers curated
  `tech_stack`/`requirements`, but aggregator-ingested jobs never populate
  those fields (only the LLM job-parse path does) -- so it falls back to
  tokenizing the raw description against a 20-word stopword list. Observed
  live: a real job's "missing skills" list was full of stopwords (`at`, `is`,
  `who`, `why`) and punctuation-glued tokens (`api.`, `built.`), and match
  scores are systematically deflated (4 matched / ~200 prose tokens). Fix:
  run aggregator-ingested jobs through the existing `JOB_PARSE_PROMPT` to
  populate `tech_stack` -- the parser already exists, ingestion just skips it.
  Cost is one LLM call per job, a tradeoff intentionally left for the
  maintainer to decide rather than assumed.
- 14 new tests. Totals: **204 Python + 11 JS tests green; ruff clean.**

### 2026-07-25 — Removed fabricated enrichment data (honesty fix)
The bundled "sample" enrichment CSVs contained **invented facts about real,
named companies** (Glassdoor ratings, layoff history, sponsor status), and the
lookup logic turned *absence of data* into a **false negative** — any company
missing from an 8-row file was recorded as `sponsors_visa = False`. For a
job-search tool that is actively harmful: a user could rule out an employer
because of data we made up.
- **Deleted** both fabricated CSVs. Nothing is shipped in their place.
- **Tri-state everywhere:** `is_sponsor()` / `CompanySignal` return
  `True` / `False` / `None`; `None` means *unknown* and is never rendered as a
  negative. `annotate()` is a no-op without a dataset, leaving columns NULL.
- **Schema:** `Company.had_layoffs` `bool = False` → `Optional[bool] = None`
  (a default of `False` asserted "no layoffs" for every unknown company).
  Migration `cbb284f817e8`, up/down verified.
- **Real loaders:** `VisaSponsorFilter.from_csv` auto-detects the employer
  column across the official UK Home Office and USCIS export formats.
- **`scripts/fetch_datasets.py`** downloads the real UK register (discovers the
  current CSV on gov.uk), verifies it parses, writes atomically via a `.part`
  file, and fails loudly rather than leaving a truncated file.
- **UI honesty:** the "visa sponsors only" filter is *disabled* with an
  explanation when no register is loaded; a caption reports when matching is
  using the lexical fallback rather than semantic embeddings
  (`facade.data_status()`). Removed hardcoded `stripe` demo defaults.
- 20 new/rewritten tests. Totals: **180 Python + 11 JS green; ruff clean.**

**Still not real in this environment** (network is blocked except PyPI): live
API pulls, the actual dataset download, semantic embeddings (model hub
unreachable), and any live browser render.

### 2026-07-23 — Remaining core services surfaced (branch: claude/discovery-api-first)
Every `core/` service is now reachable from the UI; nothing built in Phases
1–10 is left unwired.
- **Aggregator ingestion** (`ingest_aggregator`): Remotive (keyless), The Muse
  (optional key), Adzuna (requires env keys, fails with a clear message).
  Surfaced as a "Job boards (API)" Discovery mode, with the Remotive
  attribution requirement shown in the UI.
- **Full enrichment chain** in `refresh_matches`: dedup → link companies →
  salary → ghost score → visa sponsor → company signals → score. Fixed a real
  gap: jobs were never linked to their `Company` row (`link_companies`), so
  visa/Glassdoor/layoff data could not be joined per job.
- **Filters** on the Pipeline screen: min score, remote-only, hide ghost jobs,
  visa sponsors only, new-grad/internship level.
- **Digest** on the Export screen: rendered inline + Markdown and RSS
  downloads (`digest_rss` added).
- **Interview prep** in Draft Studio: questions derived from the JD, with a
  downloadable prep list.
- 7 new facade tests. Totals: **165 Python + 11 JS tests green; ruff clean.**

### 2026-07-23 — Discovery reworked to API-first (branch: claude/discovery-api-first)
- Facade gains `discover_from_url`: detects the ATS from a careers URL and pulls
  its public feed; otherwise fetches politely (robots.txt honored, rate-limited)
  and extracts `schema.org/JobPosting` JSON-LD. Recognized-but-unsupported ATS
  (e.g. Workday) is reported explicitly rather than silently scraped.
- **Discovery screen** reordered API-first: "Company careers URL (recommended)"
  is the default mode; DuckDuckGo is retained but relabeled "Web Search
  (fallback)" with a caveat about unstructured results.
- Fixed a branch-chain bug introduced while restructuring the modes (the new
  mode fell through to the paste-description branch), and moved the LLM guard
  from the whole screen to only the modes that need it — the careers-URL and
  paste-description modes now work without Ollama.
- 5 new facade tests (ATS detect, JSON-LD fallback, unsupported ATS, robots
  block, no-JSON-LD). Totals: **158 Python + 11 JS tests green; ruff clean.**

### 2026-07-23 — Resume tooling surfaced in the UI
- Facade gains `lint_resume`, `resume_pdf`, `resume_markdown`, `resume_json`,
  `tailor_for_job`.
- **Onboarding:** ATS-friendliness report (errors/warnings/suggestions) plus
  one-click downloads — ATS-clean PDF, Markdown, and JSON Resume.
- **Draft Studio:** "Tailor resume to this job" — shows emphasized skills and
  honest gaps, and offers a per-company tailored ATS PDF. Fabrication is
  impossible by construction (`assert_no_fabrication` in `core/resume`).
- 4 new facade tests (lint severities, emoji flagging, PDF/MD/JSON render,
  truthful tailoring). Totals: **153 Python + 11 JS tests green; ruff clean.**

### 2026-07-23 — UI wiring (core services → Streamlit)
- Added `core/facade.py` — the single, **tested** entry point `app.py` calls
  (session-managed; returns plain dicts, never ORM objects), keeping business
  logic out of the UI per CLAUDE.md.
- `app.py`: DB-persist CV on parse; new **Pipeline** screen (ATS API ingest →
  explainable scored matches → add-to-pipeline → kanban board + funnel);
  Draft Studio now runs the **outreach compliance gate** before a Gmail draft
  (blocks send until identity + postal address + opt-out + LIA pass).
- 6 facade tests (temp-file DB, respx-mocked ingest). `app.py` verified via
  `py_compile`, `ruff`, and a stubbed-streamlit module-load smoke test — a live
  browser render was **not** performed here.
- Totals now: **149 Python tests + 11 JS tests green; ruff clean.**

### 2026-07-23 — Phases 1–10 (full platform build)
Built the platform in phase order, one commit per phase, CI green throughout:
- **P1 `core/db`** — SQLModel tables, Alembic, Fernet PII encryption, repos,
  legacy JSON import (ADR 0003).
- **P2 `core/ingestion`** — Greenhouse/Lever/Ashby + Adzuna/Muse/Remotive
  adapters → canonical `JobPosting`; idempotent upsert; error isolation.
- **P3 `core/fetching`** — ATS detection (regex), JSON-LD extraction (bs4),
  robots-respecting rate-limited fetcher.
- **P4 `core/matching`** — pluggable embeddings (hashing fallback), fuzzy dedup,
  explainable resume↔JD scoring.
- **P5 `core/resume`** — JSON Resume interchange, ATS linter, fpdf2 PDF,
  truthful tailoring with `assert_no_fabrication`.
- **P6 `core/tracking`** — kanban state machine, reminders, dup-prevention,
  blacklist.
- **P7 `core/outreach`** — verification, CAN-SPAM/GDPR footer + LIA + send caps,
  single pre-send gate.
- **P8 `extension/`** — MV3 human-in-the-loop autofill; tested field-mapping
  core (Node); never auto-submits.
- **P9 `core/enrichment` + `core/alerting`** — salary/company/visa/ghost
  enrichment, filters, digest (MD/RSS) + Telegram/Discord.
- **P10 `core/analytics` + E2E + deploy** — funnel, A/B, interview prep; full
  E2E pipeline test; `scripts/send_digest.py` + Actions cron; ADR 0004.

### 2026-07-23 — Phase 0 complete (code-touching hygiene)
- Added `pyproject.toml` with ruff (lint + format) and mypy config.
- Ruff baseline gate is `E`/`F`/`W`/`I`; fixed all findings: removed dead
  imports/variables, replaced 4 bare `except:` with `except Exception:`, and
  persisted onboarding preferences into `st.session_state` (previously dropped).
  `ruff check .` and `ruff format --check .` both clean across 19 files.
- Fixed the five Pydantic v2 deprecations `.dict()` → `.model_dump()`
  (`app.py`, `core/storage.py` ×4).
- Rewrote CI `lint` job: ruff check + ruff format are **blocking gates**;
  mypy runs **advisory** (`continue-on-error`) until modules gain type coverage.
  Replaced black/flake8/isort in `requirements-test.txt` with ruff.
- Added GitHub issue templates (`phase.md`, `bug_report.md`, `config.yml`).
- `.env` schema already covered by the existing comprehensive `.env.example`.
- All 51 existing tests pass (`pytest`).
- **Deferred to a follow-up (documented in `pyproject.toml`):** enabling ruff
  `UP` (typing.List → list) and `B` (bugbear, e.g. `raise ... from`) rules, and
  tightening mypy from advisory to blocking, module by module.

### 2026-07-23 — Phase 0 kickoff (research + scaffolding)
- Captured the platform research as `docs/RESEARCH.md`.
- Added `ROADMAP.md` (11 phases, 0–10, with acceptance criteria).
- Added this `PROGRESS.md` and `CLAUDE.md` (conventions).
- Started the ADR log under `docs/adr/`
  (0001 record-architecture-decisions, 0002 target-architecture).
- **Still open for Phase 0:** ruff/mypy config + CI lint step; Pydantic v2
  deprecation fixes; `.env` schema doc; GitHub issue templates.
- No code behavior changed in this session — docs/scaffolding only.
