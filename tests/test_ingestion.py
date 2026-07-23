"""Phase 2 -- job ingestion adapters (HTTP mocked with respx)."""

from __future__ import annotations

import httpx
import respx

from core.db.repository import JobRepository
from core.ingestion import (
    AdzunaSource,
    AshbySource,
    GreenhouseSource,
    IngestionService,
    LeverSource,
    RemotiveSource,
    TheMuseSource,
)


@respx.mock
def test_greenhouse_adapter_parses_board():
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Software Engineer",
                        "location": {"name": "Remote - US"},
                        "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123",
                        "content": "<p>Build <b>payments</b>.</p>",
                    }
                ]
            },
        )
    )
    src = GreenhouseSource("stripe", company_name="Stripe")
    with httpx.Client() as client:
        jobs = src.fetch(client)
    assert len(jobs) == 1
    fj = jobs[0]
    assert fj.job.title == "Software Engineer"
    assert fj.job.company == "Stripe"
    assert fj.source_id == "123"
    assert fj.remote is True
    assert "payments" in fj.job.description
    assert "<b>" not in fj.job.description  # HTML stripped


@respx.mock
def test_lever_adapter_parses_workplace_type():
    respx.get("https://api.lever.co/v0/postings/netflix?mode=json").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "abc-1",
                    "text": "Senior Backend Engineer",
                    "categories": {
                        "location": "Los Angeles",
                        "commitment": "Full-time",
                    },
                    "workplaceType": "remote",
                    "descriptionPlain": "Own the streaming backend.",
                    "hostedUrl": "https://jobs.lever.co/netflix/abc-1",
                }
            ],
        )
    )
    src = LeverSource("netflix", company_name="Netflix")
    with httpx.Client() as client:
        jobs = src.fetch(client)
    assert jobs[0].remote is True
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].job.description == "Own the streaming backend."


@respx.mock
def test_ashby_adapter_parses_compensation():
    respx.get(
        "https://api.ashbyhq.com/posting-api/job-board/ramp?includeCompensation=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": "job-9",
                        "title": "ML Engineer",
                        "location": "New York",
                        "jobUrl": "https://jobs.ashbyhq.com/ramp/job-9",
                        "descriptionPlain": "Fraud models.",
                        "isRemote": False,
                        "compensation": {"compensationTierSummary": "$180K - $220K"},
                    }
                ]
            },
        )
    )
    src = AshbySource("ramp", company_name="Ramp")
    with httpx.Client() as client:
        jobs = src.fetch(client)
    assert jobs[0].job.salary_range == "$180K - $220K"
    assert jobs[0].remote is False


@respx.mock
def test_adzuna_adapter_parses_salary_and_date():
    respx.get(url__regex=r"https://api\.adzuna\.com/v1/api/jobs/gb/search/1.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "555",
                        "title": "Data Scientist",
                        "company": {"display_name": "Acme"},
                        "location": {"display_name": "London"},
                        "description": "Analytics.",
                        "redirect_url": "https://adzuna.example/555",
                        "salary_min": 60000,
                        "salary_max": 80000,
                        "contract_time": "full_time",
                        "created": "2026-07-01T09:00:00Z",
                    }
                ]
            },
        )
    )
    src = AdzunaSource("id", "key", country="gb")
    with httpx.Client() as client:
        jobs = src.fetch(client, what="data scientist")
    fj = jobs[0]
    assert fj.salary_min == 60000
    assert fj.salary_max == 80000
    assert fj.salary_currency == "GBP"
    assert fj.date_posted is not None and fj.date_posted.year == 2026


@respx.mock
def test_themuse_adapter():
    respx.get(url__regex=r"https://www\.themuse\.com/api/public/v2/jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 77,
                        "name": "Product Designer",
                        "company": {"name": "Muse Co"},
                        "locations": [{"name": "Flexible / Remote"}],
                        "contents": "<p>Design things.</p>",
                        "refs": {"landing_page": "https://themuse.example/77"},
                        "type": "full-time",
                        "publication_date": "2026-06-15T00:00:00Z",
                    }
                ]
            },
        )
    )
    src = TheMuseSource(api_key="k")
    with httpx.Client() as client:
        jobs = src.fetch(client)
    assert jobs[0].job.company == "Muse Co"
    assert jobs[0].remote is True


@respx.mock
def test_remotive_adapter_is_always_remote():
    respx.get(url__regex=r"https://remotive\.com/api/remote-jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 9001,
                        "title": "DevRel Engineer",
                        "company_name": "RemoteCorp",
                        "candidate_required_location": "Worldwide",
                        "description": "<p>Advocate.</p>",
                        "url": "https://remotive.example/9001",
                        "job_type": "full_time",
                    }
                ]
            },
        )
    )
    src = RemotiveSource()
    with httpx.Client() as client:
        jobs = src.fetch(client)
    assert jobs[0].remote is True


# --------------------------------------------------------------------------- #
# IngestionService: persistence + idempotency + error isolation
# --------------------------------------------------------------------------- #


@respx.mock
def test_ingestion_service_persists_and_is_idempotent(session):
    respx.get(
        "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "u",
                        "content": "c",
                    },
                    {
                        "id": 2,
                        "title": "Designer",
                        "location": {"name": "NYC"},
                        "absolute_url": "u2",
                        "content": "c2",
                    },
                ]
            },
        )
    )
    service = IngestionService(session)
    src = GreenhouseSource("stripe", company_name="Stripe")
    with httpx.Client() as client:
        r1 = service.ingest(src, client=client)
        r2 = service.ingest(src, client=client)  # re-ingest same board
    session.commit()

    assert r1.fetched == 2
    assert r1.upserted == 2
    # Re-ingest must not duplicate rows.
    assert JobRepository(session).count() == 2
    assert r2.upserted == 2  # upsert touched the same 2 rows

    # Structured extras persisted on the row.
    rows = JobRepository(session).list()
    remote_row = next(r for r in rows if r.title == "Engineer")
    assert remote_row.remote is True


@respx.mock
def test_ingestion_service_isolates_source_errors(session):
    respx.get("https://api.lever.co/v0/postings/broken?mode=json").mock(
        return_value=httpx.Response(500)
    )
    service = IngestionService(session)
    src = LeverSource("broken")
    with httpx.Client() as client:
        result = service.ingest(src, client=client)
    assert result.fetched == 0
    assert result.errors  # captured, not raised
    assert JobRepository(session).count() == 0
