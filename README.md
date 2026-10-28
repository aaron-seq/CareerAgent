# CareerAgent

A local career workspace for building a truthful CV, finding jobs, preparing
application materials and tracking follow-ups. AI assistance and contact
discovery are optional. The browser extension fills supported forms for your
review; you submit them yourself.

[Usage](docs/USAGE.md) · [Operations and recovery](docs/OPERATIONS.md) ·
[Architecture](ARCHITECTURE.md) · [Contributing](CONTRIBUTING.md) ·
[Roadmap](ROADMAP.md) · [Current status](PROGRESS.md)

<a id="prerequisites"></a>
<a id="installation"></a>

## Getting started

Use Python 3.11–3.13. Node.js is required for extension tests. Create and
activate a virtual environment, then install dependencies:

```bash
git clone https://github.com/aaron-seq/CareerAgent.git
cd CareerAgent
python -m venv .venv
source .venv/bin/activate  # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --require-hashes --only-binary=:all: \
  -r requirements/locks/test-py311.txt
streamlit run app.py
```

The reviewed locks target Linux x86_64: select `312` or `313` for your Python
minor, or `runtime-py311.txt` for an app-only install. On other platforms,
install `requirements-test.txt` in the virtual environment and validate that
resolved graph. See [lock scope and refresh](requirements/locks/README.md).

CV building, job browsing, deterministic tailoring and exports work without AI.
For AI parsing/drafting, install and start Ollama, then run
`ollama pull llama3.1:8b`. Alternatively, copy `.env.example` to `.env` and set
`GROQ_API_KEY`; choosing Groq sends prompt/CV content off-machine
([provider trade-off](docs/adr/0005-cloud-llm-provider-for-pii-work.md)).
Choose **Connect AI** in the sidebar's **AI settings** after selecting a model.
Changing the model/provider disconnects the previous client.

<a id="features"></a>

## Your first application

1. Browse **Job Discovery** to import a careers page, query a board or paste a
   description. Each imported job keeps its source and posting link.
2. In **Onboarding**, build a CV from your own facts, restore a saved CV, or
   connect AI to import PDF/text. Saves create distinct profile snapshots.
3. In **Pipeline**, choose **Prepare application**. Drafts and resume variants
   stay with their selected job. Contacts are optional.
4. Review all claims, recipients and saved answers before downloading materials.
   Use the [extension](extension/README.md) for supported forms, then review and
   submit yourself. Gmail integration creates drafts; it does not send mail.

See [usage](docs/USAGE.md) for CV readiness, saved application answers, optional
PDF autofill and refresh recovery.

## Privacy and limitations

- Keep `.careeragent_key` (or the configured key), `careeragent.db` and
  `careeragent_data/` together in backups. Losing the key makes encrypted data
  unreadable and changes suppression hashes. See [recovery and upgrades](docs/OPERATIONS.md).
- Explicit JSON/PDF/Markdown/ZIP downloads contain readable personal data.
  Some database metadata remains plaintext; this is a workspace for one trusted
  local user. Shared hosting requires additional controls; see the
  [security audit](docs/SECURITY_AUDIT.md) and [open prerequisites](https://github.com/aaron-seq/CareerAgent/issues/41).
- Readiness/skill checks are local heuristics, not ATS scores or hiring
  predictions. Review generated claims and uncertain contact addresses.
- Restored discovery scores lack CV provenance: explicitly **Re-score matches**.
  [Known workflow gaps](https://github.com/aaron-seq/CareerAgent/issues/77) and
  [validation limits](docs/CV_VALIDATION.md) remain tracked.

<a id="running-the-platform-pieces"></a>

## Checks

```bash
python -m scripts.check        # lint, format, types, Python coverage, extension
python -m scripts.check docker # optional container build and functional smoke
```

Tests mock application integrations. See [contributing](CONTRIBUTING.md) for
selected checks and [published engineering evidence](docs/ENGINEERING_REVIEW_2026-10-19.md)
for results at their recorded revisions.

## Detailed guides

<a id="build-a-cv-and-improve-its-readiness"></a>
<a id="save-application-answers-and-prepare-autofill"></a>
<a id="refresh-safely"></a>

- [CV builder, application answers, autofill and refresh](docs/USAGE.md).

<a id="upgrading-from-python-39-or-310"></a>
<a id="deployment"></a>
<a id="docker"></a>
<a id="existing-local-artifacts"></a>
<a id="outreach-limits"></a>

- [Docker, upgrades, backups, legacy encryption and outreach limits](docs/OPERATIONS.md).

<a id="technical-architecture"></a>
<a id="platform-architecture-v2-api-first"></a>
<a id="project-structure"></a>
<a id="ethics-guardrails-enforced-in-code"></a>

- [Component contracts and design decisions](ARCHITECTURE.md),
  [ADRs](docs/adr/) and [historical research](docs/RESEARCH.md).
- [Product/browser evidence](docs/PRODUCT_UX_REVIEW_2026-10-19.md) and
  [workflow evidence](docs/WORKFLOW_AUDIT.md).
- [Issues](https://github.com/aaron-seq/CareerAgent/issues),
  [maintenance Project](https://github.com/users/aaron-seq/projects/7) (private)
  and [current milestone](https://github.com/aaron-seq/CareerAgent/milestone/1).

## License

[MIT](LICENSE). Bundled font notices remain in [assets/fonts/LICENSE.txt](assets/fonts/LICENSE.txt).
