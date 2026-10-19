# CareerAgent

A local career workspace for building a truthful CV, finding jobs, preparing
application materials and tracking follow-ups. AI assistance and contact
discovery are optional.

## Features

- **Local-first LLM, cloud opt-in**: Ollama (Llama 3, Mistral, Qwen) by
  default for privacy-focused, zero-cost inference; Groq's free tier as an
  alternative when Ollama isn't installed (see ADR 0005 for the PII tradeoff
  this involves).
- **Job Discovery**: API-first ingestion from 13 sources — company ATS boards
  (Greenhouse/Lever/Ashby/SmartRecruiters/Recruitee/Workable) and aggregators/job boards
  (Adzuna, The Muse, Remotive, Arbeitnow, Jobicy, RemoteOK, Himalayas) — with DuckDuckGo search as a
  fallback mode.
- **Contact Finder**: Search for hiring managers, add known contacts, or
  generate unverified patterns for an email domain you supply. Provenance
  labels describe the source; they do not verify a mailbox.
- **Resume tailoring & cover letters**: Truthfully reorders/emphasizes your
  real CV content per job, and checks cover-letter metrics against it.
  Free-prose checks are heuristic; review generated claims before exporting.
- **CV builder without AI**: Create or edit your own facts, check content
  readiness, compare recognized skills against a selected job, and download
  selectable-text PDF, Markdown, or JSON Resume.
- **Personalized Outreach**: Generates technical, product, or impact-focused email drafts based on your CV and the job description.
- **Quality Assurance**: Built-in validation to ensure emails meet professional standards (no fluff, concrete metrics, clear CTA).
- **Multi-Channel Support**: Creates Gmail drafts directly or generates WhatsApp click-to-chat links.
- **Guided workflow**: Reopen a saved CV, browse jobs before connecting AI,
  and open saved postings directly in Draft Studio. Drafts and resume variants
  stay with their selected job.
- **Refresh recovery**: Restore the active CV, deliberately selected jobs,
  contacts, preferences and page from a small encrypted local workspace.
- **Reviewed autofill**: Save optional application answers with each CV,
  preview what will be shared, and download an extension profile with an
  optional CV PDF. Unknown answers stay unanswered and you submit the form.

## Technical Architecture

The application is built with a modern Python stack:

- **Frontend**: Streamlit for a responsive, interactive UI.
- **LLM Orchestration**: Custom Python client interacting with Ollama API.
- **Data Parsing**: pdfplumber and pypdf for robust CV extraction.
- **Search**: DuckDuckGo Search API for real-time contact and job data.
- **Storage**: Encrypted local JSON artifacts and selected SQLite fields;
  explicit Markdown/ZIP exports contain readable personal data.

## Getting Started

### Prerequisites

- Python 3.11 or newer; CI tests 3.11, 3.12 and 3.13.
- Optional for CV parsing and AI drafts, an LLM provider — either:
  - **Ollama** installed and running locally (standard default port 11434), or
  - A free **Groq** API key (no credit card: console.groq.com/keys) — faster
    to get running, but sends prompts off-machine; see ADR 0005.

### Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/aaron-seq/CareerAgent.git
    cd CareerAgent
    ```

2.  Install dependencies:
    ```bash
    python -m pip install --require-hashes --only-binary=:all: \
      -r requirements/locks/test-py311.txt
    ```

    This reproduces the reviewed Linux x86_64 development graph. Select `312`
    or `313` for that interpreter minor; use `runtime-py311.txt` for an app-only
    install. Other platforms can resolve `requirements-test.txt` and validate
    their own graph. See [lock scope and refresh](requirements/locks/README.md).

3.  If you want AI parsing or drafting, set up an LLM provider — either:
    ```bash
    ollama pull llama3.1:8b
    ```
    or copy `.env.example` to `.env` and set `GROQ_API_KEY`.

4.  Run the application:
    ```bash
    streamlit run app.py
    ```

The app creates an ignored, mode-0600 `.careeragent_key` on its first encrypted
write unless `CAREERAGENT_ENCRYPTION_KEY` is supplied. Keep this key stable and
back it up with `careeragent.db` and `careeragent_data/`; losing it makes
encrypted data unreadable and changes suppression-list hashes. Deployment
operators can supply a managed key instead. See `.env.example` for supported
settings and [the current audit](docs/SECURITY_AUDIT.md) for remaining risks.

Changing the model or provider disconnects the previous client. Choose
**Connect AI** in the sidebar's **AI settings** before parsing a CV. Connection requires the
selected model to exist; parsing failures are reported rather than saved as
empty profiles.

### Your first application

1. Browse **Job Discovery** to import a company careers page, query a job board,
   or paste a description. Browsing and saving jobs work without an AI provider.
2. In **Onboarding**, use the **Build or edit a CV** tab without connecting AI,
   choose **Import PDF or text** after connecting a model, or choose
   **Use a saved CV** above the tabs. Your
   matches refresh when you switch profiles; resume checks and downloads work
   offline.
3. Open **Pipeline**, choose **Prepare application** on a posting, and tailor
   your resume. Connect your chosen model when you want an email or cover letter.
   Switching jobs preserves each job's edits separately.
4. Review all claims and recipients before exporting. Contacts are optional;
   a selected job can go directly to application materials. Use the posting link and
   browser extension to fill the application, then review and submit yourself.
   **Export & Logs** provides a browser ZIP download of your local artifacts.

Each imported job shows its source and original posting link. SmartRecruiters
imports follow later pages automatically, up to 250 jobs and 20 list pages by
default. A partial-import notice identifies where to continue with the Pipeline
import controls; requests stop if a provider repeats a page.

### Build a CV and improve its readiness

In **Build or edit your CV**, enter your name and your actual skills, education,
roles, or projects. Add work/project entries with the count controls; entirely
blank entries are ignored. Save with **Create CV and check readiness**. Edits
create a new saved profile, keeping the previous version available. A failed
database save leaves your active CV unchanged.

Unsaved builder edits stay in the current browser session when switching tabs
or navigating between screens. Save before refreshing or closing the browser.
Activating a different saved CV starts its editor from that CV's facts.

**Local CV readiness** is a 100-point content checklist: name 10, usable email
15, skills 15, experience or projects 25, supporting details 15, education 10,
and complete entries 10. Project-only applicants can satisfy it. The checklist
explains each missing item; it does not verify qualifications or measure PDF
layout. **Job skill coverage** separately reports matched/missing recognized
skills for a selected job. Repeating or reordering facts cannot improve it.
Neither number is an external ATS score or a hiring prediction. Add a skill
only when you have it.

PDF exports use bundled offline fonts and preserve links, technologies and
project impact. Unsupported glyphs or scripts needing shaping/right-to-left
layout show a clear message; Markdown and JSON remain available with the
original text. See [the CV and live-URL validation report](docs/CV_VALIDATION.md)
for tested behavior and limits.

### Save application answers and prepare autofill

With a saved CV active in **Onboarding**, open **Application details** →
**Edit application details**. Supply only the answers you want to reuse:
country-scoped work eligibility, expected pay, availability, relocation or a
cover note. **Not answered**, **Yes** and **No** are distinct; blank pay/notice
stays unknown and an explicit zero is preserved. Save the details before
downloading them. Each saved CV has its own answers; creating a new CV snapshot
starts with unanswered details, so review them again.

**Export & Logs** previews the saved fields. Expected pay takes precedence over
minimum pay; if expected pay is blank, the preview explicitly identifies the
minimum fallback. Currency and period stay as stated, with no conversion.
Unsupported numeric precision is rejected instead of silently changing pay.
Voluntary demographic answers are excluded unless you save the sharing choice.
Unsaved changes remain in the current session and are excluded from downloads.

Choose **Include my CV PDF for resume upload** to embed the active CV. If PDF
generation or the 2 MB attachment limit fails, an identity/answers-only JSON
download remains available. The JSON and PDF contain readable personal data.
Load `extension/` through Chrome's **Load unpacked**, open the downloaded JSON
and paste it into **Import from CareerAgent** in the extension popup. Open the
supported form and choose **Autofill this page**, then review every field and
submit yourself. Unsupported/ambiguous questions need manual answers; hidden
non-file fields are skipped. Opening a posting or downloading a profile does
not change its application status.

See the [product review](docs/PRODUCT_UX_REVIEW_2026-10-19.md) for browser evidence,
state behavior and remaining limits.

### Refresh safely

Committed choices recover automatically after a browser refresh: the active
saved CV, selected DB-backed jobs, contacts, preferences and last page. AI/OAuth
clients, credentials, unsent drafts and approval state do not recover. Reconnect
your chosen model when needed, and use **Re-score matches** after restoring a
CV because stored discovery scores have no CV provenance. Draft Studio resume
checks still use the active profile.

The recovery file is encrypted beside your local artifacts. If it cannot be
read, the app explains the failure and preserves it. Fix the key/storage first,
or explicitly choose **Start a new saved workspace**; this retains a private
ciphertext backup and does not remove saved CVs/jobs. Explicit ZIP exports are
readable and include workspace contacts/preferences. This is recovery for one
trusted local user, not multi-user isolation or synchronization between tabs.

### Upgrading from Python 3.9 or 3.10

These runtimes are no longer supported. Security-fixed dependencies require a
newer interpreter, and both runtimes are past end of life. Back up the database,
artifact directory and matching encryption key together; create a new Python
3.11–3.13 virtual environment, install its reviewed lock, and run
`alembic upgrade head` against the existing database. Keep the same data paths
and key. This release adds no database migration or key-format change; do not
replace a populated database or generate a replacement key during an upgrade.

## Deployment

The container and Compose configuration support local self-hosting. Shared
hosting still needs authentication, user isolation, and the security work
listed in [the audit](docs/SECURITY_AUDIT.md).

### Docker

Compose starts the app and its Ollama service on a private network:

```bash
docker compose up -d --build
docker compose exec ollama ollama pull llama3.1:8b
```

The app port is published on the host's loopback interface. The container runs
as UID 1000. A Docker-managed `careeragent-data` volume is initialized with the
correct permissions, including on a fresh clone. SQLite, encrypted artifacts,
and the generated key all live there. Back up the volume together; `docker
compose down` preserves it, while `docker compose down --volumes` deletes it.

If upgrading from the earlier `./careeragent_data` bind mount, keep that directory
and its encryption key. To continue using it, add a `compose.override.yaml` file:

```yaml
services:
  careeragent:
    volumes:
      - ./careeragent_data:/app/careeragent_data
