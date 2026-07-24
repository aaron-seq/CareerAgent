"""Phase 3 -- ATS detection, JSON-LD extraction, polite fetcher."""

from __future__ import annotations

import httpx
import pytest
import respx

from core.fetching import (
    PoliteFetcher,
    RobotsDisallowed,
    detect,
    detect_from_url,
    extract_jsonld_jobs,
)

# --------------------------------------------------------------------------- #
# ATS detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,expected_type,expected_slug",
    [
        ("https://boards.greenhouse.io/stripe", "greenhouse", "stripe"),
        ("https://jobs.lever.co/netflix", "lever", "netflix"),
        ("https://jobs.ashbyhq.com/ramp", "ashby", "ramp"),
        ("https://careers.smartrecruiters.com/Company", "smartrecruiters", "Company"),
    ],
)
def test_detect_from_url(url, expected_type, expected_slug):
    match = detect_from_url(url)
    assert match is not None
    assert match.ats_type == expected_type
    assert match.slug == expected_slug


def test_detect_workday_captures_tenant_and_site():
    match = detect_from_url("https://acme.wd5.myworkdayjobs.com/External")
    assert match is not None
    assert match.ats_type == "workday"
    assert match.slug == "acme"
    assert match.extra == {"datacenter": "wd5", "site": "External"}


def test_detect_from_html_and_none():
    html = '<a href="https://boards.greenhouse.io/airbnb/jobs/1">Careers</a>'
    match = detect(html=html)
    assert match is not None and match.slug == "airbnb"
    assert detect(url="https://example.com/careers") is None


# --------------------------------------------------------------------------- #
# JSON-LD extraction
# --------------------------------------------------------------------------- #

JSONLD_OBJECT = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Senior Engineer",
  "description": "<p>Build <b>things</b>.</p>",
  "datePosted": "2026-05-01",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {"@type": "Organization", "name": "Acme Corp"},
  "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress",
      "addressLocality": "Berlin", "addressCountry": "DE"}},
  "baseSalary": {"@type": "MonetaryAmount", "currency": "EUR",
      "value": {"@type": "QuantitativeValue", "minValue": 70000, "maxValue": 90000}},
  "url": "https://acme.example/jobs/senior"
}
</script></head><body></body></html>
"""


def test_extract_jsonld_object():
    jobs = extract_jsonld_jobs(JSONLD_OBJECT)
    assert len(jobs) == 1
    fj = jobs[0]
    assert fj.job.title == "Senior Engineer"
    assert fj.job.company == "Acme Corp"
    assert "things" in fj.job.description and "<b>" not in fj.job.description
    assert "Berlin" in fj.job.location
    assert fj.salary_min == 70000 and fj.salary_max == 90000
    assert fj.salary_currency == "EUR"
    assert fj.employment_type == "FULL_TIME"
    assert fj.date_posted is not None and fj.date_posted.year == 2026


def test_extract_jsonld_graph_and_telecommute():
    html = """
    <script type="application/ld+json">
    {"@graph": [
      {"@type": "WebSite", "name": "ignore me"},
      {"@type": "JobPosting", "title": "Remote Dev",
       "hiringOrganization": {"name": "RemoteCo"},
       "jobLocationType": "TELECOMMUTE"}
    ]}
    </script>
    """
    jobs = extract_jsonld_jobs(html)
    assert len(jobs) == 1
    assert jobs[0].job.title == "Remote Dev"
    assert jobs[0].remote is True
    assert jobs[0].job.location == "Remote"


def test_extract_jsonld_ignores_malformed_and_nonjob():
    html = """
    <script type="application/ld+json">{ not valid json </script>
    <script type="application/ld+json">{"@type": "Organization", "name": "X"}</script>
    """
    assert extract_jsonld_jobs(html) == []


# --------------------------------------------------------------------------- #
# Polite fetcher
# --------------------------------------------------------------------------- #


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


@respx.mock
def test_polite_fetcher_respects_robots():
    respx.get("https://blocked.example/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private")
    )
    with httpx.Client() as client:
        fetcher = PoliteFetcher(client=client, sleep=lambda *_: None)
        assert fetcher.can_fetch("https://blocked.example/private/x") is False
        assert fetcher.can_fetch("https://blocked.example/public/x") is True
        with pytest.raises(RobotsDisallowed):
            fetcher.get("https://blocked.example/private/x")


@respx.mock
def test_polite_fetcher_rate_limits_between_requests():
    respx.get("https://site.example/robots.txt").mock(return_value=httpx.Response(404))
    page = respx.get(url__regex=r"https://site\.example/page.*").mock(
        return_value=httpx.Response(200, text="ok")
    )
    sleeps: list[float] = []
    clock = FakeClock()
    with httpx.Client() as client:
        fetcher = PoliteFetcher(
            client=client,
            min_interval=2.0,
            sleep=lambda s: sleeps.append(s),
            now=clock,
            jitter=lambda: 0.0,
        )
        fetcher.get("https://site.example/page1", use_cache=False)
        fetcher.get("https://site.example/page2", use_cache=False)  # immediate
    assert page.call_count == 2
    # Second call had to wait ~min_interval since no time elapsed on the clock.
    assert any(s >= 2.0 for s in sleeps)


@respx.mock
def test_polite_fetcher_caches():
    respx.get("https://cache.example/robots.txt").mock(return_value=httpx.Response(404))
    route = respx.get("https://cache.example/p").mock(
        return_value=httpx.Response(200, text="cached")
    )
    with httpx.Client() as client:
        fetcher = PoliteFetcher(client=client, sleep=lambda *_: None)
        r1 = fetcher.get("https://cache.example/p")
        r2 = fetcher.get("https://cache.example/p")
    assert r1.text == r2.text == "cached"
    assert route.call_count == 1  # second served from cache


@respx.mock
def test_polite_fetcher_retries_on_5xx():
    respx.get("https://flaky.example/robots.txt").mock(return_value=httpx.Response(404))
    route = respx.get("https://flaky.example/p").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, text="recovered"),
        ]
    )
    with httpx.Client() as client:
        fetcher = PoliteFetcher(
            client=client, sleep=lambda *_: None, jitter=lambda: 0.0
        )
        resp = fetcher.get("https://flaky.example/p", use_cache=False)
    assert resp.text == "recovered"
    assert route.call_count == 2
