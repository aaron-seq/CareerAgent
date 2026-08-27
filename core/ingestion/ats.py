"""
Public ATS adapters: Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee,
Workable.

These endpoints are unauthenticated JSON feeds published by the ATS on behalf
of a company. Each adapter takes the company's board token/slug and returns
normalized jobs. Descriptions arrive as HTML and are reduced to plain text.
"""

from __future__ import annotations

from typing import Optional

import httpx
from bs4 import BeautifulSoup

from ..models import JobPosting
from .base import FetchedJob, JobSource
from .base import parse_date as _parse_iso


def html_to_text(html: Optional[str]) -> str:
    """Strip HTML down to plain text.

    Greenhouse's `content` field is double-encoded: the JSON value is itself
    HTML-escaped HTML (literal "&lt;div&gt;" instead of "<div>"). A single
    BeautifulSoup pass only unwraps that outer escaping -- there's no real
    tag structure yet, so get_text() returns the now-revealed-but-still-
    tagged markup as plain text (confirmed against a live Greenhouse job:
    "<div>...</div>" showed up verbatim in the stored description). Looping
    until a pass stops changing the string handles both single- and double-
    encoded input; ordinary single-encoded HTML (Lever/Ashby) converges after
    one pass, so this is a no-op cost for them. Bounded to avoid pathological
    input looping indefinitely.
    """
    if not html:
        return ""
    text = html
    for _ in range(3):
        stripped = BeautifulSoup(text, "html.parser").get_text(
            separator="\n", strip=True
        )
        if stripped == text:
            break
        text = stripped
    return text


class GreenhouseSource(JobSource):
    """boards-api.greenhouse.io — one call returns the whole board."""

    source = "greenhouse"

    def __init__(self, board_token: str, company_name: str | None = None):
        self.board_token = board_token
        self.company_name = company_name or board_token

    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        url = (
            f"https://boards-api.greenhouse.io/v1/boards/"
            f"{self.board_token}/jobs?content=true"
        )
        data = self._get_json(client, url)
        jobs: list[FetchedJob] = []
        for item in data.get("jobs", []):
            loc = (item.get("location") or {}).get("name")
            job = JobPosting(
                title=item.get("title", ""),
                company=self.company_name,
                location=loc,
                url=item.get("absolute_url"),
                description=html_to_text(item.get("content")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=bool(loc and "remote" in loc.lower()),
                )
            )
        return jobs


class LeverSource(JobSource):
    """api.lever.co/v0/postings/{company} — clean descriptionPlain + workplaceType."""

    source = "lever"

    def __init__(self, company_slug: str, company_name: str | None = None):
        self.company_slug = company_slug
        self.company_name = company_name or company_slug

    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        url = f"https://api.lever.co/v0/postings/{self.company_slug}?mode=json"
        data = self._get_json(client, url)
        jobs: list[FetchedJob] = []
        for item in data:
            categories = item.get("categories") or {}
            workplace = (item.get("workplaceType") or "").lower()
            location = categories.get("location")
            job = JobPosting(
                title=item.get("text", ""),
                company=self.company_name,
                location=location,
                url=item.get("hostedUrl"),
                description=item.get("descriptionPlain")
                or html_to_text(item.get("description")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=workplace == "remote"
                    or bool(location and "remote" in location.lower()),
                    employment_type=categories.get("commitment"),
                )
            )
        return jobs


class AshbySource(JobSource):
    """api.ashbyhq.com posting feed — best compensation support."""

    source = "ashby"

    def __init__(self, board_name: str, company_name: str | None = None):
        self.board_name = board_name
        self.company_name = company_name or board_name

    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        url = (
            f"https://api.ashbyhq.com/posting-api/job-board/"
            f"{self.board_name}?includeCompensation=true"
        )
        data = self._get_json(client, url)
        jobs: list[FetchedJob] = []
        for item in data.get("jobs", []):
            comp = item.get("compensation") or {}
            summary = comp.get("compensationTierSummary")
            job = JobPosting(
                title=item.get("title", ""),
                company=self.company_name,
                location=item.get("location"),
                url=item.get("jobUrl"),
                description=item.get("descriptionPlain")
                or html_to_text(item.get("descriptionHtml")),
                salary_range=summary,
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=bool(item.get("isRemote")),
                    employment_type=item.get("employmentType"),
                )
            )
        return jobs


