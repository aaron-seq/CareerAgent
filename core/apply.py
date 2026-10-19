"""
The bridge between a stored job and the browser autofill extension.

* :func:`resolve_apply_url` classifies a posting URL: is it a page the
  extension's content script actually runs on, a recognized ATS it doesn't
  handle, or an unknown site? The UI uses this to set honest expectations.
* :func:`build_answers` derives the screening-question answers the extension
  may type/select, from a :class:`~core.candidate.CandidateProfile`. An answer
  is present only when the candidate supplied it -- an absent key means
  "unknown", and the extension leaves that question blank and flags it.

The answer keys are a contract with ``extension/src/field_mapping.js``
(``ANSWER_KEYS``); ``tests/test_apply.py`` and the extension's own tests pin
both sides against the shared fixture in ``extension/test/fixtures/``.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlparse

from .candidate import CandidateProfile
from .fetching import detect

#: Hosts where ``extension/manifest.json`` injects the content script. Kept in
#: lockstep with the manifest by ``tests/test_apply.py``.
AUTOFILL_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "jobs.lever.co",
        "jobs.ashbyhq.com",
    }
)

#: Boolean screening answers (yes/no selects and radio groups).
BOOLEAN_ANSWER_KEYS = ("work_authorized", "requires_sponsorship", "willing_to_relocate")
#: Free-text screening answers.
TEXT_ANSWER_KEYS = (
    "visa_status",
    "salary_expectation",
    "notice_period",
    "start_date",
    "cover_note",
)
#: EEO answers -- only exported with explicit consent.
DEMOGRAPHIC_ANSWER_KEYS = (
    "pronouns",
    "gender",
    "ethnicity",
    "veteran_status",
    "disability_status",
)
#: Marker the extension requires before it will use any demographic answer.
CONSENT_KEY = "share_demographics"
#: Country context for eligibility answers; never inferred from location/visa.
AUTHORIZATION_COUNTRY_KEY = "work_authorization_country"

#: Upper bound on an embedded resume, so a stray file can't blow the
#: extension's ``chrome.storage.local`` quota. Mirrors ``MAX_RESUME_B64``.
MAX_RESUME_BYTES = 2 * 1024 * 1024


@dataclass
class ApplyTarget:
    url: Optional[str]
    ats: Optional[str] = None
    autofill_supported: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_apply_url(url: Optional[str]) -> ApplyTarget:
    """Classify a posting URL for the Apply action.

    Only ``http(s)`` URLs are returned, so a malformed or ``javascript:`` value
    from a third-party feed can never become a clickable link.
    """
    if not url or not url.strip():
        return ApplyTarget(url=None, note="This posting has no application link.")
    original = url
    url = url.strip()
    try:
        parsed = urlparse(url)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and "\\" not in url
            and not any(ch.isspace() for ch in url)
            and not any(ord(ch) < 32 or ord(ch) == 127 for ch in original)
        )
        parsed.port  # Validate without making a network request.
    except ValueError:
        valid = False
    if not valid:
        return ApplyTarget(
            url=None, note="The recorded application link is not a web address."
        )

    host = (parsed.hostname or "").lower()
    match = detect(url=url)
    ats = match.ats_type if match else None
    if host in AUTOFILL_HOSTS and parsed.scheme == "https":
        return ApplyTarget(
            url=url,
            ats=ats,
            autofill_supported=True,
            note=(
                f"{(ats or 'ATS').title()} form: open it, then click "
                "'Autofill this page' in the extension. Review before submitting."
            ),
        )
    if ats:
        return ApplyTarget(
            url=url,
            ats=ats,
            note=(
                f"{ats.title()} form on a host the autofill extension doesn't "
                "run on; fill this one manually."
            ),
        )
    return ApplyTarget(
        url=url,
        note="Opens the posting. Autofill runs only on Greenhouse, Lever and Ashby.",
    )


def build_answers(candidate: CandidateProfile) -> dict[str, Any]:
    """The screening answers we can give truthfully, keyed for the extension.

    A key is present only when the candidate supplied the answer. Booleans
    stay booleans so the extension can pick a Yes/No option; demographics are
    included only with ``share_on_applications`` and then carry the consent
    marker the extension double-checks.
    """
    answers: dict[str, Any] = {}
    auth = candidate.work_authorization
    if auth.authorized is not None:
        answers["work_authorized"] = auth.authorized
    if auth.requires_sponsorship is not None:
        answers["requires_sponsorship"] = auth.requires_sponsorship
    if auth.visa_status:
        answers["visa_status"] = auth.visa_status
    if answers and auth.country and auth.country.strip():
        answers[AUTHORIZATION_COUNTRY_KEY] = auth.country.strip()

    comp = candidate.compensation
    amount = comp.target if comp.target is not None else comp.minimum
    if amount is not None:
        # str(float) preserves its accepted decimal value; whole-unit formatting
        # used to turn an hourly rate such as 42.75 into a different answer.
        decimal = Decimal(str(amount))
        if not decimal.is_finite() or decimal < 0:
            raise ValueError("Pay must be a finite nonnegative amount.")
        formatted = format(decimal.normalize() if decimal else Decimal(0), ",f")
        answers["salary_expectation"] = f"{comp.currency} {formatted} per {comp.period}"

    avail = candidate.availability
    if avail.notice_period_weeks is not None:
        weeks = avail.notice_period_weeks
        answers["notice_period"] = f"{weeks} week{'' if weeks == 1 else 's'}"
    if avail.earliest_start_date:
        answers["start_date"] = avail.earliest_start_date

    if candidate.preferences.open_to_relocation is not None:
        answers["willing_to_relocate"] = candidate.preferences.open_to_relocation

    if candidate.default_cover_note:
        answers["cover_note"] = candidate.default_cover_note

    demo = candidate.demographics
    if demo.share_on_applications:
        shared = {k: getattr(demo, k) for k in DEMOGRAPHIC_ANSWER_KEYS}
        shared = {k: v for k, v in shared.items() if v}
        if shared:
            answers.update(shared)
            answers[CONSENT_KEY] = True
    return answers


def answer_preview(candidate: CandidateProfile) -> dict[str, Any]:
    """Exact export values plus the pay source, without another readiness score."""
    answers = build_answers(candidate)
    comp = candidate.compensation
    source = (
        "target"
        if comp.target is not None
        else "minimum"
        if comp.minimum is not None
        else None
    )
    ordinary_keys = (*BOOLEAN_ANSWER_KEYS, *TEXT_ANSWER_KEYS)
    return {
        "answers": answers,
        "compensation_source": source,
        "unanswered": [key for key in ordinary_keys if key not in answers],
        "voluntary_answers_shared": answers.get(CONSENT_KEY) is True,
        "eligibility_country": answers.get(AUTHORIZATION_COUNTRY_KEY),
    }


def resume_attachment(pdf: bytes, candidate_name: Optional[str]) -> dict[str, str]:
    """The ``resume`` block the extension attaches to a resume file input."""
    if not pdf.startswith(b"%PDF"):
        raise ValueError("Resume attachment must be a PDF.")
    if len(pdf) > MAX_RESUME_BYTES:
        raise ValueError("Resume PDF is larger than the 2 MB autofill limit.")
    stem = "_".join((candidate_name or "").split()) or "resume"
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in "_-") or "resume"
    return {
        "filename": f"{safe}.pdf",
        "mime": "application/pdf",
        "data_b64": base64.b64encode(pdf).decode("ascii"),
    }
