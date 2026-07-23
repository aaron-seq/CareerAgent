"""Enrichment: salary, company signals, visa sponsorship, ghost detection."""

from .company import CompanyEnricher, CompanySignal
from .filters import (
    exclude_ghosts,
    filter_by_min_score,
    filter_remote,
    is_internship,
    is_new_grad,
)
from .ghost import GhostAnnotator, GhostAssessment, ghost_score
from .salary import SalaryEnricher, parse_salary
from .visa import VisaSponsorFilter

__all__ = [
    "CompanyEnricher",
    "CompanySignal",
    "exclude_ghosts",
    "filter_by_min_score",
    "filter_remote",
    "is_internship",
    "is_new_grad",
    "GhostAnnotator",
    "GhostAssessment",
    "ghost_score",
    "SalaryEnricher",
    "parse_salary",
    "VisaSponsorFilter",
]
