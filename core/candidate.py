"""
The candidate profile: everything an application form asks that a CV doesn't say.

A parsed CV gives us history — roles, projects, skills. It does not answer the
questions every application form actually blocks on:

    "Are you authorized to work in the US?"
    "Will you now or in the future require sponsorship?"
    "What are your salary expectations?"
    "When can you start?"

Platforms like Wellfound solve this by having candidates build a *structured
profile* rather than upload a document, with work authorization, compensation,
and job preferences as first-class fields. :class:`CandidateProfile` is that
layer: it wraps the parsed :class:`~core.models.CVProfile` and adds the
application-critical answers, so the autofill extension can complete a form
instead of stalling on question three.

Two rules run through this module:

* **Unknown is not an answer.** Every field is optional and defaults to
  ``None``. We never guess a work-authorization answer onto a real application.
* **Demographics are opt-in.** EEO fields default to "prefer not to say" and
  are only ever filled when the candidate explicitly supplied them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .models import CVProfile


class RemotePreference(str, Enum):
    REMOTE_ONLY = "remote_only"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    FLEXIBLE = "flexible"


class CompanyStage(str, Enum):
    SEED = "seed"
    EARLY = "early"  # Series A/B
    GROWTH = "growth"  # Series C+
    PUBLIC = "public"
    ANY = "any"


class WorkAuthorization(BaseModel):
    """Answers to the two questions almost every US/UK form asks.

    Both are tri-state: ``None`` means the candidate hasn't told us, and we
    leave the form field alone rather than answering on their behalf.
    """

    country: Optional[str] = None
    #: "Are you legally authorized to work in {country}?"
    authorized: Optional[bool] = None
    #: "Will you now or in the future require sponsorship?"
    requires_sponsorship: Optional[bool] = None
    visa_status: Optional[str] = None  # free text, e.g. "H-1B", "Skilled Worker"

    def is_complete(self) -> bool:
        return self.authorized is not None and self.requires_sponsorship is not None


class Compensation(BaseModel):
    """Expectations, so roles that can't meet them filter themselves out."""

    minimum: Optional[float] = None
    target: Optional[float] = None
    currency: str = "USD"
    period: str = "year"  # year | day | hour
    equity_expected: Optional[bool] = None

    def is_complete(self) -> bool:
        return self.minimum is not None


class Availability(BaseModel):
    notice_period_weeks: Optional[int] = None
    earliest_start_date: Optional[str] = None  # ISO date, free-form is fine
    open_to_contract: Optional[bool] = None


class JobPreferences(BaseModel):
    desired_titles: list[str] = Field(default_factory=list)
    seniority: Optional[str] = None
    remote_preference: Optional[RemotePreference] = None
    locations: list[str] = Field(default_factory=list)
    open_to_relocation: Optional[bool] = None
    company_stages: list[CompanyStage] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)

    def is_complete(self) -> bool:
        return bool(self.desired_titles) and self.remote_preference is not None


class Demographics(BaseModel):
    """Optional EEO answers.

    Defaults are deliberately empty. These are never inferred, never derived
    from a name or photo, and are only used if the candidate typed them in.
    """

    pronouns: Optional[str] = None
    gender: Optional[str] = None
    ethnicity: Optional[str] = None
    veteran_status: Optional[str] = None
    disability_status: Optional[str] = None

    #: Explicit consent to use these answers on application forms.
    share_on_applications: bool = False


class CandidateProfile(BaseModel):
    """The full candidate record: parsed CV + application answers."""

    cv: CVProfile = Field(default_factory=CVProfile)

    # Contact / identity beyond what the CV parser finds.
    location: Optional[str] = None
    phone_country_code: Optional[str] = None
    websites: list[str] = Field(default_factory=list)

    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    compensation: Compensation = Field(default_factory=Compensation)
    availability: Availability = Field(default_factory=Availability)
    preferences: JobPreferences = Field(default_factory=JobPreferences)
    demographics: Demographics = Field(default_factory=Demographics)

    #: Free-text answer reused for "Why do you want to work here?" prompts.
    default_cover_note: Optional[str] = None

    def display_name(self) -> str:
        return self.cv.name or "(unnamed)"


