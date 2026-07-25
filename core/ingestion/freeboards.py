"""
Keyless, free job-board adapters.

Every source here needs **no API key and no account**:

===============  ==========================================  ==================
Source           Endpoint                                    Notes
===============  ==========================================  ==================
Arbeitnow        ``www.arbeitnow.com/api/job-board-api``     EU + remote; has a
                                                             ``visa_sponsorship``
                                                             flag
Himalayas        ``himalayas.app/jobs/api``                  Remote-only; hard
                                                             cap of 20/request
Jobicy           ``jobicy.com/api/v2/remote-jobs``           Remote-only; salary
                                                             fields
RemoteOK         ``remoteok.com/api``                        **Attribution
                                                             legally required**
===============  ==========================================  ==================

.. warning::
   The response shapes below are taken from each provider's **documentation**,
   not from a live call (the build environment has no outbound access). Run
   ``python -m scripts.verify_sources`` on a connected machine to confirm each
   source is reachable and that these parsers handle its real payload. Parsing
   is written defensively so an unexpected field degrades to ``None`` rather
   than raising.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..models import JobPosting
from .aggregators import _parse_date
from .ats import html_to_text
from .base import FetchedJob, JobSource


def _from_epoch(value: Any) -> Optional[datetime]:
    """Several of these boards publish Unix timestamps rather than ISO dates."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _any_date(value: Any) -> Optional[datetime]:
    """Accept either an epoch int or an ISO-ish string."""
    if isinstance(value, (int, float)):
        return _from_epoch(value)
    return _parse_date(value) if value else None


def _num(value: Any) -> Optional[float]:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num or None  # treat 0 as "not stated"


def _joined(value: Any) -> list[str]:
    """Normalize a field that may be a list, a comma string, or absent."""
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


class ArbeitnowSource(JobSource):
    """Arbeitnow — free EU/remote board, no key, 100 results per page."""

    source = "arbeitnow"

    def fetch(
        self,
        client: httpx.Client,
        page: int = 1,
        visa_sponsorship: bool | None = None,
        **params,
    ) -> list[FetchedJob]:
        query: dict[str, Any] = {"page": page}
        if visa_sponsorship is not None:
            query["visa_sponsorship"] = str(visa_sponsorship).lower()
        data = self._get_json(
            client, "https://www.arbeitnow.com/api/job-board-api", params=query
        )
        jobs: list[FetchedJob] = []
        for item in (data or {}).get("data", []):
            remote = bool(item.get("remote"))
            job = JobPosting(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("location") or ("Remote" if remote else None),
                url=item.get("url"),
                description=html_to_text(item.get("description")),
                tech_stack=_joined(item.get("tags")),
            )
            types = _joined(item.get("job_types"))
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("slug") or item.get("url") or ""),
                    remote=remote,
                    employment_type=types[0] if types else None,
                    date_posted=_any_date(item.get("created_at")),
                )
            )
        return jobs


class HimalayasSource(JobSource):
    """Himalayas — remote-only. The provider caps ``limit`` at 20 per request."""

    source = "himalayas"
    MAX_LIMIT = 20

    def fetch(
        self, client: httpx.Client, limit: int = 20, offset: int = 0, **params
    ) -> list[FetchedJob]:
        query = {"limit": min(limit, self.MAX_LIMIT), "offset": offset}
        data = self._get_json(client, "https://himalayas.app/jobs/api", params=query)
        jobs: list[FetchedJob] = []
        for item in (data or {}).get("jobs", []):
            locations = _joined(item.get("locationRestrictions"))
            job = JobPosting(
                title=item.get("title", ""),
                company=item.get("companyName", ""),
                location=", ".join(locations) if locations else "Remote",
                url=item.get("applicationLink") or item.get("guid"),
                description=html_to_text(
                    item.get("description") or item.get("excerpt")
                ),
                tech_stack=_joined(item.get("categories")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("guid") or item.get("title", "")),
                    remote=True,  # the board is remote-only by definition
                    salary_min=_num(item.get("minSalary")),
                    salary_max=_num(item.get("maxSalary")),
                    salary_currency=item.get("currency"),
                    employment_type=item.get("type"),
                    date_posted=_any_date(item.get("pubDate")),
                )
            )
        return jobs


class JobicySource(JobSource):
    """Jobicy — remote-only board with annual salary fields, no key."""

    source = "jobicy"

    def fetch(
        self,
        client: httpx.Client,
        count: int = 50,
        geo: str = "",
        industry: str = "",
        **params,
    ) -> list[FetchedJob]:
        query: dict[str, Any] = {"count": count}
        if geo:
            query["geo"] = geo
        if industry:
            query["industry"] = industry
        data = self._get_json(
            client, "https://jobicy.com/api/v2/remote-jobs", params=query
        )
        jobs: list[FetchedJob] = []
        for item in (data or {}).get("jobs", []):
            job = JobPosting(
                title=item.get("jobTitle", ""),
                company=item.get("companyName", ""),
                location=item.get("jobGeo") or "Remote",
                url=item.get("url"),
                description=html_to_text(
                    item.get("jobDescription") or item.get("jobExcerpt")
                ),
                tech_stack=_joined(item.get("jobIndustry")),
            )
            types = _joined(item.get("jobType"))
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id") or item.get("jobSlug") or ""),
                    remote=True,
                    salary_min=_num(item.get("annualSalaryMin")),
                    salary_max=_num(item.get("annualSalaryMax")),
                    salary_currency=item.get("salaryCurrency"),
                    employment_type=types[0] if types else None,
                    date_posted=_any_date(item.get("pubDate")),
                )
            )
        return jobs


class RemoteOKSource(JobSource):
    """RemoteOK — keyless, ~100 most recent jobs.

    Attribution is a licence condition: when displaying these results you must
    link directly to the original posting (no redirects). The first element of
    the response is a legal/attribution notice rather than a job, and is
    skipped here -- but the obligation still applies to whatever you render.
    """

    source = "remoteok"
    ATTRIBUTION = "Jobs by RemoteOK - link directly to the original posting."

    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        data = self._get_json(client, "https://remoteok.com/api")
        if not isinstance(data, list):
            return []
        jobs: list[FetchedJob] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # The legal notice element carries no position/company.
            if item.get("legal") is not None and not item.get("position"):
                continue
            if not item.get("position"):
                continue
            job = JobPosting(
                title=item.get("position", ""),
                company=item.get("company", ""),
                location=item.get("location") or "Remote",
                url=item.get("url") or item.get("apply_url"),
                description=html_to_text(item.get("description")),
                tech_stack=_joined(item.get("tags")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id") or item.get("slug") or ""),
                    remote=True,
                    salary_min=_num(item.get("salary_min")),
                    salary_max=_num(item.get("salary_max")),
                    date_posted=_any_date(item.get("date") or item.get("epoch")),
                )
            )
        return jobs
