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

## Not verified in this environment

The field-mapping logic is unit-tested under Node. Loading in a real browser
and filling a live Greenhouse/Lever/Ashby form was **not** exercised here (no
browser/DOM in CI); that is manual QA before release.
