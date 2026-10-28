# Operations and recovery

[Overview](../README.md) | [Usage](USAGE.md) | [Dependency locks](../requirements/locks/README.md)

## Backups and exports

The app creates an ignored, mode-0600 `.careeragent_key` on its first encrypted
write unless `CAREERAGENT_ENCRYPTION_KEY` is supplied. Keep this key stable and
back it up with `careeragent.db` and `careeragent_data/`; losing it makes
encrypted data unreadable and changes suppression-list hashes. Deployment
operators can supply a managed key instead. See [`.env.example`](../.env.example) for supported
settings and [the current audit](SECURITY_AUDIT.md) for remaining risks.

ZIP exports are readable personal data, not a replacement for that backup.
They include local artifacts, saved CVs, jobs, application records and workspace
choices; application-to-CV linkage is a [known export gap](https://github.com/aaron-seq/CareerAgent/issues/71).
Protect downloaded files and remove them when no longer needed.

## Upgrading from Python 3.9 or 3.10

These runtimes are no longer supported. Security-fixed dependencies require a
newer interpreter, and both runtimes are past end of life. Back up the database,
artifact directory and matching encryption key together; create a new Python
3.11–3.13 virtual environment, install its reviewed lock, and run
`alembic upgrade head` against the existing database. Keep the same data paths
and key. Run all pending migrations; keep a backup and the original key. Do not replace
a populated database or generate a replacement key during an upgrade.

## Local deployment

The container and Compose configuration support local self-hosting. Shared
hosting still needs authentication, user isolation, and the security work
listed in [the audit](SECURITY_AUDIT.md).

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

## Database and digest commands

```bash
alembic upgrade head
python -m scripts.send_digest --dry-run
```

The digest command prints a preview without sending when `--dry-run` is set.
Delivery requires a complete Telegram configuration or a Discord webhook.
Invalid configuration, database failures, and rejected deliveries return a
failure status with safe diagnostics. There are no automatic delivery retries.

Set `DATABASE_URL` to a Postgres URL for production. Delivery/LLM/API keys are
read from the environment (see `.env.example`).

## Existing local artifacts

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

## Outreach limits

Gmail draft creation rechecks the current content and recipient, includes the
approved sender/opt-out footer, and records successful exports. The local
workflow permits 25 Gmail draft exports per day with a minimum 30-second gap;
previews do not consume that quota. SQLite serializes concurrent export checks.
The Postgres advisory-lock path requires integration validation before deployment.
The app creates drafts for human review and does not send email. It cannot limit
messages sent manually in Gmail. Unknown MX status blocks draft export until
verification can be completed.
