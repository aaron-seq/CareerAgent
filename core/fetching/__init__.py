"""Fetching fallback: ATS detection, JSON-LD extraction, polite HTTP."""

from .ats_detection import ATSMatch, detect, detect_from_html, detect_from_url
from .jsonld import extract_jsonld_jobs
from .polite import PoliteFetcher, RobotsDisallowed

__all__ = [
    "ATSMatch",
    "detect",
    "detect_from_html",
    "detect_from_url",
    "extract_jsonld_jobs",
    "PoliteFetcher",
    "RobotsDisallowed",
]
