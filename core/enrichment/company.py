"""
Company enrichment: Glassdoor rating and layoff signal.

Reads a signals dataset (a small sample ships in ``data/``; swap in
layoffs.fyi / Glassdoor exports in production) and annotates Company rows.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..normalize import normalize_company_name

_DEFAULT_DATASET = Path(__file__).parent / "data" / "company_signals_sample.csv"


@dataclass
class CompanySignal:
    glassdoor_rating: float | None = None
    had_layoffs: bool = False


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


class CompanyEnricher:
    def __init__(self, signals: dict[str, CompanySignal]):
        self._signals = signals

    @classmethod
    def from_csv(cls, path: str | Path | None = None) -> CompanyEnricher:
        path = Path(path) if path else _DEFAULT_DATASET
        signals: dict[str, CompanySignal] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = normalize_company_name(row.get("company_name", ""))
                if not name:
                    continue
                rating = row.get("glassdoor_rating")
                signals[name] = CompanySignal(
                    glassdoor_rating=float(rating) if rating else None,
                    had_layoffs=_parse_bool(row.get("had_layoffs", "")),
                )
        return cls(signals)

    def lookup(self, company_name: str) -> CompanySignal | None:
        return self._signals.get(normalize_company_name(company_name))

    def annotate(self, session) -> int:
        from sqlmodel import select

        from ..db.tables import Company

        updated = 0
        for company in session.exec(select(Company)).all():
            signal = self.lookup(company.name)
            if signal is None:
                continue
            company.glassdoor_rating = signal.glassdoor_rating
            company.had_layoffs = signal.had_layoffs
            session.add(company)
            updated += 1
        session.flush()
        return updated
