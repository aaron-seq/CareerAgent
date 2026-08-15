"""Phase 4 -- embeddings, dedup, and explainable scoring."""

from __future__ import annotations

from core.db.repository import JobRepository
from core.matching import (
    DedupItem,
    DedupService,
    HashingEmbedder,
    ScoringService,
    compute_duplicates,
    cosine_similarity,
    score_job,
)
from core.matching.embeddings import tokenize
from core.models import CVProfile, Experience, JobPosting, Project

# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #


def test_hashing_embedder_is_deterministic_and_normalized():
    emb = HashingEmbedder(dim=128)
    v1 = emb.embed("python machine learning")
    v2 = emb.embed("python machine learning")
    assert v1 == v2
    assert len(v1) == 128
    # L2-normalized -> norm ~ 1.
    assert abs(sum(x * x for x in v1) ** 0.5 - 1.0) < 1e-9


def test_cosine_similarity_reflects_overlap():
    emb = HashingEmbedder()
    a = emb.embed("python pytorch deep learning models")
    b = emb.embed("python pytorch deep learning models")
    c = emb.embed("accounting tax audit finance")
    assert cosine_similarity(a, b) > 0.99
    assert cosine_similarity(a, c) < cosine_similarity(a, b)


def test_cosine_empty_is_zero():
    assert cosine_similarity([], [1.0]) == 0.0


def test_tokenize_strips_trailing_period_but_keeps_dotted_tokens():
    # Sentence-ending periods glue onto the previous word (the [.] in the
    # token regex is there for c++/.net/node.js, not prose punctuation).
    assert tokenize("Built on Node.js.") == ["built", "on", "node.js"]
    assert tokenize("Our API.") == ["our", "api"]
    # Legitimate dotted/symbol tokens must survive untouched.
    assert tokenize("c++") == ["c++"]
    assert tokenize(".net") == [".net"]
    assert tokenize("node.js") == ["node.js"]


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _ml_cv() -> CVProfile:
    return CVProfile(
        name="Dev",
        summary="ML engineer",
        skills=["Python", "PyTorch", "Kubernetes"],
        experiences=[
            Experience(
                title="ML Engineer",
                company="AI Co",
                duration="3y",
                technologies=["Python", "PyTorch"],
            )
        ],
        projects=[
            Project(name="Recsys", description="recommender", technologies=["Python"])
        ],
    )


def test_score_job_explains_matched_and_missing():
    cv = _ml_cv()
    job = JobPosting(
        title="Machine Learning Engineer",
        company="Acme",
        description="Build ML systems.",
        tech_stack=["Python", "PyTorch", "Go"],
        requirements=["Kubernetes"],
    )
    result = score_job(cv, job, embedder=HashingEmbedder())
    assert 0 <= result.score <= 100
    assert "python" in result.matched_keywords
    assert "pytorch" in result.matched_keywords
    assert "go" in result.missing_keywords  # not in CV
    assert result.keyword_overlap > 0


def test_score_job_relevant_beats_irrelevant():
    cv = _ml_cv()
    relevant = JobPosting(
        title="ML Engineer",
        company="A",
        description="ML",
        tech_stack=["Python", "PyTorch"],
    )
    irrelevant = JobPosting(
        title="Tax Accountant",
        company="B",
        description="audit tax filings",
        tech_stack=["Excel", "SAP"],
    )
    emb = HashingEmbedder()
    assert score_job(cv, relevant, emb).score > score_job(cv, irrelevant, emb).score


def test_score_fuzzy_keyword_match():
    cv = CVProfile(skills=["Kubernetes"])
    job = JobPosting(title="SRE", company="X", tech_stack=["kubernetes"])
    result = score_job(cv, job, embedder=HashingEmbedder())
    assert "kubernetes" in result.matched_keywords