```

That existing host directory must be writable by UID 1000. Do not start with an
empty replacement volume and assume the old records have been migrated.
Compose uses `http://ollama:11434` internally, independently of a host-local
`OLLAMA_BASE_URL` in `.env`. Gmail credentials are optional and are not mounted
by default; configure private mounts and `GMAIL_CREDENTIALS_PATH` /
`GMAIL_TOKEN_PATH` explicitly when enabling Gmail.

Build the container:

```bash
docker build -t careeragent .
docker run -p 127.0.0.1:8501:8501 careeragent
```

For a build behind a TLS-inspecting proxy, provide its trusted CA bundle as a
BuildKit secret, without disabling TLS verification or copying it into the image:

```bash
docker build --secret id=pip_ca_bundle,src=/path/to/trusted-ca-bundle.pem -t careeragent .
```

Note: For cloud deployment, ensure the Ollama instance is accessible or bundled within the container (requires significant resources).

## Platform architecture (v2, API-first)

Beyond the original outreach prototype, CareerAgent is being built into a
full, compliant job-search-and-application platform. The business logic lives
in focused `core/` packages (no business logic in the UI). See `ROADMAP.md` for
the phased plan, `docs/RESEARCH.md` for the research behind it, and `docs/adr/`
for decisions.

| Package | What it does |
|---|---|
| `core/db` | SQLModel schema, Alembic migrations, repositories, Fernet-encrypted CV payloads/contact fields/draft bodies. Some metadata remains plaintext; see the audit. SQLite for dev, Postgres target (ADR 0003). |
| `core/ingestion` | API-first job ingestion: `ats.py` company boards (Greenhouse/Lever/Ashby/SmartRecruiters/Recruitee/Workable) + `aggregators.py`/`boards.py` (Adzuna, The Muse, Remotive, Arbeitnow, Jobicy, RemoteOK, Himalayas) → canonical `JobPosting`. |
| `core/fetching` | ATS detection (regex), JSON-LD `JobPosting` extraction, robots-respecting rate-limited fetcher (scraping fallback only). |
| `core/matching` | Pluggable embeddings, fuzzy dedup, and **explainable** resume↔job scoring (matched/missing keywords). |
| `core/resume` | Model-free CV builder, explainable content readiness and job-skill coverage, JSON Resume interchange, ATS linter, selectable PDF/Markdown, truthful tailoring and cover letters. |
| `core/tracking` | Kanban application pipeline, follow-up reminders, duplicate-apply prevention, company blacklist. |
| `core/outreach` | Email verification + CAN-SPAM/GDPR compliance (postal address, opt-out, per-campaign LIA), send caps, suppression list, single pre-send gate. |
| `core/enrichment` | Salary parsing, company signals (Glassdoor/layoffs), visa-sponsor filter, ghost-job detection, filters. |
| `core/alerting` | Job digests → Markdown/RSS, Telegram/Discord delivery. |
| `core/analytics` | Application funnel, A/B variant tracking, interview-prep generation. |
| `extension/` | Manifest V3 **human-in-the-loop** autofill for Greenhouse/Lever/Ashby — fills fields, never submits. |

