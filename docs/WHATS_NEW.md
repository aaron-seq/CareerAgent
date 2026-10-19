# CareerAgent

[Overview](../README.md) · **What's new** · [Architecture](../ARCHITECTURE.md) · [Progress log](../PROGRESS.md) · [Security audit](SECURITY_AUDIT.md) · [Roadmap](../ROADMAP.md)

---

## What's new — 14–19 October 2026

This release lets you build a CV, save application details, find and track
jobs, and export everything **without an AI model**. Drafting outreach emails
and cover letters still needs one. It also makes your work survive a browser
refresh, and hardens autofill, logging and dependencies. Most changes were driven by a real-user
test: a browser driven as a first-time job seeker, offline, with no model
connected. Every change below shipped through a reviewed pull request with
tests.

**Contents:** [For job seekers](#for-job-seekers) ·
[Autofill extension](#autofill-extension) ·
[Privacy and security](#privacy-and-security) ·
[For developers](#for-developers) · [Upgrading](#upgrading) ·
[Known limits](#known-limits)

---

### For job seekers

**Build your CV without AI** ([#53](https://github.com/aaron-seq/CareerAgent/pull/53), [#64](https://github.com/aaron-seq/CareerAgent/pull/64))
Before this, the only ways to create a profile were AI parsing or a profile
saved by an earlier parse, so a first-time user without Ollama or a Groq key
couldn't get started. **Onboarding** now opens on **Build or edit a CV**, where
you type in your own facts; **Import PDF or text** is there when a model is
connected.
- Edits save as a new snapshot, so earlier versions stay available.
- **CV readiness** is a 100-point checklist that explains every missing item.
  It is separate from **job skill coverage** for a selected job. Neither is an
  ATS score or a hiring prediction.
- PDF export uses bundled offline fonts, so it needs no network.

**Application details, saved once and reused** ([#51](https://github.com/aaron-seq/CareerAgent/pull/51), [#64](https://github.com/aaron-seq/CareerAgent/pull/64))
Store the answers job forms keep asking for, per saved CV and encrypted at
rest:
- country-scoped right to work and sponsorship;
- expected and minimum pay;
- notice period and start date;
- relocation;
- a default cover note;
- opt-in diversity answers.

**Not answered**, **Yes** and **No** are three different answers: anything you
skip stays unknown and is never guessed.

**Your work survives a refresh** ([#54](https://github.com/aaron-seq/CareerAgent/pull/54))
The active CV, selected jobs, contacts, preferences and current page now come
back after a browser refresh. They're restored from a small encrypted local
workspace. Unsent drafts, credentials and AI connections are deliberately not
restored. (Fixes [#48](https://github.com/aaron-seq/CareerAgent/issues/48).)

**Better job matching** ([#52](https://github.com/aaron-seq/CareerAgent/pull/52))
Resume tailoring used to list junk as skill "gaps": salary figures, "3+",
"friendly", "hiring", and even words your CV already contained. Gaps are now
real skills only, such as `aws, dbt`, and match scores improved for the same
reason.

**Follow-up reminders stop at an offer** ([#52](https://github.com/aaron-seq/CareerAgent/pull/52))
Applications at **Offer**, **Rejected** or **Withdrawn** no longer show "due in
6 days". Screening and interview stages keep their reminders.

**"Export All Data" really is all your data** ([#52](https://github.com/aaron-seq/CareerAgent/pull/52), [#53](https://github.com/aaron-seq/CareerAgent/pull/53))
The ZIP used to contain only job-posting backups, one of them duplicated. It
now holds, in readable form:
- your application board with notes;
- every saved CV and its application details;
- contacts and email drafts;
- jobs and companies;
- your opt-out list;
- a `README.txt` listing everything included.

It contains personal details, so store it carefully.

**Simpler first run** ([#64](https://github.com/aaron-seq/CareerAgent/pull/64))
- AI settings are optional and collapsed in the sidebar.
- Labels use plain language.
- Mobile navigation works at phone widths.
- Manual contacts are validated, labelled by where they came from, and can be
  removed.

**More live job sources verified** ([#53](https://github.com/aaron-seq/CareerAgent/pull/53))
An opt-in smoke command (`python -m scripts.live_url_smoke --live`) checks eight
public job sources. 1,535 postings parsed on 17 October.

### Autofill extension

**Eligibility answers are country-scoped** ([#51](https://github.com/aaron-seq/CareerAgent/pull/51))
A right to work only holds for one country. Authorization, sponsorship and
visa-status questions are filled only when the question names the country you
saved and uses supported positive wording. Anything else is left blank and
flagged in amber for you, including negated and compound questions.

**More of the form, filled truthfully** ([#51](https://github.com/aaron-seq/CareerAgent/pull/51), [#64](https://github.com/aaron-seq/CareerAgent/pull/64))
- Dropdowns, radio buttons and screening questions are filled.
- Your CV PDF is attached to the *resume* upload only, never to cover-letter
  fields.
- Hidden fields are skipped.
- Desired-salary questions use your target pay, with the minimum only as a
  fallback.

It still never submits a form: you review every field and submit yourself.

**Bad imports can't break a fill**
A malformed resume block in a pasted profile is now dropped instead of
aborting the whole autofill.

### Privacy and security

- **Logging no longer prints API keys** ([#50](https://github.com/aaron-seq/CareerAgent/pull/50)).
  Logging setup used to lower the threshold for *every* library, so the HTTP
  client's request log would have printed full URLs, including Adzuna's
  `app_key`. Logging now covers CareerAgent's own code only, and it never
  records CV text, names, emails, phone numbers or tokens.
- **Security-fixed dependencies, frozen and hash-verified**
  ([#54](https://github.com/aaron-seq/CareerAgent/pull/54)). Installs come from
  reviewed lock files, and CI fails on known advisories.
- **Timezone-correct timestamps** ([#47](https://github.com/aaron-seq/CareerAgent/pull/47)).
  Dates are stored as timezone-aware UTC, which also fixed 78 test failures that
  fresh installs hit on newer `sqlmodel`.

### For developers

- **Python 3.11–3.13** ([#54](https://github.com/aaron-seq/CareerAgent/pull/54), [ADR 0012](adr/0012-reviewed-dependencies-and-maintained-python.md)).
  3.9 and 3.10 are past end of life and are no longer supported.
- **Reproducible installs:** hash-pinned locks in `requirements/locks/` for
  3.11, 3.12 and 3.13. Dependabot proposes updates; a weekly CI job also tests
  unconstrained upstream versions so breakage shows up early.
- **Type checking is enforced:** `mypy` now runs and is required across the
  whole repository ([#49](https://github.com/aaron-seq/CareerAgent/pull/49), [#54](https://github.com/aaron-seq/CareerAgent/pull/54)).
- **`pypdf`** replaces the deprecated PyPDF2 ([#49](https://github.com/aaron-seq/CareerAgent/pull/49)).
- **One command validates everything:** `python -m scripts.check` runs lint,
  format, types, Python tests with coverage, and extension tests.
  `python -m scripts.check docker` adds a functional container smoke test.
- **Test suite:** 922 Python tests and 64 extension tests; core coverage
  95.27%.
- **Decisions recorded:** ADRs [0008](adr/0008-timezone-aware-utc-datetimes.md)
  (UTC datetimes), [0009](adr/0009-candidate-answers-and-autofill-contract.md)
  (application details and the autofill contract),
  [0010](adr/0010-local-cv-builder-and-transparent-readiness.md) (CV builder),
  [0011](adr/0011-encrypted-local-workspace-recovery.md) (refresh recovery),
  [0012](adr/0012-reviewed-dependencies-and-maintained-python.md) (dependencies
  and Python) and [0013](adr/0013-reviewed-application-details-and-task-first-ux.md)
  (task-first UX).

### Upgrading

1. **Back up first:** `careeragent.db`, the `careeragent_data/` folder and your
   encryption key (`.careeragent_key` or `CAREERAGENT_ENCRYPTION_KEY`), together.
   Losing the key makes encrypted data unreadable.
2. **Use Python 3.11 or newer** and install from the lock for your version:
   ```bash
   python -m pip install --require-hashes --only-binary=:all: \
     -r requirements/locks/test-py311.txt
   ```
3. **Migrate the database:** `alembic upgrade head`. This release adds two
   migrations:
   - timezone-aware timestamps (`3f1c2a9d7e45`);
   - the encrypted application-details column (`3c90c531157f`).

   Existing data is kept. Keep the same data paths and key; never generate a
   replacement key during an upgrade.
4. **Re-import the extension profile:** download a fresh profile from
   **Export & Logs** and paste it into the extension, so it picks up
   country-scoped answers.

### Known limits

These are tracked as open issues rather than claimed as working:
- the installed extension hasn't been tested on live employer forms ([#13](https://github.com/aaron-seq/CareerAgent/issues/13));
- Gmail OAuth and delivery are untested ([#14](https://github.com/aaron-seq/CareerAgent/issues/14));
- the Postgres locking path is unverified;
- older history still contains personal data, which needs an owner decision on
  rewriting it ([#38](https://github.com/aaron-seq/CareerAgent/issues/38));
- hosted deployment needs work first on outbound URL boundaries
  ([#41](https://github.com/aaron-seq/CareerAgent/issues/41)) and metadata
  encryption ([#42](https://github.com/aaron-seq/CareerAgent/issues/42));
- autofill edge cases, contradictory field meanings and empty-valued options
  ([#65](https://github.com/aaron-seq/CareerAgent/issues/65),
  [#66](https://github.com/aaron-seq/CareerAgent/issues/66));
- Pipeline, matching and deduplication gaps found in review, such as separate
  vacancies in different locations being merged
  ([#67](https://github.com/aaron-seq/CareerAgent/issues/67)–[#75](https://github.com/aaron-seq/CareerAgent/issues/75)).

See the full [progress log](../PROGRESS.md) for test evidence behind each
change.
