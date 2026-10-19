"""
The candidate profile: what an application form asks that a CV doesn't say.

A parsed :class:`~core.models.CVProfile` gives history -- roles, projects,
skills. It does not answer the questions application forms block on:

    "Are you authorized to work in the US?"
    "Will you now or in the future require sponsorship?"
    "What are your salary expectations?"
    "When can you start?"

:class:`CandidateProfile` holds those answers. It deliberately does **not**
embed the CV: it is stored beside the saved CV it belongs to (the encrypted
``cv_profile.candidate_payload`` column), so the CV stays the single source of
truth for history and the two can't drift apart.

Two rules run through this module:

* **Unknown is not an answer.** Every answer is optional and defaults to
  ``None``. Nothing here guesses a work-authorization answer onto a real form.
* **Demographics are opt-in.** EEO answers are only ever used when the
  candidate typed them in *and* ticked ``share_on_applications``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import CVProfile


class RemotePreference(str, Enum):
    REMOTE_ONLY = "remote_only"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    FLEXIBLE = "flexible"


class _AnswerModel(BaseModel):
    """Normalize empty editor fields without converting unknown into false."""

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def empty_to_unknown(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value


class WorkAuthorization(_AnswerModel):
    """The two questions almost every US/UK form asks.

    Both are tri-state: ``None`` means the candidate hasn't said, and the form
    question is left for the human rather than answered on their behalf.
    """

    country: Optional[str] = Field(default=None, max_length=100)
    #: "Are you legally authorized to work in {country}?"
    authorized: Optional[bool] = None
    #: "Will you now or in the future require sponsorship?"
    requires_sponsorship: Optional[bool] = None
    visa_status: Optional[str] = Field(default=None, max_length=5000)

    def is_complete(self) -> bool:
        return (
            bool(self.country and self.country.strip())
            and self.authorized is not None
            and self.requires_sponsorship is not None
        )


class Compensation(_AnswerModel):
    minimum: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    target: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    period: Literal["year", "month", "day", "hour"] = "year"

    @field_validator("minimum", "target", mode="before")
    @classmethod
    def preserve_stated_precision(cls, value: Any) -> Any:
        """Reject editor numbers the existing float storage would silently alter."""
        if isinstance(value, bool):
            raise ValueError("Pay must be an amount, not a yes/no answer.")
        if isinstance(value, (str, int)) and str(value).strip():
            try:
                exact = Decimal(str(value).strip())
                represented = Decimal(str(float(value)))
            except (InvalidOperation, ValueError, OverflowError):
                return value  # Pydantic reports invalid/non-finite numeric input.
            if exact.is_finite() and exact != represented:
                raise ValueError(
                    "This pay amount exceeds supported precision. Use a shorter "
                    "amount that preserves your intended pay."
                )
        return value

    @model_validator(mode="after")
    def target_not_below_minimum(self) -> Compensation:
        if (
            self.minimum is not None
            and self.target is not None
            and self.target < self.minimum
        ):
            raise ValueError("Expected pay must be at least the minimum pay.")
        return self

    def is_complete(self) -> bool:
        return self.minimum is not None or self.target is not None


class Availability(_AnswerModel):
    notice_period_weeks: Optional[int] = Field(default=None, ge=0, le=104)
    earliest_start_date: Optional[str] = Field(default=None, max_length=5000)
    open_to_contract: Optional[bool] = None

    def is_complete(self) -> bool:
        return self.notice_period_weeks is not None or bool(self.earliest_start_date)


class JobPreferences(_AnswerModel):
    desired_titles: List[str] = Field(default_factory=list)
    remote_preference: Optional[RemotePreference] = None
    locations: List[str] = Field(default_factory=list)
    open_to_relocation: Optional[bool] = None

    @field_validator("desired_titles", "locations")
    @classmethod
    def nonempty_entries(cls, values: List[str]) -> List[str]:
        return list(dict.fromkeys(value for value in values if value))

    def is_complete(self) -> bool:
        return bool(self.desired_titles) and self.remote_preference is not None


class Demographics(_AnswerModel):
    """Optional EEO answers.

    Never inferred (not from a name, photo, or anything else) and only used
    when the candidate typed them in and set ``share_on_applications``.
    """

    pronouns: Optional[str] = Field(default=None, max_length=5000)
    gender: Optional[str] = Field(default=None, max_length=5000)
    ethnicity: Optional[str] = Field(default=None, max_length=5000)
    veteran_status: Optional[str] = Field(default=None, max_length=5000)
    disability_status: Optional[str] = Field(default=None, max_length=5000)
    #: Explicit consent to put these answers on application forms.
    share_on_applications: bool = False


class CandidateProfile(_AnswerModel):
    """Application answers that accompany one saved CV."""

    #: City/region for the "Location" field. Not in CVProfile, never guessed.
    location: Optional[str] = None
    websites: List[str] = Field(default_factory=list)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    compensation: Compensation = Field(default_factory=Compensation)
    availability: Availability = Field(default_factory=Availability)
    preferences: JobPreferences = Field(default_factory=JobPreferences)
    demographics: Demographics = Field(default_factory=Demographics)
    #: Candidate-written text reused for "Why do you want to work here?".
    default_cover_note: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("websites", mode="before")
    @classmethod
    def websites_from_editor(cls, value: Any) -> Any:
        return value.splitlines() if isinstance(value, str) else value

    @field_validator("websites")
    @classmethod
    def valid_websites(cls, values: List[str]) -> List[str]:
        websites = list(dict.fromkeys(value for value in values if value))
        for value in websites:
            try:
                parsed = urlsplit(value)
                valid = (
                    parsed.scheme in {"http", "https"}
                    and bool(parsed.hostname)
                    and parsed.username is None
                    and parsed.password is None
                    and "\\" not in value
                    and not any(
                        ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value
                    )
                )
                parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(
                    "Websites must be complete HTTP or HTTPS URLs without credentials."
                )
        return websites


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
    items: List[ChecklistItem] = field(default_factory=list)

    @property
    def missing(self) -> List[ChecklistItem]:
        """Incomplete items, most valuable first (stable for equal weights)."""
        return sorted((i for i in self.items if not i.done), key=lambda i: -i.weight)

    def to_dict(self) -> dict[str, Any]:
        missing = self.missing
        return {
            "percent": self.percent,
            "items": [asdict(i) for i in self.items],
            "missing": [asdict(i) for i in missing],
            "next_best_action": asdict(missing[0]) if missing else None,
        }


def compute_completeness(
    cv: CVProfile, candidate: Optional[CandidateProfile] = None
) -> Completeness:
    """Score a CV + application answers and explain what each gap costs.

    Weights reflect how often a missing field blocks an application, not how
    hard it is to fill in -- work authorization outranks a portfolio link
    because forms refuse to submit without it.
    """
    c = candidate or CandidateProfile()
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
            bool(c.location),
            7,
            "Fills the 'City' field; your CV doesn't state it reliably.",
            "Basics",
        ),
        ChecklistItem(
            "work_authorization",
            "Work authorization",
            c.work_authorization.is_complete(),
            12,
            "The most common blocking question on US and UK forms; autofill "
            "leaves it blank until you supply both answers and their country.",
            "Eligibility",
        ),
        ChecklistItem(
            "experience",
            "Work experience",
            bool(cv.experiences),
            10,
            "Drives match scores and the tailored resume.",
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
            "summary",
            "Professional summary",
            bool(cv.summary),
            4,
            "Reused in outreach emails and cover notes.",
            "Experience",
        ),
        ChecklistItem(
            "desired_titles",
            "Target roles",
            bool(c.preferences.desired_titles),
            8,
            "Your stated target roles, saved with this CV for reference.",
            "Preferences",
        ),
        ChecklistItem(
            "remote_preference",
            "Remote preference",
            c.preferences.remote_preference is not None,
            6,
            "Your stated work-location preference, saved for reference.",
            "Preferences",
        ),
        ChecklistItem(
            "compensation",
            "Salary expectations",
            c.compensation.is_complete(),
            7,
            "An optional answer for pay questions; it does not filter job matches.",
            "Preferences",
        ),
        ChecklistItem(
            "availability",
            "Notice period / start date",
            c.availability.is_complete(),
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
            "portfolio",
            "GitHub / portfolio",
            bool(cv.github or cv.portfolio or c.websites),
            4,
            "Optional, but commonly asked for engineering roles.",
            "Links",
        ),
    ]
    total = sum(i.weight for i in items)
    earned = sum(i.weight for i in items if i.done)
    return Completeness(percent=round(100 * earned / total), items=items)
