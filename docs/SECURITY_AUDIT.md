# CareerAgent engineering and security audit

Date: 2026-10-15. Baseline: `2b33fcb` on `main`; findings below distinguish the
implemented hardening from remaining work. This is a fresh evidence-based audit,
not a reconstruction of the missing older document referenced by the progress log.

## Objective and review scope

CareerAgent is a local-first assistant for individual job discovery, truthful
application materials, application tracking, and human-reviewed outreach. Preserve
Python/Streamlit, the existing core services, SQLite development, optional cloud
inference, API-first ingestion, and the autofill extension's refusal to submit.
Production hardening should make those workflows reliable rather than add a new
framework, paid service, queue, vector database, or speculative abstraction.

Inspected the application, core modules, persistence/schema/migrations, LLM
prompts and clients, extension, scripts, requirements, CI, Docker, architecture,
ADRs, progress/roadmap, Git history, and GitHub's 21 initially open issues. There
were no open PRs to consolidate. GitHub issue references below avoid duplicating
existing work. No real personal data, OAuth credentials, email, or notifications
were used for regression tests.

## Prioritized findings and disposition

| Priority | Finding and evidence | Disposition |
| --- | --- | --- |
| Critical | Eleven parsed CV profiles remain reachable in the initial public Git history. Removing them from the current tree did not remove earlier objects. Contents were not printed or copied. | **Owner action required: [#38](https://github.com/aaron-seq/CareerAgent/issues/38).** No history rewrite or force-push was performed. |
| High | `app.py` reset compliance approval on every rerun, so clicking Gmail after a successful preview lost approval. It also passed the original body instead of the approved footer-bearing body. | **Fixed.** Gmail creation lives behind `facade.create_gmail_draft`, rechecks current content/recipient/suppression, exports the approved body, and records the result. Real Streamlit rerun regressions use a fake Gmail boundary. |
| High | The default outreach policy was recreated empty on every call; successful operations were never counted, and the minimum interval was unused. | **Fixed for app-created Gmail drafts, [#34](https://github.com/aaron-seq/CareerAgent/issues/34).** Successful export records rebuild the daily window; the final check/export/record is serialized. SQLite concurrency is tested; Postgres advisory locking is implemented but not integration-tested. This does not control mail sent manually. |
| High | Unknown MX status passed `require_mx=True`; resolver exceptions conflated timeout with confirmed absence. Null MX was also treated as a usable record. | **Fixed, [#14](https://github.com/aaron-seq/CareerAgent/issues/14).** Unknown blocks required verification; timeouts remain unknown, missing/null MX fails, and dnspython is a declared runtime dependency. Live Gmail OAuth remains unverified. |
| High | A footer marker, postal address, and URL could pass without the configured sender. Whitespace fields and unusable opt-out schemes passed validation. | **Fixed.** Require the complete configured footer and usable sender/HTTP(S)/mailto syntax. This checks technical fields, not legal adequacy of a campaign. |
| High | When no environment key existed, each process generated a new key, making durable records unreadable and opt-out hashes inconsistent after restart. | **Fixed.** Explicit environment key wins; otherwise publish and reuse a private local key atomically. Cross-process and replacement-container tests verify decryption and stable hashes. Keep the same key with backups. |
| High | Legacy JSON writers saved CV/draft PII in plaintext despite DB encryption. Filename interpolation allowed path components and same-second writes overwrote records; reads accepted traversal paths. | **Fixed for new writes.** Authenticated encrypted payloads, private unique files, contained reads, compatible legacy imports, and explicit repeatable legacy encryption. Markdown/ZIP exports are intentionally readable and the UI says so. Existing plaintext needs explicit migration. |
| High | Changing the displayed LLM provider/model left the old client active, so selecting local inference could still leave a cloud client receiving CV text. Environment-configured Ollama URLs/models were ignored. | **Fixed.** Disconnect on selection changes, honor deployment defaults, and require model availability before initialization succeeds. Cloud use remains a visible per-session choice. |
| High | The metric guard removed punctuation and concatenated all CV/JD digits. A CV with `99.5%` and `2020-2024` accepted invented `995%`, `20%`, and `5%`; invisible JD suffixes could also ground output. | **Fixed numeric boundary defects.** Compare complete numbers plus units and preserve decimals; only visible JD metrics with explicit job attribution can be quoted. Arbitrary prose remains heuristic and requires human review. |
| High | Resume validation checked only skills and employer/title pairs, accepting invented achievements, metrics, duration, education, identity, and summary. Tailoring itself synthesized a new summary. | **Fixed.** Only reorder existing skills and whole unchanged experiences; keep other candidate facts unchanged. |
| High | Failed LLM extraction returned an empty valid CV, which downstream code persisted as success. Uploaded CV temporary files used the supplied filename and were left behind after failure. | **Fixed, [#18](https://github.com/aaron-seq/CareerAgent/issues/18).** Failed/empty extraction raises, and private temporary uploads are always removed. Storage failures are visible instead of silently ignored. |
| High | Docker copied the entire checkout, including possible secrets/data, ran as root, required optional credentials, and configured an Ollama address ignored by the app. SQLite/key state was not persisted together. | **Fixed local deployment portion of [#24](https://github.com/aaron-seq/CareerAgent/issues/24).** Add `.dockerignore`, non-root runtime, optional credentials, service-name routing, loopback publication, and persistent data/key paths. Package/Actions supply-chain work remains. |
| Medium | Missing GitHub secret values become empty environment strings. Empty `DATABASE_URL` bypassed SQLite fallback and broke the documented digest dry-run. | **Fixed local reproduction related to [#25](https://github.com/aaron-seq/CareerAgent/issues/25).** Dry-run now works with an empty URL. Latest remote runs still fail; their failed step is known, but downloadable logs were denied, so the remote failure's full cause is not established. |
| Medium | `.env.example` advertised search/generation/quality/debug variables the implementation never read. OAuth files were not Git-ignored, and token writes used default file permissions. | **Fixed.** Document supported settings, remove inactive placeholders, ignore OAuth files, honor configured credential paths, and atomically write private tokens. |

## Root causes and engineering review

The recurring cause is an invariant tested below the layer where the product
actually uses it. Unit tests verified a footer-producing service but not the
Gmail action; a local in-memory policy but not repeated facade calls; an encrypted
database column but not the parallel JSON store; and a subset guard that discarded
fact boundaries. Passing 338 baseline tests therefore did not establish these
user-visible guarantees.

The smallest suitable change reuses `core/db/crypto.py`, existing repositories,
the facade, and existing validators. It does not introduce another orchestration
layer. Streamlit remains presentation; the Gmail side effect and quota transaction
move into the facade. The older direct CV/contact/personalization/storage paths
remain an architectural consistency issue ([#12](https://github.com/aaron-seq/CareerAgent/issues/12)).

Known facts, unknowns, assumptions, success criteria, root-cause analysis,
alternatives, security/dependency/performance/scalability review, testing strategy,
risks, and rollback were recorded before implementation. The accepted decisions
and consequences are in [ADR 0006](adr/0006-persistent-local-data-and-gated-exports.md).

## Validation and practical limits

| Check | Result |
| --- | --- |
| Existing baseline | 338 Python tests, 18 extension tests, lint/format passed. |
| Added boundary regressions | Demonstrated failures before fixes for key restart, plaintext/traversal/overwrite, parsing, metrics, resume facts, MX/footer validation, Streamlit approval reruns, ignored Ollama settings, missing model initialization, quotas, and empty DB URL. |
| Full Python suite | **377 passed**; no skips or expected failures. |
| Core coverage | **92.48%**, versus **92.07%** baseline; coverage is not a readiness guarantee. |
| Extension | **18 passed**; browser/autofill implementation unchanged. |
| Static checks | Ruff lint, format, compile checks, and `git diff --check` pass. Installed dependency compatibility check passes. |
| Mypy | **32 advisory errors** with `--python-version 3.11`, down from 33 baseline; remaining typing/stub problems are not a passing gate. Default target/pinned-tool compatibility remains [#22](https://github.com/aaron-seq/CareerAgent/issues/22). |
| SQLite | Migrations, repeatability, encrypted import, persistent key/hash, quota restart, and simultaneous Gmail creation checks pass. |
| Streamlit | Actual AppTest execution covers navigation, provider disconnect, unavailable model, Gmail rerun/footer, and opt-out after preview. Gmail/DNS boundaries are mocked. |
| Docker | Build passes with normal TLS verification and optional CA secret. Verified non-root UID, imports, excluded Git/data/secrets, AppTest UI, and data/key continuity across container replacement. Compose config validates. |
| External services | A live Arbeitnow fetch parsed 300 jobs during onboarding. Actual model inference is still blocked by model-download access; no real Gmail OAuth/delivery, Postgres, or real-browser extension round-trip was validated. |
| Remote CI | Inspected latest digest failures and annotations. Log download access was denied; no claim that the scheduled workflow is repaired or the new changes passed remote CI. |

The container package-install step initially failed because the cloud proxy's CA
was not in the base image. Rebuilt successfully with the trusted CA bundle mounted
using BuildKit's secret mechanism. No TLS/signature/checksum verification was
disabled, and no CA bundle or credential was copied into the image.

### Measured storage baseline

On this shared x86-64 cloud environment, 200 saves and loads of an 8,000-byte
synthetic body measured:

| Operation | Median | p95 |
| --- | --- | --- |
| Unique encrypted save | 0.135 ms | 0.296 ms |
| Contained read/decrypt/validation | 0.153 ms | 0.280 ms |

This includes ordinary file I/O, serialization, and encryption. It is a small
local baseline, not a load test, power-loss durability test, or comparison proving
a speedup. Model latency, large-board ingestion, memory growth, multi-user load,
and end-to-end deployment performance were not benchmarked.

## Remaining risks and issue backlog

Do not describe this project as production-ready on the strength of these checks.

- **Public history:** owner-led cleanup and GitHub cache/PR-ref handling, [#38](https://github.com/aaron-seq/CareerAgent/issues/38). Treat historical data as already exposed; do not copy it into issues or logs.
- **Hosted fetch boundary:** arbitrary job URLs need private/reserved address and redirect/rebinding controls before remote hosting, [#41](https://github.com/aaron-seq/CareerAgent/issues/41). A mock transport confirmed that the current polite fetcher reaches a metadata-IP request boundary; no real internal request was made.
- **Database metadata:** names, profile URLs, summaries, subjects, and notes are not all encrypted; require a deliberate compatible data migration, [#42](https://github.com/aaron-seq/CareerAgent/issues/42). New JSON encryption does not repair old backups or all DB metadata.
- **Semantic grounding:** a supported number can still be attributed to the wrong achievement; employer/credential detection is heuristic. Preserve human review and add evidence-oriented evaluation, [#43](https://github.com/aaron-seq/CareerAgent/issues/43).
- **Deployment:** local single-user behavior is the supported scope. Authentication, user isolation, Postgres lock/driver integration, and remote rollout remain unverified. A successful Gmail API call followed by a DB commit failure is not a distributed exactly-once transaction.
- **Supply chain:** no new advisory feed/security scanner was run; this is not a clean dependency-vulnerability attestation. Lock/constraints work is [#39](https://github.com/aaron-seq/CareerAgent/issues/39), remaining action pinning/scanning is [#24](https://github.com/aaron-seq/CareerAgent/issues/24), and timezone modernization is [#37](https://github.com/aaron-seq/CareerAgent/issues/37). Latest digest annotations report deprecated Node action runtimes and an upcoming runner image change.
- **Feature accuracy:** matching quality [#10](https://github.com/aaron-seq/CareerAgent/issues/10), per-posting attribution [#19](https://github.com/aaron-seq/CareerAgent/issues/19), pagination [#20](https://github.com/aaron-seq/CareerAgent/issues/20), A/B tracking [#35](https://github.com/aaron-seq/CareerAgent/issues/35), logging [#31](https://github.com/aaron-seq/CareerAgent/issues/31), and live extension/OAuth checks remain separately tracked. These were not represented as fixed.

## Migration, operation, and rollback

1. Back up `careeragent.db`, `careeragent_data/`, and the **same** encryption key.
   Set `CAREERAGENT_ENCRYPTION_KEY` consistently, or retain `.careeragent_key` /
   `CAREERAGENT_KEY_PATH`. Do not regenerate a key to suppress a decryption error.
2. New artifacts use a versioned Fernet JSON envelope. Legacy plaintext remains
   readable and can be explicitly migrated with `LocalStorage.encrypt_legacy_artifacts()`
   after loading `.env`; see README. Each replacement is atomic and repeatable.
3. Explicit exports contain readable PII. Keep old plaintext backups and exports
   in user-controlled storage and handle their deletion separately.
4. Compose persists DB/key under `careeragent_data/` and runs as UID 1000. Preserve
   any old database before changing layouts; do not replace an existing populated
   database with a newly created empty one. Confirm host directory ownership.
5. Roll source changes back together if needed, but **retain keys and encrypted
   data**. Older code cannot read the new JSON envelope directly; use a readable
   export or restore the matching pre-upgrade backup. Rollback must not discard
   records, change a working key, or rewrite public history.

## Primary references

- Installed Streamlit `st.button` documentation: click state is true for the
  click's run and false otherwise; actual rerun tests validate the consequence.
- [Fernet key handling and authenticated encryption](https://github.com/pyca/cryptography/blob/main/docs/fernet.rst).
- [dnspython resolver behavior](https://github.com/rthalley/dnspython/blob/main/doc/resolver-class.rst).
- [Docker Compose service discovery](https://github.com/docker/docs/blob/main/content/manuals/compose/how-tos/networking.md).
- [Docker build context exclusions](https://github.com/docker/docs/blob/main/content/manuals/build/concepts/context.md).
- [Docker build secrets](https://github.com/docker/docs/blob/main/content/manuals/build/building/secrets.md).
