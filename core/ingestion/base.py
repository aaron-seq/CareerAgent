"""
Ingestion framework: sources fetch, the service normalizes and persists.

A :class:`JobSource` knows how to call one provider (an ATS public API or an
aggregator) and yield :class:`FetchedJob` records with a canonical
:class:`~core.models.JobPosting` plus structured extras (remote flag, salary,
posting date). :class:`IngestionService` upserts them into the DB idempotently.

All network access goes through an injected ``httpx.Client`` so tests mock the
transport (no live calls in CI).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx

from ..db.repository import JobRepository
from ..models import JobPosting

DEFAULT_TIMEOUT = 15.0
USER_AGENT = "CareerAgent/1.0 (+https://github.com/aaron-seq/CareerAgent)"


@dataclass
class FetchedJob:
    """A normalized job plus the structured extras a source can provide."""

    job: JobPosting
    source: str
    source_id: Optional[str] = None
    remote: bool = False
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    employment_type: Optional[str] = None
    date_posted: Optional[datetime] = None


class JobSource(ABC):
    """Base class for a single job provider."""

    #: Short stable identifier stored on each row (e.g. "greenhouse").
    source: str = "base"

    @abstractmethod
    def fetch(self, client: httpx.Client, **params) -> list[FetchedJob]:
        """Return normalized jobs from the provider."""

    # Small helper so subclasses share timeout/headers/error handling.
    def _get_json(self, client: httpx.Client, url: str, **kwargs) -> dict | list:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        resp = client.get(url, headers=headers, timeout=DEFAULT_TIMEOUT, **kwargs)
        resp.raise_for_status()
        return resp.json()


@dataclass
class IngestionResult:
    source: str
    fetched: int = 0
    upserted: int = 0
    errors: list[str] = field(default_factory=list)


class IngestionService:
    """Fetch from a source and persist into the DB via :class:`JobRepository`."""

    def __init__(self, session):
        self.session = session
        self.jobs = JobRepository(session)

    def ingest(
        self,
        source: JobSource,
        client: httpx.Client | None = None,
        **params,
    ) -> IngestionResult:
        result = IngestionResult(source=source.source)
        owns_client = client is None
        client = client or httpx.Client()
        try:
            fetched = source.fetch(client, **params)
        except Exception as exc:  # network / parse failures isolated per source
            result.errors.append(f"{source.source}: {exc}")
            return result
        finally:
            if owns_client:
                client.close()

        result.fetched = len(fetched)
        for fj in fetched:
            row = self.jobs.upsert(fj.job, source=fj.source, source_id=fj.source_id)
            row.remote = fj.remote
            row.salary_min = fj.salary_min
            row.salary_max = fj.salary_max
            row.salary_currency = fj.salary_currency
            row.employment_type = fj.employment_type
            row.date_posted = fj.date_posted
            self.session.add(row)
            result.upserted += 1
        self.session.flush()
        return result
