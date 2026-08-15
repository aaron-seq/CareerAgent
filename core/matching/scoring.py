"""
Explainable resume <-> job matching.

Combines two signals into a 0-100 score:

* **semantic** cosine similarity between the CV and job embeddings, and
* **keyword** overlap between the job's required skills and the CV's skills.

The result carries the matched and missing keywords so the UI can explain *why*
a job scored the way it did -- never a bare number.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from rapidfuzz import fuzz

from ..models import CVProfile, JobPosting
from .embeddings import Embedder, cosine_similarity, get_embedder, tokenize

# Weighting of the two signals in the final score.
_SEMANTIC_WEIGHT = 0.6
_KEYWORD_WEIGHT = 0.4

# Common English function words plus job-posting filler -- none of these are
# ever skills, but they dominate a raw job description once tech_stack/
# requirements aren't populated (see _job_keywords). A short hand-picked list
# (the previous ~20 words) let plain prose like "at", "is", "not", "who",
# "why" leak into the "missing skills" UI as if they were unmet requirements.
_STOPWORDS = {
    # Articles, pronouns, determiners
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "mine",
    "myself",
    "we",
    "us",
    "our",
    "ours",
    "ourselves",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
    "he",
    "him",
    "his",
    "himself",
    "she",
    "her",
    "hers",
    "herself",
    "it",
    "its",
    "itself",
    "they",
    "them",
    "their",
    "theirs",
    "themselves",
    "who",
    "whom",
    "whose",
    "whoever",
    "whatever",
    "whichever",
    "what",
    "which",
    "each",
    "every",
    "either",
    "neither",
    "any",
    "some",
    "all",
    "both",
    "few",
    "more",
    "most",
    "other",
    "another",
    "such",
    "own",
    "same",
    "no",
    "none",
    # Prepositions / conjunctions
    "and",
    "or",
    "but",
    "nor",
    "so",
    "yet",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "without",
    "within",
    "about",
    "above",
    "below",
    "between",
    "among",
    "through",
    "during",
    "before",
    "after",
    "against",
    "along",
    "around",
    "as",
    "because",
    "behind",
    "beneath",
    "beside",
    "besides",
    "beyond",
    "despite",
    "down",
    "except",
    "from",
    "if",
    "into",
    "like",
    "near",
    "off",
    "onto",
    "out",
    "outside",
    "over",
    "past",
    "per",
    "since",
    "than",
    "then",
    "there",
    "toward",
    "towards",
    "under",
    "underneath",
    "until",
    "unto",
    "up",
    "upon",
    "versus",
    "via",
    "when",
    "where",
    "while",
    "why",
    "how",
    # Verbs (be/have/do + modals) and common filler verbs
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "am",
    "has",
    "have",
    "had",
    "having",
    "do",
    "does",
    "did",
    "doing",
    "done",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "can",
    "could",
    "not",
    "get",
    "gets",
    "getting",
    "got",
    "make",
    "makes",
    "making",
    "made",
    "need",
    "needs",
    "needed",
    "want",
    "wants",
    "wanted",
    "help",
    "helps",
    "helping",
    "join",
    "joining",
    "looking",
    "seek",
    "seeking",
    "including",
    "include",
    "includes",
    "included",
    # Common adverbs/adjectives with no skill signal
    "just",
    "only",
    "also",
    "very",
    "too",
    "again",
    "further",
    "once",
    "here",
    "well",
    "still",
    "even",
    "much",
    "many",
    "several",
    "various",
    "new",
    "great",
    "excellent",
    "strong",
    "ideal",
    "ideally",
    "passionate",
    "fast",
    "across",
    "based",
    # Job-posting boilerplate
    "experience",
    "years",
    "year",
    "team",
    "teams",
    "work",
    "works",
    "working",
    "worked",
    "ability",
    "using",
    "used",
    "use",
    "knowledge",
    "skill",
    "skills",
    "role",
    "roles",
    "job",
    "jobs",
    "position",
    "positions",
    "company",
    "companies",
    "candidate",
    "candidates",
    "apply",
    "application",
    "applicant",
    "applicants",
    "opportunity",
    "opportunities",
    "responsibilities",
    "responsible",
    "requirement",
    "requirements",
    "required",
    "require",
    "requires",
    "preferred",
    "plus",
    "benefit",
    "benefits",
    "salary",
    "employer",
    "employment",
    "environment",
    "business",
    "businesses",
    "product",
    "products",
    "customer",
    "customers",
    "client",
    "clients",
    "user",
    "users",
    "people",
    "person",
    "someone",
    "everyone",
    "anyone",
    "thing",
    "things",
    "way",
    "ways",
    "day",
    "days",
    "time",
    "times",
    "full",
    "part",
    "remote",
    "hybrid",
    "office",
    "location",
    "world",
    "etc",
}


def _cv_text(cv: CVProfile) -> str:
    parts = [cv.summary or "", " ".join(cv.skills)]
    for exp in cv.experiences:
        parts.append(f"{exp.title} {exp.company}")
        parts.extend(exp.achievements)
        parts.extend(exp.technologies)
    for proj in cv.projects:
        parts.append(f"{proj.name} {proj.description}")
        parts.extend(proj.technologies)
    parts.extend(cv.education)
    return "\n".join(p for p in parts if p)


def _job_text(job: JobPosting) -> str:
    parts = [job.title, job.description]
    parts.extend(job.requirements)
    parts.extend(job.nice_to_have)
    parts.extend(job.tech_stack)
    return "\n".join(p for p in parts if p)


def _cv_skill_set(cv: CVProfile) -> set[str]:
    skills: set[str] = set()
    for s in cv.skills:
        skills.update(tokenize(s))
    for exp in cv.experiences:
        for t in exp.technologies:
            skills.update(tokenize(t))
    for proj in cv.projects:
        for t in proj.technologies:
            skills.update(tokenize(t))
    return {s for s in skills if s not in _STOPWORDS and len(s) > 1}


def _job_keywords(job: JobPosting) -> set[str]:
    """Prefer explicit tech_stack/requirements; fall back to description."""
    keywords: set[str] = set()
    for t in job.tech_stack:
        keywords.update(tokenize(t))
    for r in job.requirements + job.nice_to_have:
        keywords.update(tokenize(r))
    if not keywords:
        keywords.update(tokenize(job.description))
    return {k for k in keywords if k not in _STOPWORDS and len(k) > 1}


def _fuzzy_contains(skill_set: set[str], keyword: str, threshold: int = 88) -> bool:
    """True if the keyword matches a CV skill exactly or fuzzily (typos/plurals)."""
    if keyword in skill_set:
        return True
    return any(fuzz.ratio(keyword, s) >= threshold for s in skill_set)


@dataclass
class MatchExplanation:
    score: float = 0.0
    semantic: float = 0.0
    keyword_overlap: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def score_job(
    cv: CVProfile, job: JobPosting, embedder: Embedder | None = None
) -> MatchExplanation:
    """Score a job against a CV, with an explanation."""
    embedder = embedder or get_embedder()

    cv_vec = embedder.embed(_cv_text(cv))
    job_vec = embedder.embed(_job_text(job))
    semantic = max(0.0, cosine_similarity(cv_vec, job_vec))  # clamp negatives

    skills = _cv_skill_set(cv)
    keywords = sorted(_job_keywords(job))
    matched = [k for k in keywords if _fuzzy_contains(skills, k)]
    missing = [k for k in keywords if k not in matched]
    keyword_overlap = (len(matched) / len(keywords)) if keywords else 0.0

    final = 100.0 * (_SEMANTIC_WEIGHT * semantic + _KEYWORD_WEIGHT * keyword_overlap)
    return MatchExplanation(
        score=round(final, 1),
        semantic=round(semantic, 4),
        keyword_overlap=round(keyword_overlap, 4),
        matched_keywords=matched,
        missing_keywords=missing,
    )
