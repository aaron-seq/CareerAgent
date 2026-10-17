# 10. Build CVs from explicit facts and explain local readiness

- Status: Accepted
- Date: 2026-10-17

## Context

Creating a profile required model-based extraction even when a candidate could
enter their facts directly. Exports omitted some stored links/technologies and
the PDF renderer replaced unsupported characters. An opaque ‘ATS score’ would
suggest vendor validation the application cannot provide.

## Decision

- Validate builder input in `core/resume/builder.py` through the facade. No
  model or network is involved. Preserve literal dates, metrics and claims;
  clear stale raw extraction text when the user replaces profile facts.
- Save a new encrypted profile before activating it. Retain older versions;
  a failed primary save leaves the active profile and its materials unchanged.
- Present a fixed, documented 100-point content-completeness checklist beside
  separate exact recognized-skill coverage. Neither estimates an ATS vendor's
  ranking. Projects count as evidence without requiring an employer or metrics.
- Skill evidence excludes raw extracted text and identity/contact/employer
  fields. Explicit aliases and punctuation boundaries avoid substring matches.
  Clearly negated English clauses abstain; ambiguous language and proficiency
  still require human judgment. No inferred gaps become candidate facts.
- Share export content between PDF and Markdown. Bundle licensed DejaVu fonts
  for offline selectable text. Reject unsupported text with a useful error;
  retain lossless Markdown/JSON downloads. Preserve secondary project repository
  URLs using the JSON Resume `x-github` extension.
- Keep live public API checks explicitly opt-in, bounded, and independent of
  mocked CI tests. Save public metadata evidence, never candidate data.

## Consequences and rollback

No new runtime package, schema migration or service is required. Font assets add
about 1.4 MB. The checklist measures completeness rather than quality of writing,
layout, verified proficiency or hiring outcomes. English lexical coverage cannot
understand every qualified/negated claim or nontechnical role. PDF shaping and
right-to-left scripts are outside this renderer's support; plain-text downloads
remain available. Builder limits are 30 work records and 30 projects; oversized
existing profiles remain exportable and are not silently truncated.

Revert this feature to remove the builder/checklist and use previous rendering.
Saved `CVProfile` records remain readable by earlier code. Keep database/data
backups with their encryption key.
