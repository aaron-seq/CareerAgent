"""
Truthful resume tailoring.

Tailoring here means *reordering and emphasizing* content the candidate already
has to surface job-relevant material -- never inventing skills or experience.
The ethics guardrail (CLAUDE.md) is enforced in code:
:func:`assert_no_fabrication` guarantees the tailored resume's skills,
companies, and titles are all subsets of the original.

Missing job keywords are reported as *gaps* for the human to address honestly,
not silently added to the resume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..matching.embeddings import Embedder, cosine_similarity, get_embedder, tokenize
from ..matching.scoring import score_job
from ..models import CVProfile, JobPosting


@dataclass
class TailorReport:
    emphasized_skills: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    reordered_experience: bool = False


class FabricationError(AssertionError):
    """Raised when a tailored resume would contain content not in the original."""


def assert_no_fabrication(original: CVProfile, tailored: CVProfile) -> None:
    """Guarantee the tailored resume adds no new skills, and no experience
    entry claims a (company, title) combination the candidate didn't
    actually hold.

    Checking company and title against independent sets (rather than as a
    pair) would pass a resume claiming "Manager at Foo" for a candidate who
    was only ever "Engineer at Foo" and "Manager at Bar" -- both fields are
    individually real, just never true together. Unreachable through
    tailor_resume() today (it only reorders existing Experience objects,
    never recombines their fields), but this function's contract should
    hold regardless of how it's called.
    """
    orig_skills = set(original.skills)
    if not set(tailored.skills).issubset(orig_skills):
        raise FabricationError("Tailored resume introduced new skills.")
    other_fields = set(type(original).model_fields) - {"skills", "experiences"}
    if any(getattr(original, name) != getattr(tailored, name) for name in other_fields):
        raise FabricationError("Tailored resume changed candidate facts.")
    original_experiences = [entry.model_dump() for entry in original.experiences]
    for exp in tailored.experiences:
        if exp.model_dump() not in original_experiences:
            raise FabricationError("Tailored resume introduced new experience.")


def tailor_resume(
    cv: CVProfile, job: JobPosting, embedder: Embedder | None = None
) -> tuple[CVProfile, TailorReport]:
    """Return a truthfully tailored copy of ``cv`` plus a report."""
    embedder = embedder or get_embedder()
    match = score_job(cv, job, embedder=embedder)
    matched = set(match.matched_keywords)

    # 1. Reorder skills: job-relevant ones first, order otherwise preserved.
    def is_relevant(skill: str) -> bool:
        return bool(matched & set(tokenize(skill)))

    relevant = [s for s in cv.skills if is_relevant(s)]
    rest = [s for s in cv.skills if not is_relevant(s)]
    tailored_skills = relevant + rest

    # 2. Reorder experiences by semantic relevance to the job.
    job_vec = embedder.embed(
        f"{job.title}\n{job.description}\n{' '.join(job.tech_stack)}"
    )

    def exp_relevance(exp) -> float:
        text = f"{exp.title} {exp.company} " + " ".join(
            exp.achievements + exp.technologies
        )
        return cosine_similarity(embedder.embed(text), job_vec)

    reordered = sorted(cv.experiences, key=exp_relevance, reverse=True)
    experience_changed = [e.title for e in reordered] != [
        e.title for e in cv.experiences
    ]

    tailored = cv.model_copy(
        update={
            "skills": tailored_skills,
            "experiences": reordered,
        }
    )
    assert_no_fabrication(cv, tailored)

    report = TailorReport(
        emphasized_skills=relevant,
        gaps=sorted(match.missing_keywords),
        reordered_experience=experience_changed,
    )
    return tailored, report
