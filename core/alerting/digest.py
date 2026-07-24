"""
Digest builder.

Assembles the top-matching, non-duplicate, non-ghost jobs into a digest that
can be rendered as Markdown (email/Slack) or RSS (feed readers). Pure and
deterministic; delivery lives in :mod:`core.alerting.emitters`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from xml.sax.saxutils import escape


@dataclass
class DigestItem:
    title: str
    company: str
    url: str | None
    score: float | None
    location: str | None = None
    salary: str | None = None


@dataclass
class Digest:
    items: list[DigestItem] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_markdown(self) -> str:
        if not self.items:
            return "# CareerAgent digest\n\nNo new matching jobs.\n"
        lines = ["# CareerAgent digest", ""]
        for it in self.items:
            score = f" ({it.score:.0f}% match)" if it.score is not None else ""
            link = f"[{it.title}]({it.url})" if it.url else it.title
            lines.append(f"- **{link}** — {it.company}{score}")
            meta = " · ".join(m for m in [it.location, it.salary] if m)
            if meta:
                lines.append(f"  - {meta}")
        return "\n".join(lines) + "\n"

    def to_rss(self, feed_title: str = "CareerAgent Jobs") -> str:
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0"><channel>',
            f"<title>{escape(feed_title)}</title>",
            "<description>Matched job postings from CareerAgent</description>",
        ]
        for it in self.items:
            title = f"{it.title} - {it.company}"
            parts.append("<item>")
            parts.append(f"<title>{escape(title)}</title>")
            if it.url:
                parts.append(f"<link>{escape(it.url)}</link>")
                parts.append(f"<guid>{escape(it.url)}</guid>")
            desc = f"{it.score:.0f}% match" if it.score is not None else ""
            parts.append(f"<description>{escape(desc)}</description>")
            parts.append("</item>")
        parts.append("</channel></rss>")
        return "".join(parts)


def build_digest(job_rows, limit: int = 10) -> Digest:
    """Top ``limit`` non-duplicate rows by match score."""
    candidates = [r for r in job_rows if not getattr(r, "is_duplicate", False)]
    candidates.sort(key=lambda r: r.match_score or 0, reverse=True)
    items = []
    for row in candidates[:limit]:
        salary = None
        if row.salary_min:
            cur = row.salary_currency or ""
            salary = f"{cur}{int(row.salary_min):,}"
            if row.salary_max and row.salary_max != row.salary_min:
                salary += f"-{int(row.salary_max):,}"
        items.append(
            DigestItem(
                title=row.title,
                company=row.company_name,
                url=row.url,
                score=row.match_score,
                location=row.location,
                salary=salary,
            )
        )
    return Digest(items=items)