class SmartRecruitersSource(JobSource):
    """api.smartrecruiters.com public postings feed.

    Two quirks, both confirmed live (2026-08-27):

    * A wrong slug returns **HTTP 200 with totalFound: 0**, not a 404, so a
      caller can't tell "no such company" from "no open roles" by status code.
    * The list response carries no description -- that lives on the per-posting
      detail endpoint. So this costs 1 + N requests, and ``limit`` is kept
      small by default to bound the fan-out against a public, unkeyed API.
    """

    source = "smartrecruiters"

    def __init__(self, company_slug: str, company_name: str | None = None):
        self.company_slug = company_slug
        self.company_name = company_name or company_slug

    def fetch(
        self, client: httpx.Client, limit: int = 25, **params
    ) -> list[FetchedJob]:
        base = (
            f"https://api.smartrecruiters.com/v1/companies/{self.company_slug}/postings"
        )
        data = self._get_json(client, base, params={"limit": limit})
        jobs: list[FetchedJob] = []
        for item in data.get("content") or []:
            loc = item.get("location") or {}
            city = ", ".join(
                p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p
            )
            posting_id = str(item.get("id"))
            description, url = (
                "",
                f"https://jobs.smartrecruiters.com/{self.company_slug}/{posting_id}",
            )
            try:
                detail = self._get_json(client, f"{base}/{posting_id}")
            except httpx.HTTPError:
                detail = {}  # one dead posting must not sink the whole board
            if detail:
                url = detail.get("postingUrl") or url
                sections = ((detail.get("jobAd") or {}).get("sections")) or {}
                description = html_to_text(
                    "".join(
                        (sections.get(name) or {}).get("text") or ""
                        for name in ("jobDescription", "qualifications")
                    )
                )
            job = JobPosting(
                title=item.get("name", ""),
                company=(item.get("company") or {}).get("name") or self.company_name,
                location=city or None,
                url=url,
                description=description,
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=posting_id,
                    remote=bool(loc.get("remote")),
                    employment_type=(item.get("typeOfEmployment") or {}).get("label"),
                    date_posted=_parse_iso(item.get("releasedDate")),
                )
            )
        return jobs


class RecruiteeSource(JobSource):
    """{slug}.recruitee.com/api/offers/ - full descriptions in one call.

    A wrong slug returns a JSON 404 (``{"error": "Not Found"}``), which
    ``raise_for_status`` surfaces as an HTTPStatusError. (RESEARCH.md
    previously claimed a wrong slug produced a DNS error; it does not --
    ``*.recruitee.com`` is a wildcard host.)
    """

    source = "recruitee"

    def __init__(self, company_slug: str, company_name: str | None = None):
        self.company_slug = company_slug
        self.company_name = company_name or company_slug

    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        url = f"https://{self.company_slug}.recruitee.com/api/offers/"
        data = self._get_json(client, url)
        jobs: list[FetchedJob] = []
        for item in data.get("offers") or []:
            salary = item.get("salary") or {}
            job = JobPosting(
                title=item.get("title", ""),
                company=item.get("company_name") or self.company_name,
                location=item.get("location"),
                url=item.get("careers_url"),
                description=html_to_text(item.get("description")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=bool(item.get("remote")),
                    salary_min=salary.get("min"),
                    salary_max=salary.get("max"),
                    salary_currency=salary.get("currency"),
                    employment_type=item.get("employment_type_code"),
                    date_posted=_parse_iso(item.get("published_at")),
                )
            )
        return jobs


class WorkableSource(JobSource):
    """apply.workable.com public widget feed.

    ``?details=true`` folds the description into the same call, so this stays
    a single request. Note a dormant account still resolves (HTTP 200, correct
    ``name``) but returns ``jobs: []`` -- an empty result is not proof of a bad
    slug.
    """

    source = "workable"

    def __init__(self, company_slug: str, company_name: str | None = None):
        self.company_slug = company_slug
        self.company_name = company_name or company_slug

    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{self.company_slug}"
        data = self._get_json(client, url, params={"details": "true"})
        company = data.get("name") or self.company_name
        jobs: list[FetchedJob] = []
        for item in data.get("jobs") or []:
            location = ", ".join(
                p
                for p in (item.get("city"), item.get("state"), item.get("country"))
                if p
            )
            job = JobPosting(
                title=item.get("title", ""),
                company=company,
                location=location or None,
                url=item.get("url") or item.get("shortlink"),
                description=html_to_text(item.get("description")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=item.get("shortcode"),
                    remote=bool(item.get("telecommuting")),
                    employment_type=item.get("employment_type") or None,
                    date_posted=_parse_iso(item.get("published_on")),
                )
            )
        return jobs
