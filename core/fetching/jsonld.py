"""
Extract schema.org ``JobPosting`` structured data from a page.

JSON-LD is the single highest-value, lowest-risk extraction technique: most
career pages and boards embed ``<script type="application/ld+json">`` blocks
for SEO / Google-for-Jobs. We parse those first, before any DOM heuristics.

Handles the three shapes seen in the wild: a bare object, an array of objects,
and an ``@graph`` container.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..ingestion.aggregators import _parse_date
from ..ingestion.ats import html_to_text
from ..ingestion.base import FetchedJob
from ..models import JobPosting

SOURCE = "jsonld"


def _iter_jsonld_objects(html: str):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        # Normalize to a flat list of dicts.
        candidates: list[Any] = []
        if isinstance(data, list):
            candidates.extend(data)
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates.extend(data["@graph"])
            else:
                candidates.append(data)
        for obj in candidates:
            if isinstance(obj, dict):
                yield obj


def _is_job_posting(obj: dict) -> bool:
    t = obj.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == "jobposting" for x in t)
    return str(t).lower() == "jobposting"


def _extract_company(obj: dict) -> str:
    org = obj.get("hiringOrganization")
    if isinstance(org, dict):
        return org.get("name", "") or ""
    if isinstance(org, str):
        return org
    return ""


def _extract_location(obj: dict) -> Optional[str]:
    loc = obj.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if isinstance(loc, dict):
        address = loc.get("address")
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry")
                if isinstance(address.get("addressCountry"), str)
                else None,
            ]
            return ", ".join(p for p in parts if p) or None
    if obj.get("jobLocationType") == "TELECOMMUTE":
        return "Remote"
    return None


def _extract_salary(
    obj: dict,
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    base = obj.get("baseSalary")
    if not isinstance(base, dict):
        return None, None, None
    currency = base.get("currency")
    value = base.get("value")
    if isinstance(value, dict):
        vmin = value.get("minValue")
        vmax = value.get("maxValue")
        single = value.get("value")

        def _num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None

        return _num(vmin) or _num(single), _num(vmax) or _num(single), currency
    return None, None, currency


def extract_jsonld_jobs(html: str, page_url: str | None = None) -> list[FetchedJob]:
    """Return every JobPosting found in the page's JSON-LD blocks."""
    results: list[FetchedJob] = []
    for obj in _iter_jsonld_objects(html):
        if not _is_job_posting(obj):
            continue
        smin, smax, currency = _extract_salary(obj)
        remote = obj.get("jobLocationType") == "TELECOMMUTE"
        location = _extract_location(obj)
        job = JobPosting(
            title=obj.get("title", ""),
            company=_extract_company(obj),
            location=location,
            url=obj.get("url") or page_url,
            description=html_to_text(obj.get("description")),
        )
        results.append(
            FetchedJob(
                job=job,
                source=SOURCE,
                source_id=str(obj.get("identifier", {}).get("value"))
                if isinstance(obj.get("identifier"), dict)
                else (str(obj.get("identifier")) if obj.get("identifier") else None),
                remote=remote or bool(location and "remote" in location.lower()),
                salary_min=smin,
                salary_max=smax,
                salary_currency=currency,
                employment_type=(
                    obj.get("employmentType")
                    if isinstance(obj.get("employmentType"), str)
                    else None
                ),
                date_posted=_parse_date(obj.get("datePosted")),
            )
        )
    return results
