# CareerAgent Autofill (Manifest V3)

Human-in-the-loop autofill for job application forms. It fills fields from a
locally-stored profile; **you review and click submit**. It never submits a
form for you, and it only activates on the supported ATS domains
(Greenhouse, Lever, Ashby).

## Design

- **`src/field_mapping.js`** — pure, dependency-free field-detection logic
  (the tested core). Layered detection: `autocomplete` attribute → input type →
  ARIA/label → name/id fuzzy → placeholder.
- **`src/content_script.js`** — reads visible inputs, maps them, and fills them,
  dispatching `input`/`change` events so React-based ATS forms register the
  value. Contains no submit logic by design; skips fields that already have a
  value.
- **`src/service_worker.js`** — owns the profile in `chrome.storage.local`
  (PII stays in the browser) and relays fill requests.
- **`src/popup.html` / `popup.js`** — edit the profile and trigger a fill.

## Guardrails

- **Never auto-submits.** The human reviews the filled form and submits.
- **Per-site activation** via `content_scripts.matches` (not `<all_urls>`).
- **Local PII.** The profile lives in `chrome.storage.local`; nothing is sent
  anywhere by the extension.

## Develop / test

```bash
cd extension
npm test        # runs node --test on the field-mapping logic
```

Load unpacked in Chrome: `chrome://extensions` → Developer mode → Load
unpacked → select this `extension/` directory.

## Verification status

The field-mapping logic is unit-tested under Node (13 tests). It has also
been **live-verified**: loaded unpacked into real Chromium via Playwright's
`launchPersistentContext` + `--load-extension`, with a profile seeded through
the real popup, against actual live job postings —
`job-boards.greenhouse.io` (Anthropic) and `jobs.lever.co` (Immutable). It
correctly detected and filled name/email/phone/location/LinkedIn/GitHub/
portfolio fields on both, dispatched React-visible `input`/`change` events,
and never touched the submit button. That pass also found and fixed two real
bugs (see git history around this note): a short-keyword false match ("tel"
inside "Constellation") and an overly-generic "url" keyword stealing
unrelated fields ("Twitter URL"); both now have regression tests.

Still not exercised live: Ashby (`jobs.ashbyhq.com`), and the "LLM fallback"
detection layer named in `ROADMAP.md`'s Phase 8 description, which was never
actually implemented (current layers stop at placeholder fuzzy-matching,
returning no match rather than falling back to an LLM call).

This is still manual-QA-in-CI territory, not automated: `node --test` has no
browser/DOM, so the live-browser pass is not part of the regular test run.
A real user still needs to load this unpacked via `chrome://extensions` to
use it for real.
