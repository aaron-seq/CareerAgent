# CareerAgent

A local AI-powered career assistant for personalized job outreach. This application automates the process of finding contacts, generating tailored email drafts, and managing your job search workflow using local LLMs.

## Features

- **Local-first LLM, cloud opt-in**: Ollama (Llama 3, Mistral, Qwen) by
  default for privacy-focused, zero-cost inference; Groq's free tier as an
  alternative when Ollama isn't installed (see ADR 0005 for the PII tradeoff
  this involves).
- **Job Discovery**: API-first ingestion from 13 sources — company ATS boards
  (Greenhouse/Lever/Ashby/SmartRecruiters/Recruitee/Workable) and aggregators/job boards
  (Adzuna, The Muse, Remotive, Arbeitnow, Jobicy, RemoteOK, Himalayas) — with DuckDuckGo search as a
  fallback mode.
- **Contact Finder**: Automated search for hiring managers and contact permutation generation.
- **Resume tailoring & cover letters**: Truthfully reorders/emphasizes your
  real CV content per job, and checks cover-letter metrics against it.
  Free-prose checks are heuristic; review generated claims before exporting.
- **Personalized Outreach**: Generates technical, product, or impact-focused email drafts based on your CV and the job description.
- **Quality Assurance**: Built-in validation to ensure emails meet professional standards (no fluff, concrete metrics, clear CTA).
- **Multi-Channel Support**: Creates Gmail drafts directly or generates WhatsApp click-to-chat links.
- **Guided workflow**: Reopen a saved CV, browse jobs before connecting AI,
  and open saved postings directly in Draft Studio. Drafts and resume variants
  stay with their selected job.

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

- Python 3.11 recommended (CI matrix-tests 3.9–3.11).
- An LLM provider for new CV parsing and AI drafts — either:
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
    pip install -r requirements.txt -r requirements-test.txt
    ```

3.  Set up an LLM provider — either:
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

Changing the model or provider disconnects the previous client. Initialize
the selected provider again before parsing a CV. Initialization requires the
selected model to exist; parsing failures are reported rather than saved as
empty profiles.

### Your first application

1. Browse **Job Discovery** to import a company careers page, query a job board,
   or paste a description. Browsing and saving jobs work without an AI provider.
2. In **Onboarding**, connect a model to parse a new CV, or choose **Use a saved
   CV** to reopen one locally without parsing again. Your matches refresh when
   you switch profiles; resume checks and downloads also work offline.
3. Open **Pipeline**, choose **Prepare application** on a posting, and tailor
   your resume. Connect your chosen model when you want an email or cover letter.
   Switching jobs preserves each job's edits separately.
4. Review all claims and recipients before exporting. Use the posting link and
   browser extension to fill the application, then review and submit yourself.
   **Export & Logs** provides a browser ZIP download of your local artifacts.

Each imported job shows its source and original posting link. SmartRecruiters
imports follow later pages automatically, up to 250 jobs and 20 list pages by
default. A partial-import notice identifies where to continue with the Pipeline
import controls; requests stop if a provider repeats a page.

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
| `core/resume` | JSON Resume interchange, ATS-friendliness linter, single-column PDF, **truthful** tailoring and cover-letter generation (both raise rather than fabricate an employer or metric). |
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
pip install -r requirements-test.txt   # includes runtime + test deps
alembic upgrade head                    # create the schema (SQLite by default)
python -m scripts.check                 # lint, format, Python coverage + extension tests
python -m scripts.check docker          # build + functional app/persistence/health smoke
python -m scripts.send_digest --dry-run # build a job digest
```

Node.js is required for extension tests. Select checks with `python -m
scripts.check lint test`. For Docker builds behind a trusted TLS proxy, add
`--docker-ca-bundle /path/to/trusted-ca-bundle.pem`. CI runs the same checks,
including Docker validation on pull requests before merge. Mypy remains advisory
with existing errors; see [workflow validation](docs/WORKFLOW_AUDIT.md).

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