### Ethics guardrails (enforced in code)

- **Human-in-the-loop before every submit** — the autofill extension fills; you
  review and submit.
- **APIs over scraping** — official ATS/aggregator APIs and JSON-LD first;
  robots.txt + rate limits honored on the fallback.
- **Never fabricate** — resume tailoring is guarded by `assert_no_fabrication`.
- **Regulated outreach** — no send passes the gate without verification, a
  suppression check, a complete LIA, and a compliant footer.
- **Protected CV/contact/draft payloads encrypted at rest**, local by default;
  remaining metadata and historical exposures are listed in the audit.

### Running the platform pieces

```bash
python -m pip install --require-hashes --only-binary=:all: -r requirements/locks/test-py311.txt
alembic upgrade head                    # create the schema (SQLite by default)
python -m scripts.check                 # lint, format, types, Python coverage + extension
python -m scripts.check docker          # build + functional app/persistence/health smoke
python -m scripts.send_digest --dry-run # build a job digest
```

Node.js is required for extension tests. Select checks with `python -m
scripts.check lint test`. For Docker builds behind a trusted TLS proxy, add
`--docker-ca-bundle /path/to/trusted-ca-bundle.pem`. CI runs the same checks,
including Docker and strict dependency-advisory checks before merge. Mypy is
required and checks all repository Python files. Weekly/manual CI also tests
unconstrained upstream dependencies without modifying committed locks.
See [the current engineering review](docs/ENGINEERING_REVIEW_2026-10-17.md).

Public API smoke checks are opt-in and stay outside default tests/CI:

```bash
python -m scripts.live_url_smoke --live --output /tmp/careeragent-live-results.json
```

This reads eight fixed public job sources with request/response bounds, without
saving jobs or opening applications. It checks parsed fields and attribution;
it does not establish that every returned application page is available.

The digest command prints a preview without sending when `--dry-run` is set.
Delivery requires a complete Telegram configuration or a Discord webhook.
Invalid configuration, database failures, and rejected deliveries return a
failure status with safe diagnostics. There are no automatic delivery retries.

Set `DATABASE_URL` to a Postgres URL for production. Delivery/LLM/API keys are
read from the environment (see `.env.example`).

### Existing local artifacts

Legacy plaintext JSON remains readable. After backing up your data and keeping
the original encryption key available, explicitly encrypt those artifacts:

```bash
python - <<'PY'
from dotenv import load_dotenv
from core.storage import LocalStorage
load_dotenv()
print("Encrypted artifacts:", LocalStorage().encrypt_legacy_artifacts())
PY
```

The migration is atomic per file and repeatable. Readable exports are excluded.
Do not delete an existing key or generate a replacement when a decryption fails.

### Outreach limits

Gmail draft creation rechecks the current content and recipient, includes the
approved sender/opt-out footer, and records successful exports. The local
workflow permits 25 Gmail draft exports per day with a minimum 30-second gap;
previews do not consume that quota. SQLite serializes concurrent export checks.
The Postgres advisory-lock path requires integration validation before deployment.
The app creates drafts for human review and does not send email. It cannot limit
messages sent manually in Gmail. Unknown MX status blocks draft export until
verification can be completed.

## Project Structure

- `app.py`: Streamlit entry point and UI (calls into `core/`).
- `core/`: business-logic packages (see the table above).
- `extension/`: Manifest V3 autofill extension.
- `alembic/`: database migrations.
- `scripts/`: operational scripts (e.g. digest delivery).
- `docs/`: `RESEARCH.md`, ADRs; `ROADMAP.md` / `PROGRESS.md` at the root.

## License

MIT License.
