"""
Public ATS adapters: Greenhouse, Lever, Ashby.

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


def html_to_text(html: Optional[str]) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


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
