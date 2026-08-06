"""
Repositories: the only place domain models meet the database.

Each repository converts between ``core.models`` domain objects and the
SQLModel rows in ``core.db.tables``, and encapsulates the queries the rest of
the app needs. Upserts key off natural identifiers (``(source, source_id)`` for
jobs, ``email_hash`` for suppression) so re-ingesting is idempotent.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from ..models import CVProfile, EmailDraft, JobPosting
from ..normalize import compute_dedup_key, normalize_company_name
from .crypto import deterministic_hash
from .tables import (
    ApplicationRow,
    ApplicationStatus,
    Company,
    ContactRow,
    CVProfileRow,
    EmailDraftRow,
    JobPostingRow,
    SuppressionRow,
)

# --------------------------------------------------------------------------- #
# Converters
# --------------------------------------------------------------------------- #


def job_to_row(
    job: JobPosting, source: str, source_id: str | None = None
) -> JobPostingRow:
    """Convert a domain :class:`JobPosting` into a persistable row."""
    return JobPostingRow(
        source=source,
        source_id=source_id,
        title=job.title,
        company_name=job.company,
        location=job.location,
        url=job.url,
        description=job.description,
        salary_currency=None,
        dedup_key=compute_dedup_key(job.title, job.company, job.location),
        extra={
            "requirements": job.requirements,
            "nice_to_have": job.nice_to_have,
            "tech_stack": job.tech_stack,
            "problems": job.problems,
            "benefits": job.benefits,
            "salary_range": job.salary_range,
            "relevance_score": job.relevance_score,
        },
    )


def row_to_job(row: JobPostingRow) -> JobPosting:
    extra = row.extra or {}
    return JobPosting(
        title=row.title,
        company=row.company_name,
        location=row.location,
        url=row.url,
        description=row.description,
        requirements=extra.get("requirements", []),
        nice_to_have=extra.get("nice_to_have", []),
        tech_stack=extra.get("tech_stack", []),
        problems=extra.get("problems", []),
        benefits=extra.get("benefits", []),
        salary_range=extra.get("salary_range"),
        relevance_score=extra.get("relevance_score", 0.0),
    )


# --------------------------------------------------------------------------- #
# Company
# --------------------------------------------------------------------------- #


class CompanyRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create(self, name: str, **kwargs) -> Company:
        normalized = normalize_company_name(name)
        existing = self.session.exec(
            select(Company).where(Company.normalized_name == normalized)
        ).first()
        if existing:
            for key, value in kwargs.items():
                if value is not None:
                    setattr(existing, key, value)
            self.session.add(existing)
            return existing
        company = Company(name=name, normalized_name=normalized, **kwargs)
        self.session.add(company)
        self.session.flush()
        return company


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


class JobRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self, job: JobPosting, source: str, source_id: str | None = None
    ) -> JobPostingRow:
        """Insert or update a job keyed on (source, source_id).

        Falls back to dedup_key when the source provides no id.
        """
        row = job_to_row(job, source, source_id)
        existing: Optional[JobPostingRow] = None
        if source_id is not None:
            existing = self.session.exec(
                select(JobPostingRow).where(
                    JobPostingRow.source == source,
                    JobPostingRow.source_id == source_id,
                )
            ).first()
        if existing is None:
            self.session.add(row)
            self.session.flush()
            return row
        # Update mutable fields in place.
        for field in (
            "title",
            "company_name",
            "location",
            "url",
            "description",
            "extra",
        ):
            setattr(existing, field, getattr(row, field))
        existing.dedup_key = row.dedup_key
        existing.fetched_at = datetime.utcnow()
        self.session.add(existing)
        self.session.flush()
        return existing

    def get(self, job_id: int) -> Optional[JobPostingRow]:
        return self.session.get(JobPostingRow, job_id)

    def list(self, include_duplicates: bool = False) -> list[JobPostingRow]:
        stmt = select(JobPostingRow)
        if not include_duplicates:
            stmt = stmt.where(JobPostingRow.is_duplicate == False)  # noqa: E712
        return list(self.session.exec(stmt).all())

    def count(self) -> int:
        return len(list(self.session.exec(select(JobPostingRow)).all()))


# --------------------------------------------------------------------------- #
# CV profiles
# --------------------------------------------------------------------------- #


class CVRepository:
    def __init__(self, session: Session):
        self.session = session

    def save(self, profile: CVProfile) -> CVProfileRow:
        row = CVProfileRow(
            name=profile.name,
            email=profile.email,
            phone=profile.phone,
            linkedin=profile.linkedin,
            github=profile.github,
            summary=profile.summary,
            payload=profile.model_dump_json(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, cv_id: int) -> Optional[CVProfile]:
        row = self.session.get(CVProfileRow, cv_id)
        if row is None or not row.payload:
            return None
        return CVProfile.model_validate_json(row.payload)

    # -- Candidate profile (CV + application answers) ---------------------- #

    def save_candidate(self, candidate) -> CVProfileRow:
        """Persist a full CandidateProfile, encrypted at rest."""
        profile = candidate.cv
        row = CVProfileRow(
            name=profile.name,
            email=profile.email,
            phone=profile.phone,
            linkedin=profile.linkedin,
            github=profile.github,
            summary=profile.summary,
            payload=profile.model_dump_json(),
            candidate_payload=candidate.model_dump_json(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get_candidate(self, cv_id: int):
        """Load a CandidateProfile, upgrading a CV-only row if needed."""
        from ..candidate import CandidateProfile

        row = self.session.get(CVProfileRow, cv_id)
        if row is None:
            return None
        if row.candidate_payload:
            return CandidateProfile.model_validate_json(row.candidate_payload)
        # Older rows predate the candidate profile: wrap the CV so the caller
        # gets a usable object rather than None.
        if row.payload:
            return CandidateProfile(cv=CVProfile.model_validate_json(row.payload))
        return None

    def update_candidate(self, cv_id: int, candidate) -> Optional[CVProfileRow]:
        row = self.session.get(CVProfileRow, cv_id)
        if row is None:
            return None
        row.candidate_payload = candidate.model_dump_json()
        row.payload = candidate.cv.model_dump_json()
        row.name = candidate.cv.name
        row.email = candidate.cv.email
        row.phone = candidate.cv.phone
        self.session.add(row)
        self.session.flush()
        return row


# --------------------------------------------------------------------------- #
# Contacts
# --------------------------------------------------------------------------- #


class ContactRepository:
    def __init__(self, session: Session):
        self.session = session

    def save(self, name: str, email: str | None = None, **kwargs) -> ContactRow:
        row = ContactRow(
            name=name,
            email=email,
            email_hash=deterministic_hash(email) if email else None,
            **kwargs,
        )
        self.session.add(row)
        self.session.flush()
        return row


# --------------------------------------------------------------------------- #
# Email drafts
# --------------------------------------------------------------------------- #


class DraftRepository:
    def __init__(self, session: Session):
        self.session = session

    def save(self, draft: EmailDraft, job_id: int | None = None) -> EmailDraftRow:
        row = EmailDraftRow(
            subject=draft.subject,
            body=draft.body,
            recipient_email=draft.recipient_email,
            recipient_name=draft.recipient_name,
            job_id=job_id,
            company=draft.company,
            job_title=draft.job_title,
            word_count=draft.word_count,
            gmail_draft_id=draft.gmail_draft_id,
        )
        self.session.add(row)
        self.session.flush()
        return row


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #


class ApplicationRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_dedup(
        self, dedup_key: str, cv_profile_id: int | None
    ) -> Optional[ApplicationRow]:
        return self.session.exec(
            select(ApplicationRow).where(
                ApplicationRow.job_dedup_key == dedup_key,
                ApplicationRow.cv_profile_id == cv_profile_id,
            )
        ).first()

    def create(
        self,
        job: JobPostingRow,
        cv_profile_id: int | None = None,
        status: ApplicationStatus = ApplicationStatus.SAVED,
    ) -> ApplicationRow:
        row = ApplicationRow(
            job_id=job.id,
            job_dedup_key=job.dedup_key,
            cv_profile_id=cv_profile_id,
            status=status,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list(self) -> list[ApplicationRow]:
        return list(self.session.exec(select(ApplicationRow)).all())


# --------------------------------------------------------------------------- #
# Suppression list
# --------------------------------------------------------------------------- #


class SuppressionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, email: str, reason: str = "opt_out") -> SuppressionRow:
        h = deterministic_hash(email)
        existing = self.session.exec(
            select(SuppressionRow).where(SuppressionRow.email_hash == h)
        ).first()
        if existing:
            return existing
        row = SuppressionRow(email_hash=h, reason=reason)
        self.session.add(row)
        self.session.flush()
        return row

    def is_suppressed(self, email: str) -> bool:
        h = deterministic_hash(email)
        return (
            self.session.exec(
                select(SuppressionRow).where(SuppressionRow.email_hash == h)
            ).first()
            is not None
        )


# --------------------------------------------------------------------------- #
# JSON import path (migration off the legacy careeragent_data/ files)
# --------------------------------------------------------------------------- #


def import_legacy_json(session: Session, data_dir: str) -> dict[str, int]:
    """Import legacy filesystem JSON (careeragent_data/) into the DB.

    Returns a count of imported records per type. Missing directories are
    skipped so this is safe to run on a fresh checkout.
    """
    import os

    counts = {"job_postings": 0, "cv_profiles": 0, "email_drafts": 0}
    jobs = JobRepository(session)
    cvs = CVRepository(session)
    drafts = DraftRepository(session)

    def _load_dir(subdir: str):
        path = os.path.join(data_dir, subdir)
        if not os.path.isdir(path):
            return
        for fname in sorted(os.listdir(path)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(path, fname), encoding="utf-8") as fh:
                yield json.load(fh)

    for data in _load_dir("job_postings"):
        jobs.upsert(JobPosting.model_validate(data), source="legacy_import")
        counts["job_postings"] += 1
    for data in _load_dir("cv_profiles"):
        cvs.save(CVProfile.model_validate(data))
        counts["cv_profiles"] += 1
    for data in _load_dir("email_drafts"):
        drafts.save(EmailDraft.model_validate(data))
        counts["email_drafts"] += 1

    return counts
