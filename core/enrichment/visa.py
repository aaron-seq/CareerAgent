"""
Visa-sponsorship filtering against **real** public sponsor registers.

Data sources (official, free, bulk-downloadable):

* **UK** -- Home Office *Register of licensed sponsors: workers* (CSV on
  gov.uk). This register is authoritative and complete: a company absent from
  it genuinely is not a licensed sponsor.
* **US** -- USCIS *H-1B Employer Data Hub* / DOL OFLC *LCA disclosure* files.
  These are historical filing records, so absence means "no recorded filings in
  the covered period", not a legal negative.

Fetch them with ``python -m scripts.fetch_datasets``.

**No sample or placeholder data ships with this project.** Inventing sponsor
status for real employers would be fabricating facts a user makes decisions on.
When no dataset is loaded, every lookup returns ``None`` (*unknown*) -- never
``False`` -- so the UI can say "unknown" instead of wrongly asserting that an
employer does not sponsor.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Optional

from ..normalize import normalize_company_name

#: Where a downloaded register is expected to live.
DEFAULT_DATASET_PATH = Path(
    os.environ.get(
        "CAREERAGENT_VISA_DATASET",
        Path(__file__).parent / "data" / "visa_sponsors.csv",
    )
)

# Header names seen across the official exports, lowercased.
_NAME_COLUMNS = (
    "organisation name",  # UK Home Office register
    "organization name",
    "employer (petitioner) name",  # USCIS H-1B Data Hub
    "employer name",
    "company_name",
    "company",
    "name",
)


class VisaSponsorFilter:
    """Look up whether an employer appears in a sponsor register.

    ``loaded`` is False when no dataset is available, in which case
    :meth:`is_sponsor` returns ``None`` (unknown) for every employer.
    """

    def __init__(self, sponsors: set[str] | None, source: str | None = None):
        self._sponsors = (
            {normalize_company_name(s) for s in sponsors if s}
            if sponsors is not None
            else None
        )
        self.source = source

    # -- construction ----------------------------------------------------- #

    @classmethod
    def unloaded(cls) -> VisaSponsorFilter:
        """A filter with no data: every lookup is 'unknown'."""
        return cls(sponsors=None)

    @classmethod
    def from_csv(cls, path: str | Path | None = None) -> VisaSponsorFilter:
        """Load a register from CSV.

        Auto-detects the employer-name column across the official export
        formats. Returns an :meth:`unloaded` filter when the file is absent,
        so a missing download degrades to "unknown" rather than crashing or --
        far worse -- silently answering "not a sponsor" for everyone.
        """
        path = Path(path) if path else DEFAULT_DATASET_PATH
        if not path.exists():
            return cls.unloaded()

        names: set[str] = set()
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                return cls.unloaded()
            lookup = {(f or "").strip().lower(): f for f in reader.fieldnames}
            column = next((lookup[c] for c in _NAME_COLUMNS if c in lookup), None)
            if column is None:
                raise ValueError(
                    f"{path}: no recognizable employer-name column in "
                    f"{reader.fieldnames}. Expected one of {_NAME_COLUMNS}."
                )
            for row in reader:
                value = (row.get(column) or "").strip()
                if value:
                    names.add(value)

        if not names:
            return cls.unloaded()
        return cls(names, source=str(path))

    # -- queries ---------------------------------------------------------- #

    @property
    def loaded(self) -> bool:
        return self._sponsors is not None

    def __len__(self) -> int:
        return len(self._sponsors) if self._sponsors else 0

    def is_sponsor(self, company_name: str) -> Optional[bool]:
        """True / False when a register is loaded; ``None`` when unknown."""
        if self._sponsors is None:
            return None
        return normalize_company_name(company_name) in self._sponsors

    def annotate(self, session) -> int:
        """Set ``sponsors_visa`` on Company rows. Returns rows updated.

        With no dataset loaded this is a no-op: we leave the column ``None``
        rather than writing an unfounded ``False``.
        """
        if not self.loaded:
            return 0

        from sqlmodel import select

        from ..db.tables import Company

        updated = 0
        for company in session.exec(select(Company)).all():
            company.sponsors_visa = self.is_sponsor(company.name)
            session.add(company)
            updated += 1
        session.flush()
        return updated
