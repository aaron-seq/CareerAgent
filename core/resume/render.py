"""Render truthful, single-column Markdown, PDF and escaped XeLaTeX CVs.

PDF fonts are bundled for offline use. Coverage is deliberately bounded:
unsupported glyphs and scripts requiring shaping/bidirectional layout raise an
explicit error so users can download the lossless Markdown version instead.
"""

from __future__ import annotations

import re
import unicodedata
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fpdf import FPDF
from fpdf.fonts import TTFFont

_FONT_FAMILY = "CareerAgentSans"
_FONT_DIRECTORY = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# These writing systems need shaping or bidirectional layout beyond the plain
# left-to-right PDF renderer. Font coverage alone cannot establish correctness.
_SHAPING_RANGES = (
    (0x0900, 0x109F),  # Indic, Thai, Lao, Tibetan and Myanmar
    (0x1780, 0x18AF),  # Khmer and Mongolian
    (0x1900, 0x1CFF),  # Additional Brahmic scripts and combining extensions
    (0xA800, 0xABFF),  # Additional Indic/Southeast Asian scripts
    (0x11000, 0x11FFF),  # Supplementary Brahmic scripts
)


def _contact_lines(basics: dict[str, Any]) -> list[str]:
    lines = [
        f"{label}: {basics[key]}"
        for label, key in (("Email", "email"), ("Phone", "phone"), ("Portfolio", "url"))
        if basics.get(key)
    ]
    for profile in basics.get("profiles", []):
        if profile.get("url"):
            lines.append(f"{profile.get('network') or 'Profile'}: {profile['url']}")
    return lines


def _sections(doc: dict[str, Any]) -> list[tuple[str, list[tuple[str, bool]]]]:
    """Share export content so Markdown and PDF retain the same facts."""
    sections: list[tuple[str, list[tuple[str, bool]]]] = []
    basics = doc.get("basics", {})
    if basics.get("summary"):
        sections.append(("Summary", [(basics["summary"], False)]))

    if doc.get("skills"):
        sections.append(
            ("Skills", [(", ".join(s.get("name", "") for s in doc["skills"]), False)])
        )

    if doc.get("work"):
        lines = []
        for work in doc["work"]:
            title = f"{work.get('position', '')}, {work.get('name', '')}"
            if work.get("endDate"):
                title += f" ({work['endDate']})"
            lines.append((title, True))
            lines.extend(
                (f"- {highlight}", False) for highlight in work.get("highlights", [])
            )
            if work.get("keywords"):
                lines.append((f"Tech: {', '.join(work['keywords'])}", False))
        sections.append(("Experience", lines))

    if doc.get("projects"):
        lines = []
        for project in doc["projects"]:
            lines.append(
                (f"{project.get('name', '')} - {project.get('description', '')}", True)
            )
            if project.get("keywords"):
                lines.append((f"Tech: {', '.join(project['keywords'])}", False))
            seen_urls: set[str] = set()
            for label, url in (
                ("Project", project.get("url")),
                ("GitHub", project.get("x-github")),
            ):
                if url and url not in seen_urls:
                    lines.append((f"{label}: {url}", False))
                    seen_urls.add(url)
            lines.extend(
                (f"- {highlight}", False) for highlight in project.get("highlights", [])
            )
        sections.append(("Projects", lines))

    if doc.get("education"):
        sections.append(
            (
                "Education",
                [
                    (f"- {item.get('institution', '')}", False)
                    for item in doc["education"]
                ],
            )
        )
    return sections


def render_markdown(doc: dict[str, Any]) -> str:
    """Preserve CV text and links in a plain, single-column Markdown file."""
    basics = doc.get("basics", {})
    lines: list[str] = []
    if basics.get("name"):
        lines.append(f"# {basics['name']}")
    lines.extend(_contact_lines(basics))
    for title, content in _sections(doc):
        lines.extend(["", f"## {title}"])
        lines.extend(f"**{text}**" if bold else text for text, bold in content)
    return "\n".join(lines) + "\n"


_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "%": r"\%",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}


