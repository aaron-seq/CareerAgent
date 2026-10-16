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
  value. It also answers screening questions (text, textarea, `<select>`,
  yes/no radio groups) from `profile.answers`, attaches `profile.resume` to the
  resume upload only (never a cover-letter input), and outlines every
  recognised question it could not answer in amber. Contains no submit logic
  by design; skips fields that already have a value.
- **`src/service_worker.js`** — owns the profile in `chrome.storage.local`
  (PII stays in the browser) and relays fill requests.
- **`src/popup.html` / `popup.js`** — edit the profile, import it from the
  CareerAgent app, and trigger a fill.

## Getting the profile in

Either type it into the popup, or import it from the app: CareerAgent's
**Export & Logs** screen renders a **Browser autofill profile** JSON block
built from your parsed CV (`facade.extension_profile`); paste it into the
popup's **Import from CareerAgent** box.

The handoff is deliberately a clipboard copy rather than an HTTP call to the
running app. That keeps the extension free of any host permission on the app's
origin, needs no CORS or localhost server, and means the profile never travels
over a socket — it goes clipboard → `chrome.storage.local` and stops there.
`parseImport` takes only the seven known fields plus two optional blocks, so
pasting a larger blob cannot push anything else into storage:

- `answers`: screening answers from the candidate profile
  (`facade.extension_profile(cv, candidate)`). Each key is whitelisted with its
  type (`work_authorized`, `requires_sponsorship`, `willing_to_relocate` are
  booleans; the rest strings). An absent key means unknown. The question is
  left blank and flagged rather than answered "No". Demographic keys are kept
  only with `share_demographics: true`, which the app sets only on opt-in.
- `resume`: `{filename, mime: "application/pdf", data_b64}`. It must be a PDF,
  up to 2 MB, with a sanitised filename.

`test/fixtures/candidate_profile.json` is the shared contract: the Python
tests assert the app produces it and the Node tests import it.

`location` is not in `CVProfile`; it comes from the candidate profile when one
is saved, otherwise it imports empty; fill it once in the popup and
`chrome.storage.local` keeps it. Editing the visible fields keeps imported
answers and the resume.

## Guardrails

- **Never auto-submits.** The human reviews the filled form and submits.
- **Per-site activation** via `content_scripts.matches` (not `<all_urls>`).
- **Local PII.** The profile lives in `chrome.storage.local`; nothing is sent
  anywhere by the extension.

## Develop / test

```bash
cd extension
npm test        # runs node --test on the field-mapping + import logic
```

Load unpacked in Chrome: `chrome://extensions` → Developer mode → Load
unpacked → select this `extension/` directory.

## Verification status

The field-mapping logic is unit-tested under Node (50 tests, including the
profile-import parser, screening-question rules, resume validation, and the
content script driven against a fake DOM). It has also
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

Screening-question answering (selects, radio groups), resume attachment and
the amber flags are covered only by the fake-DOM tests. They have not been
exercised in a real browser yet. React-select comboboxes are flagged, not
filled. Also still not exercised live: Ashby (`jobs.ashbyhq.com`), and the "LLM fallback"
detection layer named in `ROADMAP.md`'s Phase 8 description, which was never
actually implemented (current layers stop at placeholder fuzzy-matching,
returning no match rather than falling back to an LLM call).

This is still manual-QA-in-CI territory, not automated: `node --test` has no
browser/DOM, so the live-browser pass is not part of the regular test run.
A real user still needs to load this unpacked via `chrome://extensions` to
use it for real.
