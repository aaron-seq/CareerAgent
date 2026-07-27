"""Cover letter generation, held to the same truthfulness contract as tailoring.

A cover letter is free prose, so the subset checks in :mod:`tailor` do not
apply directly -- there are no structured fields to compare. What a letter can
still do is claim an employer the candidate never worked for, or quote a metric
that appears nowhere in the CV. Those are the two fabrication vectors worth
gating in code (CLAUDE.md guardrail 4), and :func:`verify_grounded` checks both
against the source profile.

Anything the letter cannot support is reported as a gap for the human to fill,
never invented -- the same posture :mod:`tailor` takes with missing keywords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import CVProfile, JobPosting
from ..prompts import COVER_LETTER_PROMPT
from .tailor import FabricationError

# A claim like "reduced downtime by 70%" or "2100+ samples". Bare years
# (2021-2025) and small ordinals are excluded: they are rarely achievement
# claims and would drown the check in false positives.
_METRIC = re.compile(r"\b\d[\d,.]*\s*(?:%|percent|x\b|\+)", re.IGNORECASE)


@dataclass
class CoverLetterReport:
    """What the letter leaned on, and what the human still needs to supply."""

    cited_metrics: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    word_count: int = 0


def _cv_corpus(cv: CVProfile) -> str:
    """Every string in the profile the letter is allowed to draw from."""
    parts: list[str] = [cv.summary or "", cv.raw_text or ""]
    for exp in cv.experiences:
        parts += [exp.title, exp.company, exp.duration or ""]
        parts += exp.achievements + exp.metrics + exp.technologies
    for proj in cv.projects:
        parts += [proj.name, proj.description or "", proj.impact or ""]
        parts += proj.technologies
    parts += cv.skills + cv.education
    return "\n".join(p for p in parts if p)


def _normalize_number(token: str) -> str:
    return re.sub(r"[,\s]", "", token).lower()


def verify_grounded(cv: CVProfile, job: JobPosting, letter: str) -> list[str]:
    """Return metric claims in ``letter`` that the CV does not support.

    Numbers are matched on digits alone, so "70%" in the letter is satisfied
    by "70%" anywhere in the CV. The job's own text counts as a valid source
    too -- quoting the posting's team size back at them is not a claim about
    the candidate.
    """
    supported = _normalize_number(_cv_corpus(cv) + "\n" + (job.description or ""))
    unsupported = []
    for m in _METRIC.finditer(letter):
        claim = m.group(0)
        digits = re.sub(r"[^\d]", "", claim)
        if digits and digits not in supported:
            unsupported.append(claim.strip())
    return unsupported


def assert_no_fabrication(cv: CVProfile, job: JobPosting, letter: str) -> None:
    """Raise if the letter claims an employer or metric absent from the CV."""
    lowered = letter.lower()
    known = {e.company.lower() for e in cv.experiences if e.company}
    # The addressed company is legitimately named even though it is not an
    # employer of record yet.
    known.add((job.company or "").lower())

    for phrase in re.findall(r"\bat ([A-Z][\w.&-]*(?: [A-Z][\w.&-]*)*)", letter):
        candidate = phrase.strip().lower()
        if candidate and not any(candidate.startswith(k) for k in known if k):
            raise FabricationError(
                f"Cover letter names an employer not in the CV: {phrase!r}"
            )

    unsupported = verify_grounded(cv, job, letter)
    if unsupported:
        raise FabricationError(
            "Cover letter cites metrics absent from the CV: " + ", ".join(unsupported)
        )

    if not lowered.strip():
        raise FabricationError("Cover letter is empty.")


def generate_cover_letter(
    llm, cv: CVProfile, job: JobPosting, tone: str = "professional"
) -> tuple[str, CoverLetterReport]:
    """Draft a cover letter grounded in ``cv``, and report what it leaned on.

    Raises :class:`FabricationError` if the draft invents an employer or a
    metric. The caller surfaces that to the human rather than silently
    shipping an unverifiable claim.
    """
    prompt = COVER_LETTER_PROMPT.format(
        name=cv.name or "the candidate",
        summary=cv.summary or "",
        experience="\n".join(
            f"- {e.title} at {e.company} ({e.duration}): "
            + "; ".join(e.achievements + e.metrics)
            for e in cv.experiences
        ),
        skills=", ".join(cv.skills),
        job_title=job.title,
        company=job.company,
        job_description=(job.description or "")[:3000],
        tone=tone,
    )

    data = llm.generate_json(prompt, temperature=0.4)
    letter = (data.get("letter") or "").strip()
    if not letter:
        raise FabricationError("Model returned no letter text.")

    assert_no_fabrication(cv, job, letter)

    report = CoverLetterReport(
        cited_metrics=[m.group(0).strip() for m in _METRIC.finditer(letter)],
        gaps=[g for g in (data.get("gaps") or []) if g],
        word_count=len(letter.split()),
    )
    return letter, report
