"""
End-to-end pipeline test.

Exercises the whole internal flow with real wiring and mocked external
boundaries (HTTP via respx, embeddings via the deterministic HashingEmbedder,
DNS via a stub resolver):

    ingest -> dedup -> score -> track -> digest -> tailor -> outreach gate

This is the "everything talks to everything" test. External services (live
APIs, real LLM, real email/DNS) are stubbed, per the environment's limits.
"""

from __future__ import annotations

import httpx
import respx

from core.alerting import build_digest
from core.analytics import compute_funnel
from core.db.repository import CVRepository, JobRepository
from core.db.tables import ApplicationStatus
from core.enrichment import SalaryEnricher, VisaSponsorFilter
from core.ingestion import GreenhouseSource, IngestionService, LeverSource
from core.matching import DedupService, HashingEmbedder, ScoringService
from core.models import CVProfile, EmailDraft, Experience, JobPosting
from core.outreach import ComplianceConfig, LIARecord, OutreachService
from core.resume import tailor_resume
from core.tracking import TrackingService


def _cv() -> CVProfile:
    return CVProfile(
        name="Ada Lovelace",
        email="ada@example.com",
        summary="ML engineer",
        skills=["Python", "PyTorch", "SQL"],
        experiences=[
            Experience(
                title="ML Engineer",
                company="AI Co",
                duration="3y",
                achievements=["Cut inference latency 40%"],
                technologies=["Python", "PyTorch"],
            )
        ],
    )


@respx.mock
def test_full_pipeline(session):
    # --- 1. Ingest from two sources (one posting duplicated across boards) --- #
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "Machine Learning Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "https://stripe.example/1",
                        "content": "Build ML systems with Python and PyTorch.",
                    },
                    {
                        "id": 2,
                        "title": "Data Analyst",
                        "location": {"name": "NYC"},
                        "absolute_url": "https://stripe.example/2",
                        "content": "SQL reporting.",
                    },
                ]
            },
        )
    )
    respx.get("https://api.lever.co/v0/postings/stripe?mode=json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "dup",
                    "text": "Machine Learning Engineer",
                    "categories": {"location": "Remote"},
                    "workplaceType": "remote",
                    "descriptionPlain": "Build ML systems with Python and PyTorch.",
                    "hostedUrl": "https://lever.example/dup",
                }
            ],
        )
    )

    ingest = IngestionService(session)
    with httpx.Client() as client:
        r1 = ingest.ingest(GreenhouseSource("stripe", "Stripe"), client=client)
        r2 = ingest.ingest(LeverSource("stripe", "Stripe"), client=client)
    session.commit()
    assert r1.upserted == 2 and r2.upserted == 1
    assert JobRepository(session).count() == 3

    # --- 2. Dedup: the ML role appears on both boards -> collapse --- #
    dupes = DedupService(session).run()
    session.commit()
    assert dupes == 1
    visible = JobRepository(session).list(include_duplicates=False)
    assert len(visible) == 2

    # --- 3. Salary + visa enrichment --- #
    SalaryEnricher().enrich(session)
    from core.db.repository import CompanyRepository

    CompanyRepository(session).get_or_create("Stripe")
    session.commit()
    VisaSponsorFilter.from_csv().annotate(session)
    session.commit()

    # --- 4. Score against the CV --- #
    cv = _cv()
    embedder = HashingEmbedder()
    ScoringService(session, embedder=embedder).score_all(cv)
    session.commit()
    scored = sorted(
        JobRepository(session).list(include_duplicates=False),
        key=lambda r: r.match_score or 0,
        reverse=True,
    )
    ml_job = scored[0]
    assert "Machine Learning" in ml_job.title
    assert ml_job.match_score > scored[-1].match_score  # ML beats analyst

    # --- 5. Track: save + apply, with duplicate prevention --- #
    tracker = TrackingService(session)
    app = tracker.create_application(ml_job)
    tracker.transition(app, ApplicationStatus.APPLIED)
    session.commit()
    assert app.next_follow_up_at is not None
    funnel = compute_funnel(tracker.apps.list())
    assert funnel.reached["applied"] == 1

    # --- 6. Persist the CV (encrypted) --- #
    cv_row = CVRepository(session).save(cv)
    session.commit()
    assert CVRepository(session).get(cv_row.id).name == "Ada Lovelace"

    # --- 7. Digest of top matches --- #
    digest = build_digest(JobRepository(session).list(include_duplicates=False))
    assert digest.items and digest.items[0].title == ml_job.title
    assert "digest" in digest.to_markdown().lower()

    # --- 8. Truthfully tailor the resume to the top job --- #
    from core.db.repository import row_to_job

    tailored, report = tailor_resume(cv, row_to_job(ml_job), embedder=embedder)
    assert set(tailored.skills) == set(cv.skills)  # no fabrication
    assert "python" in [s.lower() for s in report.emphasized_skills]

    # --- 9. Outreach gate: compliant, verified, capped --- #
    config = ComplianceConfig(
        sender_name="Ada Lovelace",
        sender_email="ada@example.com",
        postal_address="1 Analytical Way, London",
        unsubscribe="mailto:ada@example.com?subject=unsubscribe",
    )
    outreach = OutreachService(session, config, resolver=lambda d: ["mx.corp"])
    draft = EmailDraft(
        subject="Application: ML Engineer",
        body="I'd love to discuss the ML Engineer role.",
        recipient_email="hiring@stripe.example",
        company="Stripe",
    )
    lia = LIARecord(
        campaign="ml-outreach",
        purpose="Relevant B2B job application",
        necessity="Direct role-specific contact",
        balancing="Business address, opt-out honored",
    )
    decision = outreach.prepare_send(draft, lia)
    assert decision.allowed is True
    assert "opt out" in decision.body.lower()

    # Opt-out is then honored on the next attempt.
    outreach.opt_out("hiring@stripe.example")
    session.commit()
    assert outreach.prepare_send(draft, lia).allowed is False
