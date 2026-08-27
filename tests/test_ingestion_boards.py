"""
Ingestion adapters added 2026-08-27: the keyless boards (Arbeitnow, Jobicy,
RemoteOK, Himalayas) and the extra company-board ATSs (SmartRecruiters,
Recruitee, Workable).

Every fixture below is trimmed from a *real* response captured live on
2026-08-27, so the field names and their quirks (integer epoch dates, 0-means-
unknown salaries, RemoteOK's legal-notice element) are the ones the live APIs
actually emit. All HTTP is mocked -- no live calls in CI, per CLAUDE.md.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import respx

from core.db.repository import JobRepository
from core.ingestion import (
    ArbeitnowSource,
    HimalayasSource,
    IngestionService,
    JobicySource,
    RecruiteeSource,
    RemoteOKSource,
    SmartRecruitersSource,
    WorkableSource,
)

# --------------------------------------------------------------------------- #
# Keyless boards
# --------------------------------------------------------------------------- #


@respx.mock
def test_arbeitnow_maps_fields_and_epoch_date():
    respx.get(url__regex=r"https://www\.arbeitnow\.com/api/job-board-api.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "slug": "backend-engineer-berlin-433749",
                        "company_name": "Thorit",
                        "title": "Backend Engineer",
                        "description": "<h1>Worum es geht</h1><p>Build APIs.</p>",
                        "remote": True,
                        "url": "https://www.arbeitnow.com/jobs/companies/thorit/be",
                        "job_types": ["Full Time"],
                        "location": "Berlin",
                        "created_at": 1787766024,
                    }
                ],
                "meta": {"terms": "please do not abuse"},
            },
        )
    )
    with httpx.Client() as client:
        jobs = ArbeitnowSource().fetch(client)

    assert len(jobs) == 1
    fj = jobs[0]
    assert fj.job.title == "Backend Engineer"
    assert fj.job.company == "Thorit"
    assert fj.job.location == "Berlin"
    assert fj.source_id == "backend-engineer-berlin-433749"
    assert fj.remote is True
    assert fj.employment_type == "Full Time"
    # created_at is integer unix seconds, not an ISO string.
    assert fj.date_posted is not None and fj.date_posted.year == 2026
    assert "<h1>" not in fj.job.description and "Build APIs." in fj.job.description


@respx.mock
def test_arbeitnow_handles_job_types_serialized_as_an_object():
    """Caught only by the live run (2026-08-27): Arbeitnow's ``job_types`` is
    a PHP array serialized to JSON, so a sparse one arrives as an object keyed
    by the surviving index -- ``{"1": "manager"}`` rather than
    ``["manager"]``. 3 of 175 live postings were shaped that way, and
    ``job_types[0]`` raised ``KeyError: 0`` on the first of them, killing the
    whole page of results."""
    respx.get(url__regex=r"https://www\.arbeitnow\.com/api/job-board-api.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "slug": "ecommerce-brand-manager-london-207092",
                        "company_name": "Retail Co",
                        "title": "Ecommerce Brand Manager",
                        "description": "<p>Own the brand.</p>",
                        "remote": False,
                        "url": "https://www.arbeitnow.com/jobs/x",
                        "job_types": {"1": "manager"},  # verbatim live shape
                        "location": "London",
                        "created_at": 1787766024,
                    },
                    {
                        "slug": "no-types-at-all",
                        "company_name": "Other Co",
                        "title": "Analyst",
                        "description": "d",
                        "url": "https://www.arbeitnow.com/jobs/y",
                        "job_types": [],
                        "location": "Berlin",
                        "created_at": 1787766024,
                    },
                ]
            },
        )
    )
    with httpx.Client() as client:
        jobs = ArbeitnowSource().fetch(client)

    assert len(jobs) == 2, "one odd record must not abort the whole page"
    assert jobs[0].employment_type == "manager"
    assert jobs[1].employment_type is None


@respx.mock
def test_jobicy_maps_salary_and_forwards_tag():
    route = respx.get(url__regex=r"https://jobicy\.com/api/v2/remote-jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 151780,
                        "url": "https://jobicy.com/jobs/151780-director-ai",
                        "jobTitle": "Director, AI Enablement",
                        "companyName": "Bloomreach",
                        "jobType": ["Full-Time"],
                        "jobGeo": "USA",
                        "jobExcerpt": "excerpt",
                        "jobDescription": "<p>Lead AI.</p>",
                        "pubDate": "2026-08-26T12:42:49+00:00",
                        "salaryMin": 200000,
                        "salaryMax": 250000,
                        "salaryCurrency": "USD",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        jobs = JobicySource().fetch(client, tag="python")

    fj = jobs[0]
    assert fj.job.title == "Director, AI Enablement"
    assert fj.job.location == "USA"
    assert fj.remote is True  # Jobicy is remote-only
    assert (fj.salary_min, fj.salary_max, fj.salary_currency) == (
        200000.0,
        250000.0,
        "USD",
    )
    assert fj.employment_type == "Full-Time"
    assert fj.date_posted is not None
    assert "tag=python" in str(route.calls.last.request.url)


@respx.mock
def test_remoteok_skips_the_legal_notice_element():
    """RemoteOK's array starts with an attribution/legal object, not a job.
    Treating element 0 as a posting yields a junk row with an empty title and
    no URL, so it must be skipped -- by shape, not by a hardcoded index."""
    respx.get("https://remoteok.com/api").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "last_updated": 1787748281,
                    "legal": "API Terms of Service: Please link back ...",
                },
                {
                    "slug": "senior-backend-acme-1137142",
                    "id": "1137142",
                    "epoch": 1787683843,
                    "date": "2026-08-25T18:50:43+00:00",
                    "company": "Acme",
                    "position": "Senior Backend Engineer",
                    "tags": ["backend", "python"],
                    "description": "<p>Ship services.</p>",
                    "location": "Worldwide",
                    "apply_url": "https://remoteOK.com/remote-jobs/x/apply",
                    "salary_min": 100000,
                    "salary_max": 0,
                    "url": "https://remoteOK.com/remote-jobs/senior-backend-acme",
                },
            ],
        )
    )
    with httpx.Client() as client:
        jobs = RemoteOKSource().fetch(client)

    assert len(jobs) == 1, "the legal-notice element must not become a job"
    fj = jobs[0]
    assert fj.job.title == "Senior Backend Engineer"
    assert fj.job.company == "Acme"
    assert fj.source_id == "1137142"
    assert fj.remote is True
    assert fj.salary_min == 100000.0
    # RemoteOK writes 0 (not null) when a bound is unknown.
    assert fj.salary_max is None


@respx.mock
def test_himalayas_joins_location_restrictions_and_uses_epoch():
    respx.get(url__regex=r"https://himalayas\.app/jobs/api(\?.*)?$").mock(
        return_value=httpx.Response(
            200,
            json={
                "totalCount": 100551,
                "jobs": [
                    {
                        "title": "Speech to Text Collector",
                        "excerpt": "short",
                        "companyName": "TELUS International AI Inc",
                        "employmentType": "Part Time",
                        "minSalary": None,
                        "maxSalary": None,
                        "currency": "USD",
                        "locationRestrictions": ["Malaysia", "Singapore"],
                        "description": "<p>Record audio.</p>",
                        "pubDate": 1787709613,
                        "applicationLink": "https://himalayas.app/companies/x/jobs/y",
                        "guid": "https://himalayas.app/companies/x/jobs/y",
                    }
                ],
            },
        )
    )
    with httpx.Client() as client:
        jobs = HimalayasSource().fetch(client)

    fj = jobs[0]
    assert fj.job.company == "TELUS International AI Inc"
    assert fj.job.location == "Malaysia, Singapore"
    assert fj.remote is True
    assert fj.salary_min is None and fj.salary_max is None
    assert fj.date_posted is not None and fj.date_posted.year == 2026


@respx.mock
def test_himalayas_keyword_switches_to_the_search_endpoint():
    """The plain feed takes no query param; only /jobs/api/search does. A
    keyword sent to the plain feed would be silently ignored and quietly
    return the unfiltered newest postings."""
    route = respx.get(url__regex=r"https://himalayas\.app/jobs/api/search.*").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    with httpx.Client() as client:
        HimalayasSource().fetch(client, q="python")
    assert route.called
    assert "q=python" in str(route.calls.last.request.url)


# --------------------------------------------------------------------------- #
# Company-board ATSs
# --------------------------------------------------------------------------- #

_SR_LIST = {
    "offset": 0,
    "limit": 25,
    "totalFound": 1,
    "content": [
        {
            "id": "744000145800584",
            "name": "Senior Community Developer",
            "company": {"identifier": "Ubisoft2", "name": "Ubisoft"},
            "location": {
                "city": "Montreal",
                "region": "QC",
                "country": "ca",
                "remote": False,
            },
            "releasedDate": "2026-08-26T17:29:32.606Z",
            "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
        }
    ],
}

_SR_DETAIL = {
    "id": "744000145800584",
    "postingUrl": "https://jobs.smartrecruiters.com/Ubisoft2/744000145800584-senior",
    "jobAd": {
        "sections": {
            "companyDescription": {"text": "<p>Ubisoft makes games.</p>"},
            "jobDescription": {"text": "<p>Lead community strategy.</p>"},
            "qualifications": {"text": "<ul><li>5 years experience</li></ul>"},
        }
    },
}


@respx.mock
def test_smartrecruiters_pulls_description_from_the_detail_endpoint():
    base = "https://api.smartrecruiters.com/v1/companies/Ubisoft2/postings"
    respx.get(url__regex=rf"{base}\?.*").mock(
        return_value=httpx.Response(200, json=_SR_LIST)
    )
    respx.get(f"{base}/744000145800584").mock(
        return_value=httpx.Response(200, json=_SR_DETAIL)
    )
    with httpx.Client() as client:
        jobs = SmartRecruitersSource("Ubisoft2").fetch(client)

    fj = jobs[0]
    assert fj.job.title == "Senior Community Developer"
    assert fj.job.company == "Ubisoft"
    assert fj.job.location == "Montreal, QC, ca"
    assert fj.job.url == _SR_DETAIL["postingUrl"]
    assert "Lead community strategy." in fj.job.description
    assert "5 years experience" in fj.job.description
    assert fj.employment_type == "Full-time"
    assert fj.remote is False
    assert fj.date_posted is not None


@respx.mock
def test_smartrecruiters_survives_a_dead_detail_call():
    """One posting whose detail 500s must not sink the whole board -- the job
    still lands, just without a description."""
    base = "https://api.smartrecruiters.com/v1/companies/Ubisoft2/postings"
    respx.get(url__regex=rf"{base}\?.*").mock(
        return_value=httpx.Response(200, json=_SR_LIST)
    )
    respx.get(f"{base}/744000145800584").mock(return_value=httpx.Response(500))
    with httpx.Client() as client:
        jobs = SmartRecruitersSource("Ubisoft2").fetch(client)

    assert len(jobs) == 1
    assert jobs[0].job.description == ""
    # Falls back to the derivable public URL rather than dropping it.
    assert jobs[0].job.url.endswith("/Ubisoft2/744000145800584")


@respx.mock
def test_smartrecruiters_wrong_slug_returns_200_and_no_jobs():
    """A bad slug is HTTP 200 with totalFound 0, not a 404 -- so an empty
    result is all a caller gets to distinguish "no such company" from
    "no open roles"."""
    base = "https://api.smartrecruiters.com/v1/companies/Nope/postings"
    respx.get(url__regex=rf"{base}\?.*").mock(
        return_value=httpx.Response(
            200, json={"offset": 0, "limit": 25, "totalFound": 0, "content": []}
        )
    )
    with httpx.Client() as client:
        assert SmartRecruitersSource("Nope").fetch(client) == []


@respx.mock
def test_recruitee_maps_offer_with_inline_description():
    respx.get("https://vandebron.recruitee.com/api/offers/").mock(
        return_value=httpx.Response(
            200,
            json={
                "offers": [
                    {
                        "id": 2710502,
                        "title": "Sourcing & Pricing Analyst",
                        "company_name": "Vandebron",
                        "location": "Amsterdam, Noord-Holland, Nederland",
                        "careers_url": "https://werkenbij.vandebron.nl/o/sourcing",
                        "description": "<h3>Who we are</h3><p>Energy.</p>",
                        "salary": {
                            "min": 4000,
                            "max": 5500,
                            "currency": "EUR",
                            "period": "month",
                        },
                        "employment_type_code": "fulltime_permanent",
                        "published_at": "2026-08-14 08:23:10 UTC",
                        "remote": False,
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        jobs = RecruiteeSource("vandebron").fetch(client)

    fj = jobs[0]
    assert fj.job.title == "Sourcing & Pricing Analyst"
    assert fj.job.company == "Vandebron"
    assert fj.job.url == "https://werkenbij.vandebron.nl/o/sourcing"
    assert "Energy." in fj.job.description and "<h3>" not in fj.job.description
    assert (fj.salary_min, fj.salary_max, fj.salary_currency) == (4000, 5500, "EUR")
    assert fj.employment_type == "fulltime_permanent"
    assert fj.date_posted is not None


@respx.mock
def test_recruitee_bad_slug_raises_http_error():
    """A wrong slug is a JSON 404 from the wildcard host -- not the DNS
    failure RESEARCH.md used to claim."""
    respx.get("https://nosuchco.recruitee.com/api/offers/").mock(
        return_value=httpx.Response(404, json={"error": "Not Found"})
    )
    with httpx.Client() as client:
        with pytest.raises(httpx.HTTPStatusError):
            RecruiteeSource("nosuchco").fetch(client)


@respx.mock
def test_workable_requests_details_and_maps_location():
    route = respx.get(
        url__regex=r"https://apply\.workable\.com/api/v1/widget/accounts/enfos-inc.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "ENFOS, Inc.",
                "description": None,
                "jobs": [
                    {
                        "title": "Senior Software Engineer",
                        "shortcode": "77DF64C44E",
                        "employment_type": "Full-time",
                        "telecommuting": True,
                        "url": "https://apply.workable.com/j/77DF64C44E",
                        "shortlink": "https://apply.workable.com/j/77DF64C44E",
                        "published_on": "2026-04-25",
                        "country": "United States",
                        "city": "Chicago",
                        "state": "Illinois",
                        "description": "<p>Scale the backend.</p>",
                    }
                ],
            },
        )
    )
    with httpx.Client() as client:
        jobs = WorkableSource("enfos-inc").fetch(client)

    # details=true is what folds the description into this single call.
    assert "details=true" in str(route.calls.last.request.url)
    fj = jobs[0]
    assert fj.job.title == "Senior Software Engineer"
    assert fj.job.company == "ENFOS, Inc."
    assert fj.job.location == "Chicago, Illinois, United States"
    assert fj.source_id == "77DF64C44E"
    assert fj.remote is True
    assert "Scale the backend." in fj.job.description


@respx.mock
def test_workable_dormant_account_is_empty_not_an_error():
    """A dormant board still resolves (200 + correct name) with jobs: [] --
    an empty result is not evidence of a bad slug."""
    respx.get(
        url__regex=r"https://apply\.workable\.com/api/v1/widget/accounts/typeform.*"
    ).mock(return_value=httpx.Response(200, json={"name": "Typeform", "jobs": []}))
    with httpx.Client() as client:
        assert WorkableSource("typeform").fetch(client) == []


# --------------------------------------------------------------------------- #
# Garbage input + service-level error isolation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "source, url_regex, payload",
    [
        (
            ArbeitnowSource(),
            r"https://www\.arbeitnow\.com/api/job-board-api.*",
            {"unexpected": "shape"},
        ),
        (JobicySource(), r"https://jobicy\.com/api/v2/remote-jobs.*", {}),
        (HimalayasSource(), r"https://himalayas\.app/jobs/api.*", {"jobs": None}),
        (
            WorkableSource("x"),
            r"https://apply\.workable\.com/api/v1/widget/accounts/x.*",
            {},
        ),
        (
            RecruiteeSource("x"),
            r"https://x\.recruitee\.com/api/offers/",
            {"offers": []},
        ),
    ],
)
@respx.mock
def test_missing_or_garbage_payload_yields_no_jobs(source, url_regex, payload):
    respx.get(url__regex=url_regex).mock(return_value=httpx.Response(200, json=payload))
    with httpx.Client() as client:
        assert source.fetch(client) == []


@respx.mock
def test_remoteok_empty_and_notice_only_payloads_yield_no_jobs():
    respx.get("https://remoteok.com/api").mock(
        return_value=httpx.Response(200, json=[{"legal": "notice", "last_updated": 1}])
    )
    with httpx.Client() as client:
        assert RemoteOKSource().fetch(client) == []


# --------------------------------------------------------------------------- #
# Timestamps: naive-UTC convention (core/normalize.py)
# --------------------------------------------------------------------------- #


@respx.mock
def test_offset_bearing_board_date_is_converted_to_utc_not_just_stripped(session):
    """``dateutil`` returns an AWARE datetime when the source string carries an
    offset, but ``date_posted`` is a naive column (SQLite DATETIME / Postgres
    timestamp-without-time-zone). Merely dropping the tzinfo would store
    midnight IST as though it were midnight UTC -- 5.5 hours early -- which
    skews date sorting, the ghost-job age heuristic, and digest freshness.
    The value must be *converted* to UTC first."""
    respx.get(url__regex=r"https://jobicy\.com/api/v2/remote-jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 5,
                        "jobTitle": "Offset Job",
                        "companyName": "TZ Co",
                        "jobGeo": "India",
                        "jobDescription": "<p>Work.</p>",
                        "url": "https://jobicy.example/5",
                        "pubDate": "2026-08-01T00:00:00+05:30",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        IngestionService(session).ingest(JobicySource(), client=client)
    session.commit()

    stored = JobRepository(session).list()[0].date_posted
    assert stored == datetime(2026, 7, 31, 18, 30, 0)
    assert stored != datetime(2026, 8, 1, 0, 0, 0), "tzinfo stripped, not converted"
    assert stored.tzinfo is None, "the column holds naive UTC"


@respx.mock
def test_epoch_board_date_is_utc_not_machine_local_time(session):
    """``datetime.fromtimestamp(v)`` without a tz returns naive *local* time.
    Under the naive-UTC convention that is taken at face value, so on this
    UTC+05:30 machine every Arbeitnow/Himalayas posting landed 5.5 hours in
    the future. 1787766024 is 2026-08-26T17:40:24Z."""
    respx.get(url__regex=r"https://www\.arbeitnow\.com/api/job-board-api.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "slug": "epoch-job",
                        "company_name": "Epoch Co",
                        "title": "Epoch Job",
                        "description": "d",
                        "url": "https://www.arbeitnow.com/jobs/epoch",
                        "location": "Berlin",
                        "created_at": 1787766024,
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        IngestionService(session).ingest(ArbeitnowSource(), client=client)
    session.commit()

    stored = JobRepository(session).list()[0].date_posted
    assert stored == datetime(2026, 8, 26, 17, 40, 24)
    assert stored.tzinfo is None


@respx.mock
def test_ingestion_service_persists_a_board_and_isolates_its_failure(session):
    """The service must swallow a new source's transport failure the same way
    it does for the original adapters -- one dead board cannot abort a run."""
    respx.get(url__regex=r"https://jobicy\.com/api/v2/remote-jobs.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "jobTitle": "Remote Python Dev",
                        "companyName": "Acme",
                        "jobGeo": "Anywhere",
                        "jobDescription": "<p>Code.</p>",
                        "url": "https://jobicy.example/1",
                        "pubDate": "2026-08-26T12:42:49+00:00",
                    }
                ]
            },
        )
    )
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(503))

    service = IngestionService(session)
    with httpx.Client() as client:
        good = service.ingest(JobicySource(), client=client)
        bad = service.ingest(RemoteOKSource(), client=client)
    session.commit()

    assert good.fetched == 1 and good.upserted == 1
    assert not good.errors
    assert bad.fetched == 0
    assert bad.errors  # captured, not raised
    assert JobRepository(session).count() == 1

    row = JobRepository(session).list()[0]
    assert row.title == "Remote Python Dev"
    assert row.remote is True
