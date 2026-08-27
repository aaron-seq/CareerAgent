"""
Application tracking pipeline.

A small state machine over :class:`ApplicationStatus` with:

* validated kanban transitions (saved -> applied -> screening -> ...),
* follow-up reminders (a due date set on "applied", queryable later),
* duplicate-application prevention (same job dedup key + CV, still active),
* a company blacklist that blocks new applications.

All persistence goes through the repositories from Phase 1.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .db.repository import ApplicationRepository, CompanyRepository
from .db.tables import ApplicationRow, ApplicationStatus, JobPostingRow
from .normalize import normalize_company_name, utc_now

# Allowed kanban transitions.
_ALLOWED: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.SAVED: {ApplicationStatus.APPLIED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.APPLIED: {
        ApplicationStatus.SCREENING,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.SCREENING: {
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.INTERVIEW: {
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.OFFER: {
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.WITHDRAWN: set(),
}

# Statuses that count as "actively in the pipeline" for dedup purposes.
_ACTIVE = {
    ApplicationStatus.SAVED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.SCREENING,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
}


class InvalidTransition(Exception):
    pass


class DuplicateApplicationError(Exception):
    pass


class BlacklistedCompanyError(Exception):
    pass


class TrackingService:
    def __init__(self, session, follow_up_days: int = 7):
        self.session = session
        self.follow_up_days = follow_up_days
        self.apps = ApplicationRepository(session)
        self.companies = CompanyRepository(session)

    # -- Blacklist -------------------------------------------------------- #

    def blacklist_company(self, name: str) -> None:
        self.companies.get_or_create(name, blacklisted=True)
        self.session.flush()

    def is_blacklisted(self, name: str) -> bool:
        from sqlmodel import select

        from .db.tables import Company

        normalized = normalize_company_name(name)
        company = self.session.exec(
            select(Company).where(Company.normalized_name == normalized)
        ).first()
        return bool(company and company.blacklisted)

    # -- Lifecycle -------------------------------------------------------- #

    def create_application(
        self, job: JobPostingRow, cv_profile_id: int | None = None
    ) -> ApplicationRow:
        """Create a SAVED application, guarding blacklist + duplicates."""
        if self.is_blacklisted(job.company_name):
            raise BlacklistedCompanyError(job.company_name)
        existing = self.apps.get_by_dedup(job.dedup_key, cv_profile_id)
        if existing is not None and existing.status in _ACTIVE:
            raise DuplicateApplicationError(
                f"Already tracking an active application for '{job.title}' "
                f"at '{job.company_name}'."
            )
        return self.apps.create(job, cv_profile_id=cv_profile_id)

    def transition(
        self, app: ApplicationRow, new_status: ApplicationStatus
    ) -> ApplicationRow:
        """Move an application to a new status if the transition is legal."""
        if new_status not in _ALLOWED[app.status]:
            raise InvalidTransition(f"{app.status.value} -> {new_status.value}")
        app.status = new_status
        app.updated_at = utc_now()
        if new_status == ApplicationStatus.APPLIED:
            app.applied_at = utc_now()
            app.next_follow_up_at = app.applied_at + timedelta(days=self.follow_up_days)
        if new_status in (ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN):
            app.next_follow_up_at = None
        self.session.add(app)
        self.session.flush()
        return app

    # -- Reminders -------------------------------------------------------- #

    def due_followups(self, as_of: datetime | None = None) -> list[ApplicationRow]:
        """Applications whose follow-up date has arrived and are still active."""
        as_of = as_of or utc_now()
        return [
            app
            for app in self.apps.list()
            if app.next_follow_up_at is not None
            and app.next_follow_up_at <= as_of
            and app.status in _ACTIVE
        ]

    def snooze_followup(self, app: ApplicationRow, days: int) -> ApplicationRow:
        base = app.next_follow_up_at or utc_now()
        app.next_follow_up_at = base + timedelta(days=days)
        self.session.add(app)
        self.session.flush()
        return app

    def board(self) -> dict[str, list[ApplicationRow]]:
        """Group applications by status for a kanban view."""
        columns: dict[str, list[ApplicationRow]] = {
            s.value: [] for s in ApplicationStatus
        }
        for app in self.apps.list():
            columns[app.status.value].append(app)
        return columns
