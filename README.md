# CareerAgent

A local AI-powered career assistant for personalized job outreach. This application automates the process of finding contacts, generating tailored email drafts, and managing your job search workflow using local LLMs.

## Features

- **Local-first LLM, cloud opt-in**: Ollama (Llama 3, Mistral, Qwen) by
  default for privacy-focused, zero-cost inference; Groq's free tier as an
  alternative when Ollama isn't installed (see ADR 0005 for the PII tradeoff
  this involves).
- **Job Discovery**: API-first ingestion (Greenhouse/Lever/Ashby, Adzuna, The
  Muse, Remotive) with DuckDuckGo search as a fallback mode.
- **Contact Finder**: Automated search for hiring managers and contact permutation generation.
- **Resume tailoring & cover letters**: Truthfully reorders/emphasizes your
  real CV content per job, and drafts cover letters grounded in it — both
  raise rather than invent an employer, credential, or metric you don't have.
- **Personalized Outreach**: Generates technical, product, or impact-focused email drafts based on your CV and the job description.
- **Quality Assurance**: Built-in validation to ensure emails meet professional standards (no fluff, concrete metrics, clear CTA).
- **Multi-Channel Support**: Creates Gmail drafts directly or generates WhatsApp click-to-chat links.

## Technical Architecture

The application is built with a modern Python stack:

- **Frontend**: Streamlit for a responsive, interactive UI.
- **LLM Orchestration**: Custom Python client interacting with Ollama API.
- **Data Parsing**: PyPDF2 and PDFPlumber for robust CV extraction.
- **Search**: DuckDuckGo Search API for real-time contact and job data.
- **Storage**: Local filesystem storage with JSON serialization for privacy.

## Getting Started

### Prerequisites

- Python 3.9 or higher (CI matrix-tests 3.9-3.11; also verified working
  directly on 3.13 with no venv, see `CLAUDE.md`)
- An LLM provider — either:
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

## Deployment

The application is container-ready and supports deployment on platforms like Railway, Render, or Vercel (using docker).

### Docker

Build the container:

```bash
docker build -t careeragent .
docker run -p 8501:8501 careeragent
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
| `core/db` | SQLModel schema, Alembic migrations, repositories, **PII encrypted at rest** (Fernet). SQLite for dev, Postgres in prod (ADR 0003). |
| `core/ingestion` | API-first job ingestion: Greenhouse/Lever/Ashby public feeds + Adzuna/The Muse/Remotive → canonical `JobPosting`. |
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
- **PII encrypted at rest** and kept local by default.

### Running the platform pieces

```bash
pip install -r requirements-test.txt   # includes runtime + test deps
export CAREERAGENT_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
alembic upgrade head                    # create the schema (SQLite by default)
pytest                                  # 204+ Python tests (see PROGRESS.md for current count)
(cd extension && node --test)           # 11 extension tests
python -m scripts.send_digest --dry-run # build a job digest
```

Set `DATABASE_URL` to a Postgres URL for production. Delivery/LLM/API keys are
read from the environment (see `.env.example`).

## Project Structure

- `app.py`: Streamlit entry point and UI (calls into `core/`).
- `core/`: business-logic packages (see the table above).
- `extension/`: Manifest V3 autofill extension.
- `alembic/`: database migrations.
- `scripts/`: operational scripts (e.g. digest delivery).
- `docs/`: `RESEARCH.md`, ADRs; `ROADMAP.md` / `PROGRESS.md` at the root.

## License

MIT License.
