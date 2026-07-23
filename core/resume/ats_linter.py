"""
ATS-friendliness linter.

Flags the layout/content choices that trip up applicant-tracking systems:
tables/columns, header/footer contact info, images/icons, emojis, non-standard
section headings, and missing essentials. Evidence-based rules from
docs/RESEARCH.md (section D).

Works on the structured :class:`CVProfile` plus, when available, the raw
extracted text (which reveals layout artifacts like column whitespace or
box-drawing characters).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import CVProfile

# Standard, ATS-recognized section headings.
_STANDARD_HEADINGS = {
    "experience",
    "work experience",
    "employment",
    "education",
    "skills",
    "technical skills",
    "projects",
    "summary",
    "professional summary",
    "certifications",
    "publications",
    "awards",
}

# Emoji / symbol ranges that ATS parsers commonly choke on.
_EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]")
# Box-drawing / block characters, or a line using pipes as column separators.
_TABLE_CHARS = re.compile(r"[─-▟]")
_PIPE_COLUMNS = re.compile(r"\S\s*\|\s*\S.*\|")
# A heading-looking line: short, title-ish, maybe ALL CAPS.
_HEADING_LINE = re.compile(r"^[A-Z][A-Za-z /&]{2,30}$")


@dataclass
class ATSIssue:
    severity: str  # "error" | "warning" | "info"
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.message}"


def lint(cv: CVProfile, raw_text: str | None = None) -> list[ATSIssue]:
    """Return ATS-friendliness issues, most severe first."""
    issues: list[ATSIssue] = []

    # Essentials.
    if not cv.email:
        issues.append(ATSIssue("error", "Missing email address."))
    if not cv.name:
        issues.append(ATSIssue("error", "Missing candidate name."))
    if not cv.skills:
        issues.append(ATSIssue("warning", "No skills section detected."))
    if not cv.experiences:
        issues.append(ATSIssue("warning", "No work experience detected."))

    text = raw_text if raw_text is not None else (cv.raw_text or "")

    if _EMOJI.search(text) or any(_EMOJI.search(s) for s in cv.skills):
        issues.append(
            ATSIssue("error", "Emojis/symbols found; many ATS read these as garbage.")
        )

    if _TABLE_CHARS.search(text) or any(
        _PIPE_COLUMNS.search(line) for line in text.splitlines()
    ):
        issues.append(
            ATSIssue(
                "error",
                "Table/column characters detected; use a single-column layout.",
            )
        )

    # Multi-column heuristic: many lines with a wide internal gap.
    if text:
        gap_lines = sum(
            1 for line in text.splitlines() if re.search(r"\S {4,}\S", line)
        )
        if gap_lines >= 5:
            issues.append(
                ATSIssue(
                    "warning",
                    "Wide internal whitespace suggests a multi-column layout; "
                    "ATS parse single-column best.",
                )
            )

        # Non-standard section headings.
        for line in text.splitlines():
            stripped = line.strip()
            if _HEADING_LINE.match(stripped) and len(stripped.split()) <= 4:
                if stripped.lower() not in _STANDARD_HEADINGS and _looks_like_heading(
                    stripped
                ):
                    issues.append(
                        ATSIssue(
                            "info",
                            f"Non-standard section heading '{stripped}'. Prefer "
                            "standard headings (Experience, Education, Skills).",
                        )
                    )

    severity_rank = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: severity_rank[i.severity])
    return issues


def _looks_like_heading(line: str) -> bool:
    """Reduce false positives: treat only ALL-CAPS or Title-Case short lines."""
    words = line.split()
    if not words:
        return False
    all_caps = line.isupper()
    title_case = all(w[:1].isupper() for w in words if w)
    return all_caps or title_case


def is_ats_friendly(cv: CVProfile, raw_text: str | None = None) -> bool:
    """True when there are no error-severity issues."""
    return not any(i.severity == "error" for i in lint(cv, raw_text))
