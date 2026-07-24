"""
Render a JSON Resume to ATS-friendly outputs.

* :func:`render_markdown` -- plain, single-column Markdown.
* :func:`render_pdf` -- a text-based (selectable), single-column PDF via fpdf2,
  standard fonts and headings, no tables/columns/images.

The PDF deliberately avoids everything the ATS linter warns about.
"""

from __future__ import annotations

from typing import Any

from fpdf import FPDF

_STANDARD_FONT = "Helvetica"


def _latin1(text: str) -> str:
    """fpdf core fonts are latin-1; drop unsupported glyphs safely."""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def render_markdown(doc: dict[str, Any]) -> str:
    basics = doc.get("basics", {})
    lines: list[str] = []
    if basics.get("name"):
        lines.append(f"# {basics['name']}")
    contact = " | ".join(
        v for v in [basics.get("email"), basics.get("phone"), basics.get("url")] if v
    )
    if contact:
        lines.append(contact)
    if basics.get("summary"):
        lines += ["", "## Summary", basics["summary"]]

    if doc.get("skills"):
        lines += ["", "## Skills", ", ".join(s.get("name", "") for s in doc["skills"])]

    if doc.get("work"):
        lines += ["", "## Experience"]
        for w in doc["work"]:
            header = f"**{w.get('position', '')}**, {w.get('name', '')}"
            if w.get("endDate"):
                header += f" ({w['endDate']})"
            lines.append(header)
            for h in w.get("highlights", []):
                lines.append(f"- {h}")

    if doc.get("projects"):
        lines += ["", "## Projects"]
        for p in doc["projects"]:
            lines.append(f"**{p.get('name', '')}** - {p.get('description', '')}")
            if p.get("keywords"):
                lines.append(f"Tech: {', '.join(p['keywords'])}")

    if doc.get("education"):
        lines += ["", "## Education"]
        for e in doc["education"]:
            lines.append(f"- {e.get('institution', '')}")

    return "\n".join(lines) + "\n"


def render_pdf(doc: dict[str, Any]) -> bytes:
    """Render an ATS-clean, single-column, selectable-text PDF."""
    basics = doc.get("basics", {})
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 15, 18)

    def heading(text: str):
        pdf.ln(2)
        pdf.set_font(_STANDARD_FONT, "B", 13)
        pdf.cell(0, 8, _latin1(text.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(_STANDARD_FONT, "", 11)

    def body(text: str, bold: bool = False):
        pdf.set_font(_STANDARD_FONT, "B" if bold else "", 11)
        pdf.multi_cell(0, 6, _latin1(text), new_x="LMARGIN", new_y="NEXT")

    # Name + contact (in the body, not a header/footer, so ATS reads it).
    if basics.get("name"):
        pdf.set_font(_STANDARD_FONT, "B", 18)
        pdf.cell(0, 10, _latin1(basics["name"]), new_x="LMARGIN", new_y="NEXT")
    contact = " | ".join(
        v for v in [basics.get("email"), basics.get("phone"), basics.get("url")] if v
    )
    if contact:
        pdf.set_font(_STANDARD_FONT, "", 10)
        pdf.cell(0, 6, _latin1(contact), new_x="LMARGIN", new_y="NEXT")

    if basics.get("summary"):
        heading("Summary")
        body(basics["summary"])

    if doc.get("skills"):
        heading("Skills")
        body(", ".join(s.get("name", "") for s in doc["skills"]))

    if doc.get("work"):
        heading("Experience")
        for w in doc["work"]:
            title = f"{w.get('position', '')}, {w.get('name', '')}"
            if w.get("endDate"):
                title += f"  ({w['endDate']})"
            body(title, bold=True)
            for h in w.get("highlights", []):
                body(f"- {h}")
            pdf.ln(1)

    if doc.get("projects"):
        heading("Projects")
        for p in doc["projects"]:
            body(f"{p.get('name', '')} - {p.get('description', '')}", bold=True)
            if p.get("keywords"):
                body(f"Tech: {', '.join(p['keywords'])}")
            pdf.ln(1)

    if doc.get("education"):
        heading("Education")
        for e in doc["education"]:
            body(f"- {e.get('institution', '')}")

    out = pdf.output()
    return bytes(out)