def test_score_job_description_fallback_filters_stopwords_and_punctuation():
    # No tech_stack/requirements -- exactly the aggregator-ingestion case
    # (Greenhouse/Lever/Ashby/Adzuna/etc. never populate those fields), so
    # _job_keywords falls back to tokenizing raw prose.
    cv = _ml_cv()
    job = JobPosting(
        title="Applied AI Architect",
        company="Acme",
        description=(
            "You will work directly with customers who are building on top "
            "of our API. This role is not just about writing code -- it is "
            "about understanding why a customer's workflow is failing. You "
            "should be comfortable working with Python, Kubernetes, and "
            "Node.js. Prior experience with .NET or C++ is a plus, but is "
            "not required."
        ),
    )
    result = score_job(cv, job, embedder=HashingEmbedder())
    all_keywords = set(result.matched_keywords) | set(result.missing_keywords)

    # Plain-English function words must not surface as "missing skills".
    leaked_stopwords = all_keywords & {
        "at",
        "is",
        "it",
        "not",
        "than",
        "who",
        "why",
        "you",
        "we",
        "our",
        "your",
        "was",
        "are",
        "this",
        "about",
    }
    assert not leaked_stopwords, f"stopwords leaked into keywords: {leaked_stopwords}"

    # Sentence-ending periods must not glue onto the previous word.
    glued = {k for k in all_keywords if k.endswith(".")}
    assert not glued, f"punctuation-glued tokens: {glued}"

    # Real tech terms -- including dotted/symbol ones -- must still surface.
    assert {"python", "kubernetes", "node.js", ".net", "c++"} <= all_keywords


# --------------------------------------------------------------------------- #
# Dedup (pure)
# --------------------------------------------------------------------------- #


def test_compute_duplicates_exact_key():
    items = [
        DedupItem(
            1, "Software Engineer", "Acme", "Remote", "software engineer|acme|remote"
        ),
        DedupItem(
            2, "Software Engineer", "Acme", "Remote", "software engineer|acme|remote"
        ),
        DedupItem(3, "Designer", "Acme", "NYC", "designer|acme|nyc"),
    ]
    mapping = compute_duplicates(items)
    assert mapping == {2: 1}  # item 2 collapses into canonical 1; 3 is unique


def test_compute_duplicates_fuzzy_same_company():
    items = [
        DedupItem(1, "Senior Software Engineer", "Acme", "Remote", "k1"),
        DedupItem(2, "Software Engineer Senior", "Acme", "Remote", "k2"),
        DedupItem(3, "Senior Software Engineer", "Other Co", "Remote", "k3"),
    ]
    mapping = compute_duplicates(items, threshold=85)
    assert mapping.get(2) == 1  # fuzzy title match, same company
    assert 3 not in mapping  # different company -> not a duplicate


# --------------------------------------------------------------------------- #
# DB-facing services
# --------------------------------------------------------------------------- #


def test_dedup_service_flags_rows(session):
    jobs = JobRepository(session)
    jobs.upsert(
        JobPosting(title="SWE", company="Acme", location="Remote"), "greenhouse", "1"
    )
    jobs.upsert(
        JobPosting(title="SWE", company="Acme", location="Remote"), "lever", "2"
    )
    jobs.upsert(JobPosting(title="PM", company="Acme", location="NYC"), "ashby", "3")
    session.commit()

    dupes = DedupService(session).run()
    session.commit()
    assert dupes == 1
    visible = jobs.list(include_duplicates=False)
    assert len(visible) == 2  # one collapsed


def test_scoring_service_persists_scores(session):
    jobs = JobRepository(session)
    jobs.upsert(
        JobPosting(
            title="ML Engineer",
            company="Acme",
            description="ML",
            tech_stack=["Python", "PyTorch"],
        ),
        "greenhouse",
        "1",
    )
    session.commit()

    ScoringService(session, embedder=HashingEmbedder()).score_all(_ml_cv())
    session.commit()

    row = jobs.list()[0]
    assert row.match_score is not None and row.match_score > 0
    assert "matched_keywords" in row.match_explanation
