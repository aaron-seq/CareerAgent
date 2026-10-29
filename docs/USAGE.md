# Using CareerAgent

[Overview](../README.md) | [Operations and recovery](OPERATIONS.md) | [Extension reference](../extension/README.md)

## Your first application

1. Browse **Job Discovery** to import a company careers page, query a job board,
   or paste a description. Browsing and saving jobs work without an AI provider.
2. In **Onboarding**, use the **Build or edit a CV** tab without connecting AI,
   choose **Import PDF or text** after connecting a model, or choose
   **Use a saved CV** above the tabs. Your
   matches refresh when you switch profiles; resume checks and downloads work
   offline.
3. Open **Pipeline**, choose **Prepare application** on a posting, and tailor
   your resume. Connect your chosen model when you want an email or cover letter.
   Switching jobs preserves each job's edits separately.
4. Review all claims and recipients before exporting. Contacts are optional;
   a selected job can go directly to application materials. Use the posting link and
   browser extension to fill the application, then review and submit yourself.
   **Export & Logs** downloads a readable ZIP of local artifacts and selected database records. See [export limits](OPERATIONS.md#backups-and-exports).

Each imported job shows its source and original posting link. SmartRecruiters
imports follow later pages automatically, up to 250 jobs and 20 list pages by
default. A partial-import notice identifies where to continue with the Pipeline
import controls; requests stop if a provider repeats a page.

## Build a CV and improve its readiness

In **Build or edit your CV**, enter your name and your actual skills, education,
roles, or projects. Add work/project entries with the count controls; entirely
blank entries are ignored. Choose **Update draft preview** to inspect the current
facts beside the editor: **PDF preview**, **Plain text** and **LaTeX source**.
Previewing needs no AI connection and does not save or activate a CV. Changing
facts hides outdated draft downloads until you update the preview.

Save with **Create CV and check readiness**. Edits
create a new saved profile, keeping the previous version available. A failed
database save leaves your active CV unchanged.

Unsaved builder edits stay in the current browser session when switching tabs
or navigating between screens. Save before refreshing or closing the browser.
Activating a different saved CV starts its editor from that CV's facts.

Draft downloads use your previewed edits; the saved-CV and tailored downloads
use their separately labelled profiles. **Download draft Overleaf ZIP** includes
`main.tex`, bundled fonts and their notices. [Upload the ZIP as a new Overleaf
project](https://docs.overleaf.com/managing-projects-and-files/uploading-a-project),
select **XeLaTeX** and `main.tex`, then edit the source there. You can also compile
it locally. Downloads contain readable personal data; uploading shares it with
Overleaf. CareerAgent generates escaped source and runs no TeX commands.

Review the compiled PDF: its pagination can differ from the app's preview.
Bundled fonts cover Latin, Greek and Cyrillic; other scripts may require suitable
fonts and layout changes in the source. Lossless Markdown/JSON exports remain
available when PDF generation fails. No export guarantees an ATS ranking.

**Local CV readiness** is a 100-point content checklist: name 10, usable email
15, skills 15, experience or projects 25, supporting details 15, education 10,
and complete entries 10. Project-only applicants can satisfy it. The checklist
explains each missing item; it does not verify qualifications or measure PDF
layout. **Job skill coverage** separately reports matched/missing recognized
skills for a selected job. Repeating or reordering facts cannot improve it.
Neither number is an external ATS score or a hiring prediction. Add a skill
only when you have it.

PDF exports use bundled offline fonts and preserve links, technologies and
project impact. Unsupported glyphs or scripts needing shaping/right-to-left
layout show a clear message; Markdown and JSON remain available with the
original text. See [the CV and live-URL validation report](CV_VALIDATION.md)
for tested behavior and limits.

## Save application answers and prepare autofill

With a saved CV active in **Onboarding**, open **Application details** →
**Edit application details**. Supply only the answers you want to reuse:
country-scoped work eligibility, expected pay, availability, relocation or a
cover note. **Not answered**, **Yes** and **No** are distinct; blank pay/notice
stays unknown and an explicit zero is preserved. Save the details before
downloading them. Each saved CV has its own answers; creating a new CV snapshot
starts with unanswered details, so review them again.

**Export & Logs** previews the saved fields. Expected pay takes precedence over
minimum pay; if expected pay is blank, the preview explicitly identifies the
minimum fallback. Currency and period stay as stated, with no conversion.
Unsupported numeric precision is rejected instead of silently changing pay.
Voluntary demographic answers are excluded unless you save the sharing choice.
Unsaved changes remain in the current session and are excluded from downloads.

Choose **Include my CV PDF for resume upload** to embed the active CV. If PDF
generation or the 2 MB attachment limit fails, an identity/answers-only JSON
download remains available. The JSON and PDF contain readable personal data.
Load `extension/` through Chrome's **Load unpacked**, open the downloaded JSON
and paste it into **Import from CareerAgent** in the extension popup. Open the
supported form and choose **Autofill this page**, then review every field and
submit yourself. Unsupported/ambiguous questions need manual answers; hidden
non-file fields are skipped. Opening a posting or downloading a profile does
not change its application status.

See the [product review](PRODUCT_UX_REVIEW_2026-10-19.md) for browser evidence,
state behavior and remaining limits.

## Refresh safely

Committed choices recover automatically after a browser refresh: the active
saved CV, selected DB-backed jobs, contacts, preferences and last page. AI/OAuth
clients, credentials, unsent drafts and approval state do not recover. Reconnect
your chosen model when needed, and use **Re-score matches** after restoring a
CV because stored discovery scores have no CV provenance. Draft Studio resume
checks still use the active profile.

The recovery file is encrypted beside your local artifacts. If it cannot be
read, the app explains the failure and preserves it. Fix the key/storage first,
or explicitly choose **Start a new saved workspace**; this retains a private
ciphertext backup and does not remove saved CVs/jobs. Explicit ZIP exports are
readable and include workspace contacts/preferences. This is recovery for one
trusted local user, not multi-user isolation or synchronization between tabs.
