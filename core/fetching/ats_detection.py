"""
Detect which ATS backs a company's careers page.

Given a careers URL (or the page HTML), match known ATS URL signatures and
return the ATS type plus the board slug/token needed to call its public API
(see ``core.ingestion``). This lets us go from "here's a company careers page"
to "pull their jobs from the structured API" without scraping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Ordered signatures. Each captures the board slug/token in group 1
# (Workday captures tenant, datacenter, and site across groups).
_SIGNATURES: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/([\w-]+)", re.I)),
    (
        "workday",
        re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/([\w-]+)", re.I),
    ),
]


@dataclass
class ATSMatch:
    ats_type: str
    slug: str
    #: Extra captures (e.g. Workday datacenter/site) when relevant.
    extra: Optional[dict] = None


def detect_from_url(url: str) -> Optional[ATSMatch]:
    """Detect an ATS directly from a URL string."""
    if not url:
        return None
    for ats_type, pattern in _SIGNATURES:
        m = pattern.search(url)
        if not m:
            continue
        if ats_type == "workday":
            return ATSMatch(
                ats_type=ats_type,
                slug=m.group(1),
                extra={"datacenter": m.group(2), "site": m.group(3)},
            )
        return ATSMatch(ats_type=ats_type, slug=m.group(1))
    return None


def detect_from_html(html: str) -> Optional[ATSMatch]:
    """Detect an ATS by scanning page HTML for an embedded board URL."""
    if not html:
        return None
    for ats_type, pattern in _SIGNATURES:
        m = pattern.search(html)
        if not m:
            continue
        if ats_type == "workday":
            return ATSMatch(
                ats_type=ats_type,
                slug=m.group(1),
                extra={"datacenter": m.group(2), "site": m.group(3)},
            )
        return ATSMatch(ats_type=ats_type, slug=m.group(1))
    return None


def detect(url: str = "", html: str = "") -> Optional[ATSMatch]:
    """Try the URL first, then the HTML."""
    return detect_from_url(url) or detect_from_html(html)
