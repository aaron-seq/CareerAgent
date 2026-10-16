"""Phase 6 -- application tracking pipeline."""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone

import pytest

from core.db.repository import JobRepository
from core.db.tables import ApplicationStatus
from core.models import JobPosting
from core.normalize import ensure_utc, utc_now
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
    assert svc.due_followups(as_of=utc_now()) == []
    # Due after the window.
    later = utc_now() + timedelta(days=8)
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


# --------------------------------------------------------------------------- #
# Aware-UTC timestamp convention (ADR 0008)
# --------------------------------------------------------------------------- #


def test_utc_now_is_aware_utc_and_emits_no_deprecation():
    """``utc_now`` must be aware, hold UTC, and not warn.

    Guards both ways the obvious "fix" goes wrong: ``datetime.utcnow()``
    (DeprecationWarning, and naive) and ``datetime.now()`` (no warning, but
    naive local wall-clock rather than UTC).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        now = utc_now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    drift = abs((now - datetime.now(timezone.utc)).total_seconds())
    assert drift < 60, "utc_now() returned local time, not UTC"


def test_ensure_utc_converts_offsets_and_labels_naive_as_utc():
    ist = timezone(timedelta(hours=5, minutes=30))
    aware = datetime(2026, 1, 1, 0, 0, tzinfo=ist)
    converted = ensure_utc(aware)
    assert converted == datetime(2025, 12, 31, 18, 30, tzinfo=timezone.utc)
    assert converted.utcoffset() == timedelta(0)
    # Converted, not relabelled: the wall-clock moved.
    assert converted.hour == 18

    naive = datetime(2026, 1, 1, 0, 0)
    labelled = ensure_utc(naive)
    assert labelled == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

    # Idempotent.
    assert ensure_utc(labelled) == labelled
    assert ensure_utc(labelled).tzinfo is timezone.utc


def test_due_followups_compares_against_rows_reloaded_from_sqlite(session):
    """Rows reloaded from SQLite must come back aware UTC.

    SQLite's DATETIME storage carries no offset. The ``UTCDateTime`` column
    type re-attaches UTC on read -- on every sqlmodel release, old (which
    would otherwise return naive) and new -- so comparing against the aware
    ``utc_now()`` never raises ``TypeError: can't compare offset-naive and
    offset-aware datetimes``.
    """
    job = _job(session)
    svc = TrackingService(session, follow_up_days=7)
    app = svc.create_application(job)
    svc.transition(app, ApplicationStatus.APPLIED)
    session.commit()
    session.expire_all()  # drop the identity-map copies, force a real reload

    reloaded = svc.apps.list()[0]
    assert reloaded.next_follow_up_at is not None
    assert reloaded.next_follow_up_at.utcoffset() == timedelta(0)
    assert reloaded.created_at.utcoffset() == timedelta(0)

    # Both the defaulted and the explicit `as_of` path must survive.
    assert svc.due_followups() == []
    due = svc.due_followups(as_of=utc_now() + timedelta(days=8))
    assert len(due) == 1 and due[0].id == app.id


def test_due_followups_accepts_a_naive_as_of(session):
    """Legacy callers passing naive UTC must not hit a naive/aware TypeError."""
    job = _job(session)
    svc = TrackingService(session, follow_up_days=7)
    app = svc.create_application(job)
    svc.transition(app, ApplicationStatus.APPLIED)
    session.commit()
    session.expire_all()

    naive_later = (utc_now() + timedelta(days=8)).replace(tzinfo=None)
    due = svc.due_followups(as_of=naive_later)
    assert [a.id for a in due] == [app.id]


def test_naive_value_assigned_in_memory_is_stored_and_read_as_utc(session):
    """A naive datetime written to a column is taken as UTC, not rejected.

    sqlmodel >= 0.0.45's own type raises on naive input; ours coerces, so a
    legacy caller (or a pre-migration row) keeps working on every version.
    """
    job = _job(session)
    svc = TrackingService(session)
    app = svc.create_application(job)
    app.next_follow_up_at = datetime(2026, 3, 1, 9, 0)  # naive
    session.add(app)
    session.commit()
    session.expire_all()

    reloaded = svc.apps.list()[0]
    assert reloaded.next_follow_up_at == datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)

    # In-memory naive values on unflushed rows are also tolerated.
    reloaded.next_follow_up_at = datetime(2020, 1, 1)
    assert [a.id for a in svc.due_followups()] == [reloaded.id]


def test_offset_datetime_is_converted_to_utc_on_write(session):
    """An aware non-UTC value is stored as the same instant in UTC."""
    ist = timezone(timedelta(hours=5, minutes=30))
    job = _job(session)
    svc = TrackingService(session)
    app = svc.create_application(job)
    app.next_follow_up_at = datetime(2026, 3, 1, 0, 0, tzinfo=ist)
    session.add(app)
    session.commit()
    session.expire_all()

    stored = svc.apps.list()[0].next_follow_up_at
    assert stored == datetime(2026, 2, 28, 18, 30, tzinfo=timezone.utc)
    assert stored.utcoffset() == timedelta(0)
