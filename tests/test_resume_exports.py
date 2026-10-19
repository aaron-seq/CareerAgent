"""Content-level CV export checks using synthetic candidate facts only."""

from __future__ import annotations

from io import BytesIO

import pdfplumber
import pytest
from pypdf import PdfReader

from core.models import CVProfile, Experience, Project
from core.resume import (
    from_json_resume,
    lint,
    render_markdown,
    render_pdf,
    to_json_resume,
)


def _complete_profile() -> CVProfile:
    return CVProfile(
        name="Łukasz Žurić",
        email="lukasz@example.test",
        phone="+44 1234 567890",
        portfolio="https://portfolio.example.test/lukasz",
        linkedin="https://www.linkedin.com/in/synthetic-lukasz",
        github="https://github.com/synthetic-lukasz",
        summary="Café systems engineer — Python, Δοκιμή and Кириллица.",
        skills=["Python", "SQL"],
        experiences=[
            Experience(
                title="Platform Engineer",
                company="Synthetic Systems",
                duration="2021–2025",
                achievements=["Built a reproducible deployment pipeline"],
                metrics=["Reduced build time by 25%"],
                technologies=["GitHub Actions", "Docker"],
            )
        ],
        projects=[
            Project(
                name="Synthetic Observatory",
                description="A service health dashboard",
                technologies=["OpenTelemetry", "Grafana"],
                link="https://observatory.example.test/demo",
                github="https://github.com/synthetic-lukasz/observatory",
                impact="Detected deployment regressions within 2 minutes",
            )
        ],
        education=["BSc Computer Science, Synthetic University"],
    )


def _all_facts(cv: CVProfile) -> list[str]:
    """Explicit expected facts, independent of renderer traversal/formatting."""
    contact_facts = []
    for fact in (
        cv.name,
        cv.email,
        cv.phone,
        cv.portfolio,
        cv.linkedin,
        cv.github,
        cv.summary,
    ):
        assert isinstance(fact, str) and fact, (
            "The complete fixture requires all contact fields."
        )
        contact_facts.append(fact)
    return contact_facts + [
        "Python",
        "SQL",
        "Platform Engineer",
        "Synthetic Systems",
        "2021–2025",
        "Built a reproducible deployment pipeline",
        "Reduced build time by 25%",
        "GitHub Actions",
        "Docker",
        "Synthetic Observatory",
        "A service health dashboard",
        "OpenTelemetry",
        "Grafana",
        "https://observatory.example.test/demo",
        "https://github.com/synthetic-lukasz/observatory",
        "Detected deployment regressions within 2 minutes",
        "BSc Computer Science, Synthetic University",
    ]


def test_markdown_preserves_contact_work_and_project_facts():
    cv = _complete_profile()
    markdown = render_markdown(to_json_resume(cv))

    for fact in _all_facts(cv):
        assert fact in markdown
    assert markdown.index("## Experience") < markdown.index("## Projects")


@pytest.mark.parametrize("reader", ["pdfplumber", "pypdf"])
def test_pdf_text_preserves_all_candidate_facts_and_supported_unicode(reader):
    cv = _complete_profile()
    data = render_pdf(to_json_resume(cv))
    if reader == "pdfplumber":
        with pdfplumber.open(BytesIO(data)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    else:
        pdf = PdfReader(BytesIO(data))
        text = "\n".join(page.extract_text() for page in pdf.pages)

    for fact in _all_facts(cv):
        assert fact in text
    assert "?" not in text
    assert not any("Table/column" in issue.message for issue in lint(cv, text))


def test_json_resume_preserves_secondary_repository_url():
    cv = _complete_profile()
    doc = to_json_resume(cv)

    assert doc["projects"][0]["url"] == cv.projects[0].link
    assert doc["projects"][0]["x-github"] == cv.projects[0].github
    restored = from_json_resume(doc)
    assert restored.projects[0].link == cv.projects[0].link
    assert restored.projects[0].github == cv.projects[0].github
    assert restored.projects[0].impact == cv.projects[0].impact


def test_pdf_wraps_long_contact_links_and_preserves_text_on_multiple_pages():
    cv = _complete_profile()
    long_url = "https://portfolio.example.test/" + "path" * 100 + "/terminal"
    cv.portfolio = long_url
    cv.summary = "\n".join(
        f"Verified synthetic achievement {index:03d}: shipped a tested release."
        for index in range(150)
    )
    data = render_pdf(to_json_resume(cv))

    with pdfplumber.open(BytesIO(data)) as pdf:
        assert len(pdf.pages) >= 3
        extracted = "\n".join(page.extract_text() or "" for page in pdf.pages)
        # Line wrapping may split long URLs; all URL characters must survive.
        assert long_url in "".join(extracted.split())
        assert "Verified synthetic achievement 000" in extracted
        assert "Verified synthetic achievement 149" in extracted
        assert "Synthetic University" in extracted
        for page in pdf.pages:
            assert all(
                45 <= char["x0"] < char["x1"] <= page.width - 45 for char in page.chars
            )


@pytest.mark.parametrize(
    "text, expected_error",
    [
        ("Engineer 🧪", "U+1F9EA"),
        ("研究工程师", "U+7814"),
        ("مهندس برمجيات", "script"),
        ("מהנדס", "script"),
        ("अभियंता", "script"),
    ],
)
def test_pdf_rejects_unsupported_text_with_markdown_fallback(text, expected_error):
    cv = _complete_profile()
    cv.summary = text
    doc = to_json_resume(cv)

    with pytest.raises(ValueError) as error:
        render_pdf(doc)
    assert expected_error in str(error.value)
    assert "Download Markdown" in str(error.value)
    assert text in render_markdown(doc)


def test_pdf_supports_decomposed_latin_accents_without_losing_the_name():
    cv = _complete_profile()
    cv.name = "Jose\u0301 Alvarez"
    data = render_pdf(to_json_resume(cv))

    reader = PdfReader(BytesIO(data))
    assert "José Alvarez" in reader.pages[0].extract_text()


@pytest.mark.parametrize("reader", ["pdfplumber", "pypdf"])
@pytest.mark.parametrize(
    "summary, expected",
    [
        ("Machine\tlearning engineer", "Machine learning engineer"),
        ("Python\rDocker services", "Python\nDocker services"),
        ("Python\r\nDocker services", "Python\nDocker services"),
    ],
)
def test_pdf_preserves_word_boundaries_for_tabs_and_carriage_returns(
    reader, summary, expected, caplog
):
    cv = _complete_profile()
    cv.summary = summary
    doc = to_json_resume(cv)
    caplog.set_level("WARNING")

    data = render_pdf(doc)
    if reader == "pdfplumber":
        with pdfplumber.open(BytesIO(data)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    else:
        pdf = PdfReader(BytesIO(data))
        text = "\n".join(page.extract_text() for page in pdf.pages)

    assert expected in text
    assert not any(
        "missing" in record.message.lower() and "glyph" in record.message.lower()
        for record in caplog.records
    )
    assert summary in render_markdown(doc)
