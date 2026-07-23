"""Database layer: SQLModel tables, session management, and repositories."""

from .session import get_engine, get_session, init_db, reset_engine
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

__all__ = [
    "get_engine",
    "get_session",
    "init_db",
    "reset_engine",
    "ApplicationRow",
    "ApplicationStatus",
    "Company",
    "ContactRow",
    "CVProfileRow",
    "EmailDraftRow",
    "JobPostingRow",
    "SuppressionRow",
]
