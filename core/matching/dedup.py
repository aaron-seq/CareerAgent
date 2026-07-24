"""
Collapse duplicate postings.

The same role often appears on 3-4 boards (Greenhouse + LinkedIn + Indeed +
an aggregator). We collapse them with a two-tier rule:

1. exact match on the normalized ``dedup_key`` (title|company|location), then
2. a fuzzy fallback -- same normalized company and a high title similarity --
   to catch "Senior SWE" vs "Senior Software Engineer".

The earliest-seen row wins as canonical; the rest are flagged duplicates
pointing at it.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from ..normalize import normalize_company_name, normalize_title


@dataclass
class DedupItem:
    id: int
    title: str
    company: str
    location: str | None
    dedup_key: str


@dataclass
class _Rep:
    id: int
    dedup_key: str
    norm_company: str
    norm_title: str


def compute_duplicates(items: list[DedupItem], threshold: int = 90) -> dict[int, int]:
    """Map each duplicate item id -> the canonical item id it collapses into."""
    reps: list[_Rep] = []
    mapping: dict[int, int] = {}
    for it in sorted(items, key=lambda x: x.id):
        nc = normalize_company_name(it.company)
        nt = normalize_title(it.title)
        matched: _Rep | None = None
        for rep in reps:
            if rep.dedup_key == it.dedup_key:
                matched = rep
                break
            if (
                rep.norm_company == nc
                and fuzz.token_sort_ratio(rep.norm_title, nt) >= threshold
            ):
                matched = rep
                break
        if matched is not None:
            mapping[it.id] = matched.id
        else:
            reps.append(
                _Rep(id=it.id, dedup_key=it.dedup_key, norm_company=nc, norm_title=nt)
            )
    return mapping


class DedupService:
    """Recompute duplicate flags across all stored jobs."""

    def __init__(self, session):
        from ..db.repository import JobRepository

        self.session = session
        self.jobs = JobRepository(session)

    def run(self, threshold: int = 90) -> int:
        """Flag duplicates in the DB. Returns the number of duplicates found."""
        rows = self.jobs.list(include_duplicates=True)
        items = [
            DedupItem(
                id=r.id,
                title=r.title,
                company=r.company_name,
                location=r.location,
                dedup_key=r.dedup_key,
            )
            for r in rows
        ]
        mapping = compute_duplicates(items, threshold=threshold)
        for row in rows:
            if row.id in mapping:
                row.is_duplicate = True
                row.canonical_job_id = mapping[row.id]
            else:
                row.is_duplicate = False
                row.canonical_job_id = None
            self.session.add(row)
        self.session.flush()
        return len(mapping)
