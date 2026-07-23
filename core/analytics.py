"""
Analytics: application funnel, A/B variant tracking, interview prep.

The funnel is computed from current application statuses (we don't store full
transition history yet), so "reached" counts reflect applications currently at
or past a stage. Rejected/withdrawn applications leave the ladder and are
reported separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from .db.tables import ApplicationStatus
from .models import JobPosting

# Ladder position for the active pipeline stages.
_ORDER = {
    ApplicationStatus.SAVED: 0,
    ApplicationStatus.APPLIED: 1,
    ApplicationStatus.SCREENING: 2,
    ApplicationStatus.INTERVIEW: 3,
    ApplicationStatus.OFFER: 4,
}
_LADDER = [
    ApplicationStatus.APPLIED,
    ApplicationStatus.SCREENING,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
]


@dataclass
class Funnel:
    total: int
    counts: dict[str, int]
    reached: dict[str, int]
    rejected: int
    withdrawn: int

    def conversion(self, frm: ApplicationStatus, to: ApplicationStatus) -> float:
        base = self.reached.get(frm.value, 0)
        return (self.reached.get(to.value, 0) / base) if base else 0.0


def compute_funnel(apps) -> Funnel:
    counts = {s.value: 0 for s in ApplicationStatus}
    for a in apps:
        counts[a.status.value] += 1

    reached: dict[str, int] = {}
    for stage in _LADDER:
        reached[stage.value] = sum(
            1 for a in apps if a.status in _ORDER and _ORDER[a.status] >= _ORDER[stage]
        )
    return Funnel(
        total=len(apps),
        counts=counts,
        reached=reached,
        rejected=counts[ApplicationStatus.REJECTED.value],
        withdrawn=counts[ApplicationStatus.WITHDRAWN.value],
    )


@dataclass
class VariantStats:
    variant: str
    sent: int = 0
    responses: int = 0

    @property
    def response_rate(self) -> float:
        return (self.responses / self.sent) if self.sent else 0.0


def variant_response_rates(records: list[tuple[str, bool]]) -> dict[str, VariantStats]:
    """Aggregate (variant_label, got_response) records into per-variant stats."""
    stats: dict[str, VariantStats] = {}
    for variant, responded in records:
        s = stats.setdefault(variant, VariantStats(variant=variant))
        s.sent += 1
        if responded:
            s.responses += 1
    return stats


# --------------------------------------------------------------------------- #
# Interview prep
# --------------------------------------------------------------------------- #

_BEHAVIORAL = [
    "Tell me about a time you disagreed with a teammate and how you resolved it.",
    "Describe a project you're most proud of and your specific contribution.",
    "Tell me about a time you failed and what you learned.",
]


def generate_interview_questions(job: JobPosting, limit: int = 10) -> list[str]:
    """Deterministic prep questions derived from the JD (no LLM required)."""
    questions: list[str] = []
    for tech in job.tech_stack[:5]:
        questions.append(f"Walk me through your hands-on experience with {tech}.")
    for req in job.requirements[:4]:
        questions.append(
            f"This role requires: '{req}'. How have you demonstrated that?"
        )
    for problem in job.problems[:2]:
        questions.append(f"How would you approach: {problem}?")
    questions.extend(_BEHAVIORAL)
    # De-dupe preserving order, then cap.
    seen: set[str] = set()
    ordered = [q for q in questions if not (q in seen or seen.add(q))]
    return ordered[:limit]
