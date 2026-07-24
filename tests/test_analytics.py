"""Phase 10 -- analytics: funnel, A/B variants, interview prep."""

from __future__ import annotations

from core.analytics import (
    compute_funnel,
    generate_interview_questions,
    variant_response_rates,
)
from core.db.repository import JobRepository
from core.db.tables import ApplicationStatus
from core.models import JobPosting
from core.tracking import TrackingService


def _seed_applications(session):
    jobs = JobRepository(session)
    svc = TrackingService(session)
    apps = []
    for i in range(5):
        row = jobs.upsert(
            JobPosting(title=f"Role {i}", company=f"Co{i}", location="Remote"),
            "greenhouse",
            str(i),
        )
        apps.append(svc.create_application(row))
    session.commit()
    # Advance them to varying stages.
    svc.transition(apps[0], ApplicationStatus.APPLIED)
    svc.transition(apps[1], ApplicationStatus.APPLIED)
    svc.transition(apps[1], ApplicationStatus.SCREENING)
    svc.transition(apps[2], ApplicationStatus.APPLIED)
    svc.transition(apps[2], ApplicationStatus.SCREENING)
    svc.transition(apps[2], ApplicationStatus.INTERVIEW)
    svc.transition(apps[3], ApplicationStatus.APPLIED)
    svc.transition(apps[3], ApplicationStatus.REJECTED)
    session.commit()
    return svc


def test_funnel_counts_and_conversion(session):
    svc = _seed_applications(session)
    funnel = compute_funnel(svc.apps.list())
    assert funnel.total == 5
    # apps[0..3] applied; apps[3] then rejected leaves the ladder.
    assert funnel.reached["applied"] == 3  # 0,1,2 still active on ladder
    assert funnel.reached["screening"] == 2  # 1,2
    assert funnel.reached["interview"] == 1  # 2
    assert funnel.rejected == 1
    conv = funnel.conversion(ApplicationStatus.APPLIED, ApplicationStatus.SCREENING)
    assert abs(conv - (2 / 3)) < 1e-9


def test_variant_response_rates():
    records = [
        ("technical", True),
        ("technical", False),
        ("impact", True),
        ("impact", True),
    ]
    stats = variant_response_rates(records)
    assert stats["technical"].response_rate == 0.5
    assert stats["impact"].response_rate == 1.0


def test_generate_interview_questions_from_jd():
    job = JobPosting(
        title="ML Engineer",
        company="Acme",
        tech_stack=["Python", "PyTorch"],
        requirements=["Own model deployment"],
        problems=["Reduce inference latency"],
    )
    qs = generate_interview_questions(job, limit=8)
    assert any("Python" in q for q in qs)
    assert any("model deployment" in q for q in qs)
    assert any("inference latency" in q for q in qs)
    assert len(qs) <= 8
    assert len(qs) == len(set(qs))  # de-duplicated
