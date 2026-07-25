"""Keyless free job-board adapters.

Fixtures reproduce each provider's **documented** response shape. They are not
proof the live API matches -- ``scripts/verify_sources.py`` is what checks that
on a connected machine. These tests pin our parsing behaviour, including the
awkward cases (epoch timestamps, list-or-string fields, RemoteOK's legal
notice element).
"""

from __future__ import annotations

import httpx
import respx

from core.ingestion import (
    ArbeitnowSource,
    HimalayasSource,
    JobicySource,
    RemoteOKSource,
)


@respx.mock
def test_arbeitnow_parses_documented_shape():
    respx.get(url__regex=r"https://www\.arbeitnow\.com/api/job-board-api.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "slug": "senior-dev-berlin-123",
                        "company_name": "Acme GmbH",
                        "title": "Senior Developer",
                        "description": "<p>Build <b>things</b>.</p>",
                        "remote": True,
                        "url": "https://www.arbeitnow.com/jobs/senior-dev-berlin-123",
                        "tags": ["python", "django"],
                        "job_types": ["full-time"],
                        "location": "Berlin",
                        "created_at": 1782000000,
                    }
                ],
                "links": {"next": None},
                "meta": {"current_page": 1},
            },
        )
    )
    with httpx.Client() as client:
        jobs = ArbeitnowSource().fetch(client)

    assert len(jobs) == 1
    fj = jobs[0]
    assert fj.job.title == "Senior Developer"
    assert fj.job.company == "Acme GmbH"
    assert fj.remote is True
    assert fj.employment_type == "full-time"
    assert fj.job.tech_stack == ["python", "django"]
    assert "<b>" not in fj.job.description  # HTML stripped
    assert fj.date_posted is not None  # epoch parsed


@respx.mock
def test_arbeitnow_visa_sponsorship_param_is_sent():
    route = respx.get(
        url__regex=r"https://www\.arbeitnow\.com/api/job-board-api.*"
    ).mock(return_value=httpx.Response(200, json={"data": []}))
    with httpx.Client() as client:
        ArbeitnowSource().fetch(client, visa_sponsorship=True)
    assert "visa_sponsorship=true" in str(route.calls[0].request.url)


@respx.mock
def test_himalayas_caps_limit_at_provider_maximum():
    route = respx.get(url__regex=r"https://himalayas\.app/jobs/api.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "guid": "abc",
                        "title": "Remote SRE",
                        "companyName": "Globex",
                        "excerpt": "Run things",
                        "applicationLink": "https://himalayas.app/jobs/abc",
                        "pubDate": 1782000000,
                        "minSalary": 120000,
                        "maxSalary": 150000,
                        "currency": "USD",
                        "type": "Full Time",
                        "locationRestrictions": ["Worldwide"],
                        "categories": ["DevOps"],
                    }
                ],
                "total": 1,
            },
        )
    )
    with httpx.Client() as client:
        jobs = HimalayasSource().fetch(client, limit=500)  # over the cap

    # The provider rejects limits above 20, so we clamp before sending.
    assert "limit=20" in str(route.calls[0].request.url)
    fj = jobs[0]
    assert fj.job.company == "Globex"
    assert fj.remote is True
    assert (fj.salary_min, fj.salary_max, fj.salary_currency) == (
        120000,
        150000,
        "USD",
    )


@respx.mock
def test_jobicy_parses_salary_and_list_fields():
    respx.get(url__regex=r"https://jobicy\.com/api/v2/remote-jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobCount": 1,
                "jobs": [
                    {
                        "id": 99,
                        "url": "https://jobicy.com/jobs/99",
                        "jobTitle": "Data Engineer",
                        "companyName": "Initech",
                        "jobIndustry": ["Data Science"],
                        "jobType": ["full-time"],
                        "jobGeo": "USA",
                        "jobExcerpt": "Pipelines",
                        "jobDescription": "<p>ETL</p>",
                        "pubDate": "2026-06-01 10:00:00",
                        "annualSalaryMin": 100000,
                        "annualSalaryMax": 130000,
                        "salaryCurrency": "USD",
                    }
                ],
            },
        )
    )
    with httpx.Client() as client:
        jobs = JobicySource().fetch(client, count=5)

    fj = jobs[0]
    assert fj.job.title == "Data Engineer"
    assert fj.employment_type == "full-time"
    assert fj.job.tech_stack == ["Data Science"]
    assert fj.salary_min == 100000
    assert fj.date_posted is not None


@respx.mock
def test_remoteok_skips_the_legal_notice_element():
    """RemoteOK's first array element is an attribution notice, not a job."""
    respx.get("https://remoteok.com/api").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "legal": "See https://remoteok.com/api for terms. "
                    "Attribution required."
                },
                {
                    "id": "777",
                    "company": "Hooli",
                    "position": "Backend Engineer",
                    "tags": ["go", "postgres"],
                    "description": "<p>Services</p>",
                    "location": "Worldwide",
                    "salary_min": 90000,
                    "salary_max": 120000,
                    "date": "2026-06-15T00:00:00+00:00",
                    "url": "https://remoteok.com/l/777",
                },
            ],
        )
    )
    with httpx.Client() as client:
        jobs = RemoteOKSource().fetch(client)

    assert len(jobs) == 1  # notice element dropped
    assert jobs[0].job.company == "Hooli"
    assert jobs[0].salary_min == 90000
    assert jobs[0].remote is True


@respx.mock
def test_remoteok_handles_non_list_payload():
    respx.get("https://remoteok.com/api").mock(
        return_value=httpx.Response(200, json={"error": "rate limited"})
    )
    with httpx.Client() as client:
        assert RemoteOKSource().fetch(client) == []


@respx.mock
def test_adapters_tolerate_missing_optional_fields():
    """A sparse payload must degrade to None, never raise."""
    respx.get(url__regex=r"https://jobicy\.com/api/v2/remote-jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={"jobs": [{"jobTitle": "Minimal", "companyName": "Tiny Co"}]},
        )
    )
    with httpx.Client() as client:
        fj = JobicySource().fetch(client)[0]
    assert fj.job.title == "Minimal"
    assert fj.salary_min is None
    assert fj.date_posted is None
    assert fj.employment_type is None
