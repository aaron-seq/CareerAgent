"""
The bridge between a tracked job and the browser autofill extension.

Clicking **Apply** on a job should open that job's real application page and
have the form fill itself. Two things make that work:

1. :func:`resolve_apply_url` -- turn a stored posting URL into the page the
   candidate actually applies on, and report whether our extension supports
   that ATS (so the UI can set expectations instead of silently doing nothing).
2. :func:`build_autofill_profile` -- derive the extension's profile from the
   **parsed CV**, so nothing is retyped by hand, optionally carrying the
   ATS-clean resume PDF so the file input can be populated too.

The profile is a plain dict the extension stores in ``chrome.storage.local``.
It is PII, so it never leaves the user's machine: the app writes a file, the
user imports it into the extension. No server, no network hop.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .fetching import detect
from .models import CVProfile, JobPosting

#: ATS platforms the content script has selectors/handling for.
SUPPORTED_ATS = {"greenhouse", "lever", "ashby"}

#: Recognized but not yet handled by the extension.
KNOWN_UNSUPPORTED_ATS = {"workday", "smartrecruiters"}

_CITY = re.compile(r"^\s*([^,|/]+)")


@dataclass
class ApplyTarget:
    url: Optional[str]
    ats: Optional[str] = None
    autofill_supported: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "ats": self.ats,
            "autofill_supported": self.autofill_supported,
            "note": self.note,
        }


def resolve_apply_url(url: Optional[str]) -> ApplyTarget:
    """Classify a posting URL for the Apply flow."""
    if not url:
        return ApplyTarget(
            url=None, note="This posting has no application link recorded."
        )

    match = detect(url=url)
    if match is None:
        return ApplyTarget(
            url=url,
            note=(
                "Opens the posting. Autofill only runs on Greenhouse, Lever, "
                "and Ashby forms."
            ),
        )
    if match.ats_type in SUPPORTED_ATS:
        return ApplyTarget(
            url=url,
            ats=match.ats_type,
            autofill_supported=True,
            note=f"{match.ats_type.title()} form - autofill will run on open.",
        )
    return ApplyTarget(
        url=url,
        ats=match.ats_type,
        note=(
            f"{match.ats_type.title()} is not supported by the autofill "
            "extension yet; you'll need to fill this one manually."
        ),
    )


# NOTE: CVProfile carries no location field today, so the 'Location' input is
# left for the caller to supply. Guessing a city from company names would put
# an invented answer on a real application form.


@dataclass
class AutofillProfile:
    """What the extension stores. Keys mirror ``field_mapping.js``."""

    fullName: str = ""
    firstName: str = ""
    lastName: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    location: str = ""
    resume: Optional[dict[str, str]] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "fullName": self.fullName,
            "firstName": self.firstName,
            "lastName": self.lastName,
            "email": self.email,
            "phone": self.phone,
            "linkedin": self.linkedin,
            "github": self.github,
            "portfolio": self.portfolio,
            "location": self.location,
            "meta": self.meta,
        }
        if self.resume:
            data["resume"] = self.resume
        return data


def split_name(full_name: Optional[str]) -> tuple[str, str]:
    """Split a display name into first/last without inventing either."""
    parts = [p for p in (full_name or "").split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def build_autofill_profile(
    cv: CVProfile,
    resume_pdf: bytes | None = None,
    resume_filename: str = "resume.pdf",
    location: str | None = None,
) -> AutofillProfile:
    """Derive the extension profile from the parsed CV.

    Only fields the CV actually contains are populated -- absent values stay
    empty strings so the extension skips those inputs rather than typing
    something made up into an application form.
    """
    first, last = split_name(cv.name)
    profile = AutofillProfile(
        fullName=cv.name or "",
        firstName=first,
        lastName=last,
        email=cv.email or "",
        phone=cv.phone or "",
        linkedin=cv.linkedin or "",
        github=cv.github or "",
        portfolio=cv.portfolio or "",
        location=location or "",
    )
    if resume_pdf:
        profile.resume = {
            "filename": resume_filename,
            "mime": "application/pdf",
            "data_b64": base64.b64encode(resume_pdf).decode("ascii"),
        }
    profile.meta = {
        "source": "CareerAgent",
        "never_submits": True,
    }
    return profile


def apply_context(job: JobPosting) -> dict[str, Any]:
    """Everything the UI needs to render an Apply action for one job."""
    target = resolve_apply_url(job.url)
    return {
        "title": job.title,
        "company": job.company,
        **target.to_dict(),
    }
