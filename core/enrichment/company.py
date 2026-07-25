"""
Company enrichment: employer-quality and risk signals.

**No sample or placeholder data ships with this project.** Ratings and layoff
history are facts about real, named employers; inventing them would put made-up
numbers in front of someone making career decisions.

Supply your own CSV (from a source you are licensed to use) with a
``company_name`` column plus any of:

    glassdoor_rating   float
    had_layoffs        true/false

Point at it with ``CAREERAGENT_COMPANY_DATASET`` or place it at
``core/enrichment/data/company_signals.csv``.

Unknown is represented as ``None`` throughout -- never ``False`` -- so the UI
can distinguish "no layoffs recorded" from "we have no data".
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..normalize import normalize_company_name

DEFAULT_DATASET_PATH = Path(
    os.environ.get(
        "CAREERAGENT_COMPANY_DATASET",
        Path(__file__).parent / "data" / "company_signals.csv",
    )
)


@dataclass
class CompanySignal:
    glassdoor_rating: Optional[float] = None
    had_layoffs: Optional[bool] = None


def _parse_bool(value: str | None) -> Optional[bool]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None  # blank or unrecognized -> unknown, not False


def _parse_float(value: str | None) -> Optional[float]:
    if value is None or not str(value).strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


class CompanyEnricher:
    def __init__(
        self, signals: dict[str, CompanySignal] | None, source: str | None = None
    ):
        self._signals = signals
        self.source = source

    @classmethod
    def unloaded(cls) -> CompanyEnricher:
        return cls(signals=None)

    @classmethod
    def from_csv(cls, path: str | Path | None = None) -> CompanyEnricher:
        """Load signals from CSV; missing file degrades to 'unloaded'."""
        path = Path(path) if path else DEFAULT_DATASET_PATH
        if not path.exists():
            return cls.unloaded()

        signals: dict[str, CompanySignal] = {}
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                return cls.unloaded()
            for row in reader:
                name = normalize_company_name(row.get("company_name", "") or "")
                if not name:
                    continue
                signals[name] = CompanySignal(
                    glassdoor_rating=_parse_float(row.get("glassdoor_rating")),
                    had_layoffs=_parse_bool(row.get("had_layoffs")),
                )
        if not signals:
            return cls.unloaded()
        return cls(signals, source=str(path))

    @property
    def loaded(self) -> bool:
        return self._signals is not None

    def lookup(self, company_name: str) -> Optional[CompanySignal]:
        if self._signals is None:
            return None
        return self._signals.get(normalize_company_name(company_name))

    def annotate(self, session) -> int:
        """Annotate Company rows. No-op when no dataset is loaded."""
        if not self.loaded:
            return 0

        from sqlmodel import select

        from ..db.tables import Company

        updated = 0
        for company in session.exec(select(Company)).all():
            signal = self.lookup(company.name)
            if signal is None:
                continue  # leave unknown as NULL
            company.glassdoor_rating = signal.glassdoor_rating
            company.had_layoffs = signal.had_layoffs
            session.add(company)
            updated += 1
        session.flush()
        return updated
