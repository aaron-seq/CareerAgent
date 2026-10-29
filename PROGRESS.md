# Project status and continuation

Last verified: 2026-10-29 (Asia/Kolkata). Current work is
[issue #88](https://github.com/aaron-seq/CareerAgent/issues/88), branch
`feature/88-ats-resume-editor`, based on main at
[`d06cee0`](https://github.com/aaron-seq/CareerAgent/commit/d06cee0839f731fadb90a2a9434e0c0c6d4225af).
The [private Project](https://github.com/users/aaron-seq/projects/7) and
[milestone 2](https://github.com/aaron-seq/CareerAgent/milestone/2) track review.
The issue links the draft PR and final-head checks. Merge/deployment is pending.

## Resume editor

- Onboarding's existing builder now previews unsaved facts beside the form.
  Previewing does not activate/save a CV, call AI or invalidate application
  materials. Edits hide outdated exports; switching/saving a CV clears preview.
- PDF uses the existing factual renderer and Streamlit's local PDF viewer.
  Plain text, escaped LaTeX and PDF/Markdown/JSON/Overleaf ZIP downloads use the
  same facts. Saved and tailored exports have separate labels and ZIPs.
- ZIPs include `main.tex`, existing licensed fonts and import instructions.
  XeLaTeX source wraps long tokens and retains paragraphs/extractable spaces.
  CareerAgent executes no TeX; Overleaf upload is manual. Review fonts/layout
  for unsupported scripts. [Usage](docs/USAGE.md#build-a-cv-and-improve-its-readiness)
  owns the user instructions.
- Only `streamlit-pdf` 2.1.0 was added to the six Linux runtime/test locks; all
  prior pins/hashes are preserved. No migration or credential changes.

## Validation and limits

- Red/green checks covered missing preview controls, missing-font fallbacks,
  explicit paragraphs and long-token wrapping. Focused editor/save/export
  regressions and current lint/type results are recorded in #88's PR.
- Personally compiled synthetic ZIP exports with Tectonic 0.17.0 (XeTeX):
  one-page, five-page/30-role and empty documents. Inspected rendered pages;
  pypdf and pdfplumber retained facts, links, symbols, Unicode and section order.
  No overfull boxes, missing glyphs or content outside margins in those fixtures.
- Personally checked Chromium at 1440px and 390px: visible PDF canvas, stale
  download suppression and ZIP download. Preview/export made no external
  requests. This was local testing, not an Overleaf account or ATS service test.
- Agent-run strict pip-audit 2.10.1 passed all three hashed test graphs with
  zero advisory rows/skips (97/96/96 distributions); lock tests passed. Delegated
  review is a system perspective, not independent human approval.
- Windows' correct Python 3.11 graph cannot collect DB tests because Application
  Control blocks SQLAlchemy's native DLL. A secret-free alternate local graph
  was used for UI tests with a test-only offline embedding provider. Its broad
  run had 938 passes and ten failures, all reproduced on pristine `849c0d8`:
  POSIX modes, symlink privileges and failed-fsync temporary-file cleanup.
  Final Linux matrix/Docker checks, rather than that alternate graph, validate
  the frozen dependencies. Local Docker's Linux daemon remains unavailable.

## Prior work and continuation

[Cleanup PR #86](https://github.com/aaron-seq/CareerAgent/pull/86) is merged;
issues #85/#87 and milestone 1 are closed. Its
[post-merge CI](https://github.com/aaron-seq/CareerAgent/actions/runs/40828273105)
passed. The [previous checkpoint](https://github.com/aaron-seq/CareerAgent/blob/d06cee0839f731fadb90a2a9434e0c0c6d4225af/PROGRESS.md)
retains cleanup measurements, older reviews and open follow-ups. Original local
audit, credentials, databases and personal files remain untouched.

1. Read #88 and its draft PR; verify branch/HEAD, working tree and current checks.
2. Resolve introduced CI/review failures. Keep #88/milestone 2 open for review;
   no merge, deployment or live-provider tests are implied.
3. Existing security prerequisites #38/#41/#42, dormant helpers #35, product
   findings #65–#78 and overlapping/dependency PRs #76/#79–#84 remain separate.
   Reconcile their useful changes without discarding security-fixed locks.

Rollback is the feature diff and its one added dependency; no data migration.
Keep the security updates already merged in #86.
