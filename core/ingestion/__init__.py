"""Job ingestion: API-first sources normalized into canonical JobPostings."""

from .aggregators import AdzunaSource, RemotiveSource, TheMuseSource
from .ats import AshbySource, GreenhouseSource, LeverSource
from .base import FetchedJob, IngestionResult, IngestionService, JobSource

__all__ = [
    "FetchedJob",
    "IngestionResult",
    "IngestionService",
    "JobSource",
    "GreenhouseSource",
    "LeverSource",
    "AshbySource",
    "AdzunaSource",
    "TheMuseSource",
    "RemotiveSource",
]