def _latex_text(text: str) -> str:
    """Encode candidate text without ever interpreting it as TeX source."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    for character in text:
        if character != "\n" and unicodedata.category(character) in {"Cc", "Cs"}:
            raise ValueError(
                "LaTeX export does not support control character "
                f"U+{ord(character):04X}. Remove it before exporting."
            )
    # A single pass prevents braces/backslashes in replacement commands from
    # being escaped again, while protecting every candidate-controlled field.
    parts = []
    for token in re.split(r"(\s+)", text):
        # Ordinary TeX cannot wrap a long URL/identifier. Add optional breaks
        # between whole escaped characters; never split an escape command.
        chunks = (
            [token[i : i + 24] for i in range(0, len(token), 24)]
            if len(token) > 24 and not token.isspace()
            else [token]
        )
        parts.append(
            r"\allowbreak{}".join(
                "".join(_LATEX_ESCAPES.get(char, char) for char in chunk)
                for chunk in chunks
            )
        )
    return "".join(parts).replace("\n", "\\par\n")


def render_latex(doc: dict[str, Any]) -> str:
    """Render single-column XeLaTeX source with the same facts as PDF/Markdown.

    Compile beside the bundled ``fonts/`` directory, included by
    :func:`render_latex_project`. This generates text only: it runs no compiler
    and makes no network request. The PDF renderer remains the app preview;
    XeLaTeX pagination can differ and its output still needs human review.
    """
    lines = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[margin=18mm,top=15mm,bottom=15mm]{geometry}",
        r"\usepackage{fontspec}",
        # Keep literal word spaces and separate glyphs in extracted PDF text.
        r"\setmainfont{DejaVuSans.ttf}[Path=fonts/,BoldFont=DejaVuSans-Bold.ttf,Kerning=Off,Ligatures=NoCommon]",
        r"\XeTeXinterwordspaceshaping=2",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\parskip}{4pt}",
        r"\setlength{\emergencystretch}{3em}",
        r"\pagestyle{empty}",
        r"\raggedright",
        r"\begin{document}",
    ]
    basics = doc.get("basics", {})
    contacts = _contact_lines(basics)
    sections = _sections(doc)
    if basics.get("name"):
        lines.append(
            r"{\fontsize{18}{22}\selectfont\bfseries "
            + _latex_text(basics["name"])
            + r"}\par"
        )
    for contact in contacts:
        lines.append(r"{\small " + _latex_text(contact) + r"}\par")
    for title, content in sections:
        lines.extend(["", r"\section*{" + _latex_text(title) + "}"])
        for text, bold in content:
            escaped = _latex_text(text)
            lines.append(
                (r"{\bfseries " + escaped + "}" if bold else escaped) + r"\par"
            )
    if not basics.get("name") and not contacts and not sections:
        lines.append(r"\null")  # even an empty document produces a blank PDF page
    lines.extend([r"\end{document}", ""])
    return "\n".join(lines)


def render_latex_project(doc: dict[str, Any]) -> bytes:
    """Package fixed project paths and licensed fonts for local/Overleaf use."""
    instructions = (
        "# Resume LaTeX project\n\n"
        "Upload this ZIP as a new Overleaf project:\n"
        "https://docs.overleaf.com/managing-projects-and-files/uploading-a-project\n\n"
        "Choose XeLaTeX as the compiler and main.tex as the main document. "
        "Keep the fonts/ directory beside main.tex; font notices are in "
        "fonts/LICENSE.txt. No extra font download is needed.\n\n"
        "These files contain readable personal data. Review them before "
        "sharing; uploading to Overleaf shares them with that service. "
        "To keep them local, compile main.tex with XeLaTeX on your machine.\n\n"
        "The source preserves your supplied facts in one column. Review the "
        "compiled PDF: its pagination can differ from CareerAgent's PDF "
        "preview, and no ATS ranking or hiring outcome is guaranteed. "
        "The bundled fonts cover Latin, Greek and Cyrillic text. For other "
        "scripts, choose suitable fonts and layout before using the PDF.\n"
    )
    files = [("main.tex", render_latex(doc).encode("utf-8"))]
    files.extend(
        ("fonts/" + filename, (_FONT_DIRECTORY / filename).read_bytes())
        for filename in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "LICENSE.txt")
    )
    files.append(("README.md", instructions.encode("utf-8")))
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for filename, data in files:
            info = ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def _pdf_text(text: str, supported: dict[int, str]) -> str:
    # NFC composes ordinary accents when possible without changing their text.
    text = unicodedata.normalize("NFC", text)
    # fpdf2 treats CR and tabs as unsupported glyphs and otherwise drops them,
    # which can join distinct words. Preserve their whitespace meaning.
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    for character in text:
        codepoint = ord(character)
        if (
            unicodedata.bidirectional(character) in {"R", "AL", "AN"}
            or unicodedata.category(character).startswith("M")
            or any(start <= codepoint <= end for start, end in _SHAPING_RANGES)
        ):
            raise ValueError(
                "PDF export cannot reliably lay out this script or combining marks. "
                "Download Markdown to preserve your text."
            )
        if character != "\n" and codepoint not in supported:
            raise ValueError(
                f"PDF export does not support character U+{codepoint:04X}. "
                "Download Markdown to preserve your text."
            )
    return text


def render_pdf(doc: dict[str, Any]) -> bytes:
    """Render a selectable, single-column PDF; reject unsupported text explicitly.

    Bundled DejaVu Sans covers Latin, Greek and Cyrillic text, among other
    glyphs. Complex-script shaping and right-to-left layout are not supported.
    Markdown export remains available for text outside this PDF coverage.
    """
    basics = doc.get("basics", {})
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 15, 18)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font(_FONT_FAMILY, "", str(_FONT_DIRECTORY / "DejaVuSans.ttf"))
    pdf.add_font(_FONT_FAMILY, "B", str(_FONT_DIRECTORY / "DejaVuSans-Bold.ttf"))
    pdf.add_page()

    def body(text: str, bold: bool = False, size: int = 11, height: int = 6) -> None:
        pdf.set_font(_FONT_FAMILY, "B" if bold else "", size)
        # fpdf2 exposes the loaded TrueType font's Unicode-to-glyph map. Check
        # it before output: fpdf2 otherwise logs missing glyphs and drops them.
        font = pdf.current_font
        assert isinstance(font, TTFFont)
        text = _pdf_text(text, font.cmap)
        pdf.multi_cell(0, height, text, new_x="LMARGIN", new_y="NEXT")

    if basics.get("name"):
        body(basics["name"], bold=True, size=18, height=10)
    for contact in _contact_lines(basics):
        body(contact, size=10)

    for title, content in _sections(doc):
        pdf.ln(2)
        body(title.upper(), bold=True, size=13, height=8)
        for text, bold in content:
            body(text, bold=bold)

    return bytes(pdf.output())
