"""Job ingestion: API-first sources normalized into canonical JobPostings."""

from .aggregators import AdzunaSource, RemotiveSource, TheMuseSource
from .ats import (
    AshbySource,
    GreenhouseSource,
    LeverSource,
    RecruiteeSource,
    SmartRecruitersSource,
    WorkableSource,
)
from .base import FetchedJob, IngestionResult, IngestionService, JobSource, parse_date
from .boards import (
    ATTRIBUTION,
    ArbeitnowSource,
    HimalayasSource,
    JobicySource,
    RemoteOKSource,
)

__all__ = [
    "FetchedJob",
    "IngestionResult",
    "IngestionService",
    "JobSource",
    "parse_date",
    "ATTRIBUTION",
    # Company boards (ATS)
    "GreenhouseSource",
    "LeverSource",
    "AshbySource",
    "SmartRecruitersSource",
    "RecruiteeSource",
    "WorkableSource",
    # Aggregators / job boards
    "AdzunaSource",
    "TheMuseSource",
    "RemotiveSource",
    "ArbeitnowSource",
    "JobicySource",
    "RemoteOKSource",
    "HimalayasSource",
]
