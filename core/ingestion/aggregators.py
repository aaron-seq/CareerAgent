"""
Aggregator adapters: Adzuna, The Muse, Remotive.

Adzuna and The Muse take API keys (free tiers); Remotive is keyless but
requires attribution and light rate limits. Quotas change — re-verify against
the live docs at build time (see docs/RESEARCH.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx
from dateutil import parser as date_parser

from ..models import JobPosting
from .ats import html_to_text
from .base import FetchedJob, JobSource


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return date_parser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None


class AdzunaSource(JobSource):
    """api.adzuna.com — keyed aggregator with salary data."""

    source = "adzuna"

    def __init__(self, app_id: str, app_key: str, country: str = "gb"):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country

    def fetch(
        self,
        client: httpx.Client,
        what: str = "",
        where: str = "",
        page: int = 1,
        **params,
    ) -> list[FetchedJob]:
        url = f"https://api.adzuna.com/v1/api/jobs/{self.country}/search/{page}"
        query = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": what,
            "where": where,
            "results_per_page": params.get("results_per_page", 50),
        }
        data = self._get_json(client, url, params=query)
        jobs: list[FetchedJob] = []
        for item in data.get("results", []):
            company = (item.get("company") or {}).get("display_name", "")
            location = (item.get("location") or {}).get("display_name")
            job = JobPosting(
                title=item.get("title", ""),
                company=company,
                location=location,
                url=item.get("redirect_url"),
                description=item.get("description", ""),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=bool(location and "remote" in location.lower()),
                    salary_min=item.get("salary_min"),
                    salary_max=item.get("salary_max"),
                    salary_currency="GBP" if self.country == "gb" else None,
                    employment_type=item.get("contract_time"),
                    date_posted=_parse_date(item.get("created")),
                )
            )
        return jobs


class TheMuseSource(JobSource):
    """themuse.com public API — optional key raises the rate limit."""

    source = "themuse"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def fetch(
        self, client: httpx.Client, category: str = "", page: int = 0, **params
    ) -> list[FetchedJob]:
        url = "https://www.themuse.com/api/public/v2/jobs"
        query = {"page": page}
        if category:
            query["category"] = category
        if self.api_key:
            query["api_key"] = self.api_key
        data = self._get_json(client, url, params=query)
        jobs: list[FetchedJob] = []
        for item in data.get("results", []):
            company = (item.get("company") or {}).get("name", "")
            locations = item.get("locations") or []
            location = locations[0].get("name") if locations else None
            job = JobPosting(
                title=item.get("name", ""),
                company=company,
                location=location,
                url=(item.get("refs") or {}).get("landing_page"),
                description=html_to_text(item.get("contents")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=bool(location and "remote" in location.lower()),
                    employment_type=item.get("type"),
                    date_posted=_parse_date(item.get("publication_date")),
                )
            )
        return jobs


class RemotiveSource(JobSource):
    """remotive.com/api/remote-jobs — keyless, remote-only, attribution required."""

    source = "remotive"

    def fetch(
        self, client: httpx.Client, category: str = "", search: str = "", **params
    ) -> list[FetchedJob]:
        url = "https://remotive.com/api/remote-jobs"
        query = {}
        if category:
            query["category"] = category
        if search:
            query["search"] = search
        data = self._get_json(client, url, params=query)
        jobs: list[FetchedJob] = []
        for item in data.get("jobs", []):
            job = JobPosting(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Remote"),
                url=item.get("url"),
                description=html_to_text(item.get("description")),
                salary_range=item.get("salary") or None,
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=True,
                    employment_type=item.get("job_type"),
                    date_posted=_parse_date(item.get("publication_date")),
                )
            )
        return jobs
