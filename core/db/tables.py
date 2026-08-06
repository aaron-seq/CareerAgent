"""
SQLModel table definitions -- the persistent schema.

These are the storage layer. Domain models in ``core.models`` remain the
validation/LLM-IO layer; converters live in ``core.db.repository``. Anything
personal (resume text, emails, phones) uses :class:`EncryptedString`.

The schema is written to be Postgres-compatible (the deployment target) while
running on SQLite for local dev, CI, and tests. Vector embeddings are stored as
JSON here; pgvector is the production swap (see ADR 0003).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from .crypto import EncryptedString


def _utcnow() -> datetime:
    return datetime.utcnow()


class ApplicationStatus(str, Enum):
    """Kanban states for an application's lifecycle."""

    SAVED = "saved"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class Company(SQLModel, table=True):
    __tablename__ = "company"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    normalized_name: str = Field(index=True)
    ats_type: Optional[str] = None
    careers_url: Optional[str] = None
    glassdoor_rating: Optional[float] = None
    # Tri-state: True / False / None. NULL means "we have no data", which is
    # distinct from "no layoffs recorded" -- never default this to False.
    had_layoffs: Optional[bool] = None
    sponsors_visa: Optional[bool] = None
    blacklisted: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class JobPostingRow(SQLModel, table=True):
    __tablename__ = "job_posting"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_job"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    source_id: Optional[str] = Field(default=None, index=True)
    title: str
    company_name: str = Field(index=True)
    company_id: Optional[int] = Field(default=None, foreign_key="company.id")
    location: Optional[str] = None
    remote: bool = False
    url: Optional[str] = None
    description: str = ""
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    employment_type: Optional[str] = None
    date_posted: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=_utcnow)

    # Enrichment / matching
    dedup_key: str = Field(default="", index=True)
    is_duplicate: bool = False
    canonical_job_id: Optional[int] = Field(default=None, foreign_key="job_posting.id")
    match_score: Optional[float] = None
    match_explanation: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    embedding: Optional[list] = Field(default=None, sa_column=Column(JSON))
    ghost_score: Optional[float] = None

    # Structured extras from the source (requirements, tech_stack, ...)
    extra: Optional[dict] = Field(default=None, sa_column=Column(JSON))


class CVProfileRow(SQLModel, table=True):
    __tablename__ = "cv_profile"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = None
    # PII: encrypted at rest.
    email: Optional[str] = Field(default=None, sa_column=Column(EncryptedString))
    phone: Optional[str] = Field(default=None, sa_column=Column(EncryptedString))
    linkedin: Optional[str] = None
    github: Optional[str] = None
    summary: Optional[str] = None
    # Full CVProfile serialized + encrypted (contains raw resume text = PII).
    payload: Optional[str] = Field(default=None, sa_column=Column(EncryptedString))
    # Full CandidateProfile (CV + work auth, compensation, preferences, and
    # optional demographics). Encrypted: this is the most sensitive record we
    # hold.
    candidate_payload: Optional[str] = Field(
        default=None, sa_column=Column(EncryptedString)
    )
    embedding: Optional[list] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class ContactRow(SQLModel, table=True):
    __tablename__ = "contact"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    role: Optional[str] = None
    email: Optional[str] = Field(default=None, sa_column=Column(EncryptedString))
    email_hash: Optional[str] = Field(default=None, index=True)
    email_confidence: str = "unknown"
    email_verified: Optional[bool] = None
    linkedin: Optional[str] = None
    company_id: Optional[int] = Field(default=None, foreign_key="company.id")
    source: str = ""
    confidence_score: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)


class EmailDraftRow(SQLModel, table=True):
    __tablename__ = "email_draft"

    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str
    body: str = Field(sa_column=Column(EncryptedString))
    recipient_email: Optional[str] = Field(
        default=None, sa_column=Column(EncryptedString)
    )
    recipient_name: Optional[str] = None
    job_id: Optional[int] = Field(default=None, foreign_key="job_posting.id")
    company: str = ""
    job_title: str = ""
    word_count: int = 0
    gmail_draft_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)


class ApplicationRow(SQLModel, table=True):
    __tablename__ = "application"
    __table_args__ = (
        UniqueConstraint("job_dedup_key", "cv_profile_id", name="uq_application"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: Optional[int] = Field(default=None, foreign_key="job_posting.id")
    job_dedup_key: str = Field(default="", index=True)
    cv_profile_id: Optional[int] = Field(default=None, foreign_key="cv_profile.id")
    status: ApplicationStatus = Field(default=ApplicationStatus.SAVED)
    applied_at: Optional[datetime] = None
    next_follow_up_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SuppressionRow(SQLModel, table=True):
    """Do-not-contact list. Matched by deterministic email hash."""

    __tablename__ = "suppression"

    id: Optional[int] = Field(default=None, primary_key=True)
    email_hash: str = Field(index=True, unique=True)
    reason: str = "opt_out"
    created_at: datetime = Field(default_factory=_utcnow)
