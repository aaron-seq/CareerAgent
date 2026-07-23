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


def _skill_set(cv: CVProfile) -> set[str]:
    s: set[str] = set()
    for skill in cv.skills:
        s.update(tokenize(skill))
    return s


def assert_no_fabrication(original: CVProfile, tailored: CVProfile) -> None:
    """Guarantee the tailored resume adds no new skills/companies/titles."""
    orig_skills = set(original.skills)
    if not set(tailored.skills).issubset(orig_skills):
        raise FabricationError("Tailored resume introduced new skills.")
    orig_companies = {e.company for e in original.experiences}
    orig_titles = {e.title for e in original.experiences}
    for exp in tailored.experiences:
        if exp.company not in orig_companies or exp.title not in orig_titles:
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

    # 3. Tailored summary drawn only from real, matched skills.
    top_skills = relevant[:4]
    if top_skills:
        summary = (
            f"{job.title} candidate with hands-on experience in "
            f"{', '.join(top_skills)}."
        )
        if cv.summary:
            summary = f"{summary} {cv.summary}"
    else:
        summary = cv.summary

    tailored = cv.model_copy(
        update={
            "skills": tailored_skills,
            "experiences": reordered,
            "summary": summary,
        }
    )
    assert_no_fabrication(cv, tailored)

    report = TailorReport(
        emphasized_skills=relevant,
        gaps=sorted(match.missing_keywords),
        reordered_experience=experience_changed,
    )
    return tailored, report
