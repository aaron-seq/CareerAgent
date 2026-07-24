"""Tests for the UI facade (the boundary app.py calls into)."""

from __future__ import annotations

import httpx
import pytest
import respx

from core import facade
from core.db import reset_engine
from core.models import CVProfile, EmailDraft, Experience
from core.outreach import ComplianceConfig, LIARecord


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the global engine at a throwaway SQLite file for the facade."""
    db = tmp_path / "facade.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    facade.init_persistence()
    yield
    reset_engine()


def _cv() -> CVProfile:
    return CVProfile(
        name="Ada Lovelace",
        email="ada@example.com",
        skills=["Python", "PyTorch"],
        experiences=[
            Experience(
                title="ML Eng",
                company="AI Co",
                duration="3y",
                technologies=["Python", "PyTorch"],
            )
        ],
    )


def test_persist_and_load_cv(temp_db):
    cv_id = facade.persist_cv(_cv())
    loaded = facade.load_cv(cv_id)
    assert loaded is not None and loaded.name == "Ada Lovelace"


@respx.mock
def test_ingest_score_and_top_jobs(temp_db):
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
                        "absolute_url": "u1",
                        "content": "Python and PyTorch.",
                    },
                    {
                        "id": 2,
                        "title": "Accountant",
                        "location": {"name": "NYC"},
                        "absolute_url": "u2",
                        "content": "Tax filings.",
                    },
                ]
            },
        )
    )
    with httpx.Client() as client:
        result = facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)
    assert result.upserted == 2

    facade.refresh_matches(_cv())
    jobs = facade.top_jobs()
    assert jobs[0]["title"] == "Machine Learning Engineer"  # best match first
    assert jobs[0]["score"] >= jobs[-1]["score"]
    assert "python" in jobs[0]["matched"]


@respx.mock
def test_pipeline_flow(temp_db):
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "ML Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u1",
                        "content": "ML",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        facade.ingest_ats("greenhouse", "stripe", "Stripe", client=client)
    job = facade.top_jobs()[0]

    added = facade.add_to_pipeline(job["id"])
    assert added["ok"] is True
    app_id = added["application_id"]

    # Duplicate is prevented.
    assert facade.add_to_pipeline(job["id"])["ok"] is False

    # Advance and see it move on the board.
    assert facade.advance_application(app_id, "applied")["ok"] is True
    board = facade.pipeline_board()
    assert len(board["applied"]) == 1
    assert facade.funnel()["reached"]["applied"] == 1


def test_advance_illegal_transition_returns_error(temp_db):
    # No such application.
    assert facade.advance_application(999, "applied")["ok"] is False


def test_compliance_gate_and_opt_out(temp_db):
    config = ComplianceConfig(
        sender_name="Ada",
        sender_email="ada@example.com",
        postal_address="1 Analytical Way",
        unsubscribe="mailto:ada@example.com",
    )
    lia = LIARecord(campaign="c", purpose="p", necessity="n", balancing="b")
    draft = EmailDraft(
        subject="Hi", body="Hello", recipient_email="hm@corp.com", company="Corp"
    )
    decision = facade.compliance_gate(draft, config, lia, resolver=lambda d: ["mx"])
    assert decision.allowed is True

    facade.record_opt_out("hm@corp.com")
    blocked = facade.compliance_gate(draft, config, lia, resolver=lambda d: ["mx"])
    assert blocked.allowed is False


def test_unsupported_ats_raises(temp_db):
    with pytest.raises(ValueError):
        facade.ingest_ats("workday", "acme")
