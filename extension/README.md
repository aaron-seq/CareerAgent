# CareerAgent Autofill (Manifest V3)

Autofill for Greenhouse, Lever and Ashby application forms. The extension fills
from a local profile; **you review every field and click submit**. Activation
is limited by `content_scripts.matches`; it has no submit logic.

## Getting the profile in

Follow [save application answers and prepare autofill](../docs/USAGE.md#save-application-answers-and-prepare-autofill)
to download reviewed JSON from **Export & Logs** and paste it into the popup's
**Import from CareerAgent** box. You can also edit identity fields in the popup.
The handoff uses a file/clipboard, with no app-origin host permission, CORS
endpoint or localhost server. The imported profile stays in
`chrome.storage.local`; the extension makes no outbound API calls.

## Import contract

`src/popup.js`'s `parseImport` accepts only `fullName`, `email`, `phone`,
`linkedin`, `github`, `portfolio`, `location` and two optional blocks:

- `answers`: known keys with validated types. Missing means unknown, not "No".
  Demographics require `share_demographics: true`. Eligibility answers retain
  the candidate's country; filling requires the same recognized country and
  supported positive wording. Missing/unfamiliar countries, inverted or compound
  questions remain amber for human review. A city or visa name supplies no
  missing authorization context.
- `resume`: `{filename, mime: "application/pdf", data_b64}`, validated as a PDF
  of at most 2 MB with a sanitized filename. Only the resume input is eligible,
  never a cover-letter input.

`location` comes from saved application details, otherwise it imports empty.
Editing the seven visible fields preserves imported answers and resume. The
[shared fixture](test/fixtures/candidate_profile.json) is checked by Python
export tests and Node import tests.

<a id="design"></a>
<a id="guardrails"></a>

## Design and guardrails

- `src/field_mapping.js`: dependency-free detection through autocomplete, input
  type, ARIA/label, name/id and placeholder. No LLM fallback is implemented.
- `src/content_script.js`: fills supported visible text/select/radio questions,
  dispatches `input`/`change`, and flags unanswered recognized questions amber.
  Existing values and real selected choices are preserved; React-select
  comboboxes are flagged for manual input.
- `src/service_worker.js`: owns local profile storage and relays fill requests.
  `src/popup.html` / `popup.js` edit/import the profile and trigger a fill.

## Develop / test

```bash
cd extension
npm test        # node --test; no dependency installation needed
```

In Chrome, open `chrome://extensions` → Developer mode → Load unpacked →
select this `extension/` directory.

## Verification status

The [historical extension report](https://github.com/aaron-seq/CareerAgent/blob/2ceaf85145a146ca9b4616b16f5c37bbab38b32c/extension/README.md#verification-status)
records real Chromium/Playwright checks on Greenhouse (Anthropic) and Lever
(Immutable): identity fields, React-visible events and no submit interaction.
That is a reported historical check, not a new live test of the current build.

Screening selects/radios, resume attachment and amber flags have fake-DOM test
coverage. The later [Chromium DOM evidence](../docs/validation/ux-2026-10-19/extension-dom.json)
uses injected scripts on a synthetic page, not employer forms or the extension
service worker. Ashby remains unverified live ([#13](https://github.com/aaron-seq/CareerAgent/issues/13)).
Regular Node CI does not run a real browser or employer application. Review
[open autofill issues](https://github.com/aaron-seq/CareerAgent/issues?q=is%3Aopen+autofill)
before relying on a filled answer.
