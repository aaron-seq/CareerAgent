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


# --------------------------------------------------------------------------- #
# End-to-end through the *facade* -- the path app.py actually takes.
#
# The test above wires services together directly, which is why a whole
# feature (follow-up reminders) could be green there while being unreachable
# from the UI. This one walks the candidate's real loop across the facade
# boundary only: discover -> save -> apply -> get reminded -> chase -> offer.
# --------------------------------------------------------------------------- #


def _greenhouse_mock(url: str) -> None:
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
                        "absolute_url": url,
                        "content": "Python PyTorch SQL " * 20,
                    }
                ]
            },
        )
    )


@respx.mock
def test_candidate_journey_through_the_facade(temp_db):
    from datetime import timedelta

    from core import facade
    from core.db import get_session
    from core.db.tables import ApplicationRow

    posting_url = "https://boards.greenhouse.io/stripe/jobs/1"
    _greenhouse_mock(posting_url)

    cv = _cv()
    cv_id = facade.persist_cv(cv)

    # 1. Discover: pull a real board and score it against the CV.
    with httpx.Client() as client:
        result = facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)
    assert result.upserted == 1
    facade.refresh_matches(cv)
    job = facade.top_jobs()[0]
    assert job["score"] is not None

    # 2. Save it, with the CV it was matched against.
    added = facade.add_to_pipeline(job["id"], cv_id)
    assert added["ok"] is True
    app_id = added["application_id"]

    # 3. The board hands back the posting URL, so the candidate can open the
    #    form the autofill extension fills.
    saved_card = facade.pipeline_board()["saved"][0]
    assert saved_card["url"] == posting_url
    assert saved_card["overdue"] is False

    # 4. The extension profile comes from the parsed CV, not retyping.
    assert facade.extension_profile(cv)["email"] == cv.email

    # 5. Apply. A follow-up is scheduled but not yet due.
    assert facade.advance_application(app_id, "applied")["ok"] is True
    assert facade.due_followups() == []

    # 6. A week passes with no reply -> the reminder fires.
    with get_session() as session:
        row = session.get(ApplicationRow, app_id)
        row.next_follow_up_at = row.next_follow_up_at - timedelta(days=8)
        session.add(row)

    due = facade.due_followups()
    assert [c["application_id"] for c in due] == [app_id]
    assert due[0]["overdue"] is True
    assert due[0]["url"] == posting_url

    # 7. Candidate chases, snoozes a week; the reminder clears.
    facade.set_application_notes(app_id, "Chased recruiter 2026-09-11")
    assert facade.snooze_followup(app_id, days=7)["ok"] is True
    assert facade.due_followups() == []

    # 8. It converts. Notes survive, the funnel reflects every stage reached,
    #    and a closed-out application stops nagging.
    for status in ("screening", "interview", "offer"):
        assert facade.advance_application(app_id, status)["ok"] is True

    offer_card = facade.pipeline_board()["offer"][0]
    assert offer_card["notes"] == "Chased recruiter 2026-09-11"
    assert offer_card["days_since_applied"] == 0

    funnel = facade.funnel()
    assert funnel["total"] == 1
    assert funnel["reached"]["offer"] == 1
    assert facade.due_followups() == []