# --------------------------------------------------------------------------- #
# Completeness
# --------------------------------------------------------------------------- #


@dataclass
class ChecklistItem:
    key: str
    label: str
    done: bool
    weight: int
    why: str
    section: str


@dataclass
class Completeness:
    percent: int
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def missing(self) -> list[ChecklistItem]:
        """Incomplete items, most valuable first."""
        return sorted(
            (i for i in self.items if not i.done),
            key=lambda i: i.weight,
            reverse=True,
        )

    def next_best_action(self) -> Optional[ChecklistItem]:
        missing = self.missing
        return missing[0] if missing else None

    def by_section(self) -> dict[str, list[ChecklistItem]]:
        sections: dict[str, list[ChecklistItem]] = {}
        for item in self.items:
            sections.setdefault(item.section, []).append(item)
        return sections


def compute_completeness(profile: CandidateProfile) -> Completeness:
    """Score the profile and explain what each gap costs the candidate.

    Weights reflect how often a missing field actually blocks an application,
    not how hard it is to fill in -- work authorization outranks a portfolio
    link because forms refuse to submit without it.
    """
    cv = profile.cv
    auth = profile.work_authorization
    items = [
        ChecklistItem(
            "name",
            "Full name",
            bool(cv.name),
            10,
            "Every application form requires it.",
            "Basics",
        ),
        ChecklistItem(
            "email",
            "Email address",
            bool(cv.email),
            10,
            "Required to apply and to receive replies.",
            "Basics",
        ),
        ChecklistItem(
            "phone",
            "Phone number",
            bool(cv.phone),
            6,
            "Most forms require a phone number.",
            "Basics",
        ),
        ChecklistItem(
            "location",
            "Location",
            bool(profile.location),
            7,
            "Fills the 'City' field and filters roles you can actually take.",
            "Basics",
        ),
        ChecklistItem(
            "work_auth",
            "Work authorization",
            auth.is_complete(),
            12,
            "The most common blocking question on US and UK forms — autofill "
            "cannot answer it for you without this.",
            "Eligibility",
        ),
        ChecklistItem(
            "experience",
            "Work experience",
            bool(cv.experiences),
            10,
            "Drives your match scores and the tailored resume.",
            "Experience",
        ),
        ChecklistItem(
            "skills",
            "Skills",
            bool(cv.skills),
            9,
            "Match scoring is mostly skill overlap.",
            "Experience",
        ),
        ChecklistItem(
            "education",
            "Education",
            bool(cv.education),
            4,
            "Frequently a required field on ATS forms.",
            "Experience",
        ),
        ChecklistItem(
            "desired_titles",
            "Target roles",
            bool(profile.preferences.desired_titles),
            8,
            "Used to rank jobs and to seed searches.",
            "Preferences",
        ),
        ChecklistItem(
            "remote_pref",
            "Remote preference",
            profile.preferences.remote_preference is not None,
            6,
            "Filters out roles you would decline anyway.",
            "Preferences",
        ),
        ChecklistItem(
            "compensation",
            "Salary expectations",
            profile.compensation.is_complete(),
            7,
            "Forms ask for it, and it screens out roles below your floor.",
            "Preferences",
        ),
        ChecklistItem(
            "availability",
            "Notice period / start date",
            profile.availability.notice_period_weeks is not None
            or bool(profile.availability.earliest_start_date),
            5,
            "A standard form question ('When can you start?').",
            "Preferences",
        ),
        ChecklistItem(
            "linkedin",
            "LinkedIn URL",
            bool(cv.linkedin),
            5,
            "Requested on most application forms.",
            "Links",
        ),
        ChecklistItem(
            "github",
            "GitHub / portfolio",
            bool(cv.github or cv.portfolio or profile.websites),
            4,
            "Optional but commonly asked for engineering roles.",
            "Links",
        ),
        ChecklistItem(
            "summary",
            "Professional summary",
            bool(cv.summary),
            4,
            "Reused in outreach emails and cover notes.",
            "Experience",
        ),
    ]

    total = sum(i.weight for i in items)
    earned = sum(i.weight for i in items if i.done)
    percent = round(100 * earned / total) if total else 0
    return Completeness(percent=percent, items=items)
