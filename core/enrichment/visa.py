"""
Visa-sponsorship filtering against public sponsor datasets.

A company is flagged as a likely sponsor if it appears in a sponsor register
(US H-1B Employer Data Hub / DOL LCA disclosures; UK Home Office Register of
Licensed Sponsors). A small illustrative sample ships in ``data/``; point the
loader at the full downloaded dataset in production.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..normalize import normalize_company_name

_DEFAULT_DATASET = Path(__file__).parent / "data" / "visa_sponsors_sample.csv"


class VisaSponsorFilter:
    def __init__(self, sponsors: set[str]):
        # Stored normalized for forgiving matching.
        self._sponsors = {normalize_company_name(s) for s in sponsors}

    @classmethod
    def from_csv(cls, path: str | Path | None = None) -> VisaSponsorFilter:
        path = Path(path) if path else _DEFAULT_DATASET
        names: set[str] = set()
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("company_name"):
                    names.add(row["company_name"])
        return cls(names)

    def is_sponsor(self, company_name: str) -> bool:
        return normalize_company_name(company_name) in self._sponsors

    def annotate(self, session) -> int:
        """Set ``sponsors_visa`` on Company rows. Returns rows updated."""
        from sqlmodel import select

        from ..db.tables import Company

        companies = session.exec(select(Company)).all()
        updated = 0
        for company in companies:
            company.sponsors_visa = self.is_sponsor(company.name)
            session.add(company)
            updated += 1
        session.flush()
        return updated
