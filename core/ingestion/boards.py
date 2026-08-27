"""
Keyless remote-job board adapters: Arbeitnow, Jobicy, RemoteOK, Himalayas.

All four are public JSON feeds needing no credentials. Field names here were
read off live responses on 2026-08-27 (see docs/RESEARCH.md) rather than from
docs, which are thin or stale for most of them.

Attribution: RemoteOK's terms make a direct, followed link back legally
required, and Jobicy/Arbeitnow both ask for credit in the response body
itself. :data:`ATTRIBUTION` carries the notice the UI renders per source.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from ..models import JobPosting
from .ats import html_to_text
from .base import FetchedJob, JobSource
from .base import parse_date as _parse_date

#: Source -> notice the UI must display. Remotive/RemoteOK are contractual.
ATTRIBUTION = {
    "remotive": (
        "Remotive requires attribution: link back to the original posting "
        "when sharing results."
    ),
    "remoteok": (
        "RemoteOK requires attribution: link directly back to the posting on "
        "RemoteOK (a followed link, no redirects) and name RemoteOK as the "
        "source. API access can be suspended otherwise."
    ),
    "jobicy": "Jobicy asks that it be credited with a direct link to the posting.",
    "arbeitnow": "Arbeitnow asks for a link back to the job on arbeitnow.com.",
    "himalayas": "Himalayas jobs link back to himalayas.app.",
}


def _from_epoch(value) -> Optional[datetime]:
    """Several boards publish dates as integer unix seconds, not strings.

    Returns an *aware* UTC datetime, deliberately. Bare
    ``datetime.fromtimestamp(v)`` returns naive **local** time, which the
    naive-UTC storage convention would then take at face value -- on a
    UTC+05:30 machine every Arbeitnow and Himalayas posting landed 5.5 hours
    in the future. Handing back an aware value lets ``to_naive_utc`` at the
    persistence boundary do the one real conversion.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _positive(value) -> Optional[float]:
    """Boards use 0 (not null) to mean "no salary given"."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _first(value) -> Optional[str]:
    """First entry of a field that is *usually* a list but sometimes isn't.

    Arbeitnow's ``job_types`` is a PHP array serialized to JSON, so a sparse
    one loses its list-ness and arrives as an object keyed by the surviving
    index -- ``{"1": "manager"}`` instead of ``["manager"]``. Indexing that
    with ``[0]`` raises KeyError; live run 2026-08-27 hit it on 3 of 175
    postings, which is exactly the sort of thing a hand-written mock never
    reproduces.
    """
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else None
    return str(value) if value else None


class ArbeitnowSource(JobSource):
    """arbeitnow.com/api/job-board-api - keyless, EU-heavy, hourly refresh."""

    source = "arbeitnow"

    def fetch(self, client: httpx.Client, page: int = 1, **params) -> list[FetchedJob]:
        url = "https://www.arbeitnow.com/api/job-board-api"
        data = self._get_json(client, url, params={"page": page})
        jobs: list[FetchedJob] = []
        for item in data.get("data") or []:
            job = JobPosting(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("location"),
                url=item.get("url"),
                description=html_to_text(item.get("description")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=item.get("slug"),
                    remote=bool(item.get("remote")),
                    employment_type=_first(item.get("job_types")),
                    date_posted=_from_epoch(item.get("created_at")),
                )
            )
        return jobs


class JobicySource(JobSource):
    """jobicy.com/api/v2/remote-jobs - keyless, remote-only, salary data."""

    source = "jobicy"

    def fetch(
        self,
        client: httpx.Client,
        tag: str = "",
        industry: str = "",
        geo: str = "",
        count: int = 50,
        **params,
    ) -> list[FetchedJob]:
        url = "https://jobicy.com/api/v2/remote-jobs"
        query: dict[str, object] = {"count": count}
        if tag:
            query["tag"] = tag  # free-text keyword; more precise than industry
        if industry:
            query["industry"] = industry
        if geo:
            query["geo"] = geo
        data = self._get_json(client, url, params=query)
        jobs: list[FetchedJob] = []
        for item in data.get("jobs") or []:
            job = JobPosting(
                title=item.get("jobTitle", ""),
                company=item.get("companyName", ""),
                location=item.get("jobGeo") or "Remote",
                url=item.get("url"),
                description=html_to_text(
                    item.get("jobDescription") or item.get("jobExcerpt")
                ),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=True,
                    salary_min=_positive(item.get("salaryMin")),
                    salary_max=_positive(item.get("salaryMax")),
                    salary_currency=item.get("salaryCurrency"),
                    employment_type=_first(item.get("jobType")),
                    date_posted=_parse_date(item.get("pubDate")),
                )
            )
        return jobs


class RemoteOKSource(JobSource):
    """remoteok.com/api - keyless, ~100 newest jobs, attribution required.

    The first array element is a legal/attribution notice object, not a job
    (it has ``legal`` + ``last_updated`` and none of the posting fields), so
    it is skipped by shape rather than by index.
    """

    source = "remoteok"

    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        data = self._get_json(client, "https://remoteok.com/api")
        jobs: list[FetchedJob] = []
        for item in data:
            if not isinstance(item, dict) or "legal" in item or not item.get("id"):
                continue  # attribution notice element, or a malformed row
            job = JobPosting(
                title=item.get("position") or item.get("title", ""),
                company=item.get("company", ""),
                location=item.get("location") or "Remote",
                url=item.get("url") or item.get("apply_url"),
                description=html_to_text(item.get("description")),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("id")),
                    remote=True,
                    salary_min=_positive(item.get("salary_min")),
                    salary_max=_positive(item.get("salary_max")),
                    salary_currency="USD"
                    if _positive(item.get("salary_min"))
                    else None,
                    date_posted=_parse_date(item.get("date"))
                    or _from_epoch(item.get("epoch")),
                )
            )
        return jobs


class HimalayasSource(JobSource):
    """himalayas.app/jobs/api - keyless, remote-only, 100k+ postings.

    The plain feed has no query parameter; the sibling ``/jobs/api/search``
    endpoint takes ``q`` and returns the same job shape, so a keyword switches
    endpoints rather than adding a filter.
    """

    source = "himalayas"

    def fetch(
        self,
        client: httpx.Client,
        q: str = "",
        limit: int = 50,
        offset: int = 0,
        **params,
    ) -> list[FetchedJob]:
        query: dict[str, object] = {"limit": limit, "offset": offset}
        if q:
            url = "https://himalayas.app/jobs/api/search"
            query["q"] = q
        else:
            url = "https://himalayas.app/jobs/api"
        data = self._get_json(client, url, params=query)
        jobs: list[FetchedJob] = []
        for item in data.get("jobs") or []:
            restrictions = item.get("locationRestrictions") or []
            job = JobPosting(
                title=item.get("title", ""),
                company=item.get("companyName", ""),
                location=", ".join(restrictions) if restrictions else "Remote",
                url=item.get("applicationLink") or item.get("guid"),
                description=html_to_text(
                    item.get("description") or item.get("excerpt")
                ),
            )
            jobs.append(
                FetchedJob(
                    job=job,
                    source=self.source,
                    source_id=str(item.get("guid") or item.get("title")),
                    remote=True,
                    salary_min=_positive(item.get("minSalary")),
                    salary_max=_positive(item.get("maxSalary")),
                    salary_currency=item.get("currency"),
                    employment_type=item.get("employmentType"),
                    date_posted=_from_epoch(item.get("pubDate")),
                )
            )
        return jobs
