"""Matching: embeddings, dedup, and explainable resume<->job scoring."""

from .dedup import DedupItem, DedupService, compute_duplicates
from .embeddings import (
    Embedder,
    HashingEmbedder,
    SentenceTransformerEmbedder,
    cosine_similarity,
    get_embedder,
)
from .scoring import MatchExplanation, score_job
from .service import ScoringService

__all__ = [
    "DedupItem",
    "DedupService",
    "compute_duplicates",
    "Embedder",
    "HashingEmbedder",
    "SentenceTransformerEmbedder",
    "cosine_similarity",
    "get_embedder",
    "MatchExplanation",
    "score_job",
    "ScoringService",
]
