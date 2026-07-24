"""DB-facing matching service: score stored jobs against a CV and persist."""

from __future__ import annotations

from ..db.repository import JobRepository, row_to_job
from ..models import CVProfile
from .embeddings import Embedder, get_embedder
from .scoring import score_job


class ScoringService:
    """Score every non-duplicate job against a CV, storing score + explanation."""

    def __init__(self, session, embedder: Embedder | None = None):
        self.session = session
        self.jobs = JobRepository(session)
        self.embedder = embedder or get_embedder()

    def score_all(self, cv: CVProfile) -> int:
        """Score all non-duplicate jobs. Returns the number scored."""
        rows = self.jobs.list(include_duplicates=False)
        for row in rows:
            explanation = score_job(cv, row_to_job(row), embedder=self.embedder)
            row.match_score = explanation.score
            row.match_explanation = explanation.to_dict()
            self.session.add(row)
        self.session.flush()
        return len(rows)
