"""Phase 6 -- application tracking pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.db.repository import JobRepository
from core.db.tables import ApplicationStatus
from core.models import JobPosting
from core.tracking import (
    BlacklistedCompanyError,
    DuplicateApplicationError,
    InvalidTransition,
    TrackingService,
)


def _job(session, title="Engineer", company="Acme", loc="Remote", sid="1"):
    row = JobRepository(session).upsert(
        JobPosting(title=title, company=company, location=loc), "greenhouse", sid
    )
    session.commit()
    return row


def test_create_and_apply_sets_followup(session):
    job = _job(session)
    svc = TrackingService(session, follow_up_days=7)
    app = svc.create_application(job)
    assert app.status == ApplicationStatus.SAVED
    svc.transition(app, ApplicationStatus.APPLIED)
    session.commit()
    assert app.applied_at is not None
    assert app.next_follow_up_at is not None
    delta = app.next_follow_up_at - app.applied_at
    assert abs(delta - timedelta(days=7)) < timedelta(seconds=2)


def test_full_pipeline_transitions(session):
    job = _job(session)
    svc = TrackingService(session)
    app = svc.create_application(job)
    for status in (
        ApplicationStatus.APPLIED,
        ApplicationStatus.SCREENING,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.OFFER,
    ):
        svc.transition(app, status)
    session.commit()
    assert app.status == ApplicationStatus.OFFER


def test_illegal_transition_rejected(session):
    job = _job(session)
    svc = TrackingService(session)
    app = svc.create_application(job)
    with pytest.raises(InvalidTransition):
        svc.transition(app, ApplicationStatus.OFFER)  # can't skip from SAVED


def test_duplicate_application_blocked(session):
    job = _job(session)
    svc = TrackingService(session)
    svc.create_application(job)
    session.commit()
    # Same job (same dedup key), still active -> blocked.
    dup_job = _job(session, sid="2")  # different source id, same title/company/loc
    with pytest.raises(DuplicateApplicationError):
        svc.create_application(dup_job)


def test_duplicate_allowed_after_withdrawn(session):
    job = _job(session)
    svc = TrackingService(session)
    app = svc.create_application(job)
    svc.transition(app, ApplicationStatus.WITHDRAWN)
    session.commit()
    dup_job = _job(session, sid="2")
    again = svc.create_application(dup_job)  # no longer active -> allowed
    assert again.status == ApplicationStatus.SAVED


def test_blacklist_blocks_application(session):
    svc = TrackingService(session)
    svc.blacklist_company("Acme Inc.")
    session.commit()
    job = _job(session, company="Acme")  # normalizes to same as "Acme Inc."
    assert svc.is_blacklisted("Acme") is True
    with pytest.raises(BlacklistedCompanyError):
        svc.create_application(job)


def test_due_followups(session):
    job = _job(session)
    svc = TrackingService(session, follow_up_days=7)
    app = svc.create_application(job)
    svc.transition(app, ApplicationStatus.APPLIED)
    session.commit()
    # Not due yet.
    assert svc.due_followups(as_of=datetime.utcnow()) == []
    # Due after the window.
    later = datetime.utcnow() + timedelta(days=8)
    due = svc.due_followups(as_of=later)
    assert len(due) == 1 and due[0].id == app.id


def test_snooze_followup(session):
    job = _job(session)
    svc = TrackingService(session)
    app = svc.create_application(job)
    svc.transition(app, ApplicationStatus.APPLIED)
    before = app.next_follow_up_at
    svc.snooze_followup(app, days=3)
    session.commit()
    assert app.next_follow_up_at - before == timedelta(days=3)


def test_board_groups_by_status(session):
    svc = TrackingService(session)
    a = svc.create_application(_job(session, title="A", sid="1", loc="NYC"))
    b = svc.create_application(_job(session, title="B", sid="2", loc="LA"))
    svc.transition(b, ApplicationStatus.APPLIED)
    session.commit()
    board = svc.board()
    assert len(board["saved"]) == 1 and board["saved"][0].id == a.id
    assert len(board["applied"]) == 1 and board["applied"][0].id == b.id
