"""Phase 5 -- JSON Resume, ATS linter, PDF render, truthful tailoring."""

from __future__ import annotations

from core.matching.embeddings import HashingEmbedder
from core.models import CVProfile, Experience, JobPosting, Project
from core.resume import (
    FabricationError,
    assert_no_fabrication,
    from_json_resume,
    is_ats_friendly,
    lint,
    render_markdown,
    render_pdf,
    tailor_resume,
    to_json_resume,
)


def _sample_cv() -> CVProfile:
    return CVProfile(
        name="Ada Lovelace",
        email="ada@example.com",
        phone="+1-555-0100",
        linkedin="https://linkedin.com/in/ada",
        github="https://github.com/ada",
        summary="Engineer.",
        skills=["Python", "SQL", "Docker"],
        experiences=[
            Experience(
                title="Engineer",
                company="Analytical Engines",
                duration="2020-2024",
                achievements=["Cut latency by 40%"],
                technologies=["Python", "SQL"],
            )
        ],
        projects=[
            Project(
                name="Notes",
                description="A tool",
                technologies=["Python"],
                link="https://x.y",
            )
        ],
        education=["BSc Mathematics"],
    )


# --------------------------------------------------------------------------- #
# JSON Resume
# --------------------------------------------------------------------------- #


def test_json_resume_roundtrip():
    cv = _sample_cv()
    doc = to_json_resume(cv)
    assert doc["basics"]["name"] == "Ada Lovelace"
    assert {p["network"] for p in doc["basics"]["profiles"]} == {"LinkedIn", "GitHub"}
    back = from_json_resume(doc)
    assert back.name == cv.name
    assert back.email == cv.email
    assert back.skills == cv.skills
    assert back.experiences[0].company == "Analytical Engines"
    assert back.linkedin == cv.linkedin


# --------------------------------------------------------------------------- #
# ATS linter
# --------------------------------------------------------------------------- #


def test_ats_linter_flags_missing_email():
    cv = _sample_cv()
    cv.email = None
    issues = lint(cv)
    assert any(i.severity == "error" and "email" in i.message.lower() for i in issues)
    assert is_ats_friendly(cv) is False


def test_ats_linter_flags_emoji_and_tables():
    cv = _sample_cv()
    raw = "EXPERIENCE\nDid great work 🚀\n│ Skill │ Level │\n"
    issues = lint(cv, raw_text=raw)
    messages = " ".join(i.message for i in issues)
    assert "Emoji" in messages or "emoji" in messages.lower()
    assert "Table" in messages or "column" in messages.lower()


def test_ats_linter_clean_resume_passes():
    cv = _sample_cv()
    raw = "SUMMARY\nEngineer.\nEXPERIENCE\nEngineer, Analytical Engines\nSKILLS\nPython, SQL"
    assert is_ats_friendly(cv, raw_text=raw) is True


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def test_render_markdown_is_single_column_text():
    md = render_markdown(to_json_resume(_sample_cv()))
    assert "# Ada Lovelace" in md
    assert "## Experience" in md
    assert "Cut latency by 40%" in md


def test_render_pdf_is_valid_selectable_pdf():
    pdf = render_pdf(to_json_resume(_sample_cv()))
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500


def test_render_pdf_handles_unicode_summary():
    cv = _sample_cv()
    cv.summary = "Café-quality résumé — naïve façade"  # non-latin-1 dashes
    pdf = render_pdf(to_json_resume(cv))
    assert pdf.startswith(b"%PDF")


def test_render_pdf_roundtrips_expected_text(tmp_path):
    """Render, then extract the text back out with pdfplumber and confirm the
    real content -- not just PDF magic bytes -- made it onto the page."""
    import pdfplumber

    cv = _sample_cv()
    pdf_bytes = render_pdf(to_json_resume(cv))
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(pdf_bytes)

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert "Ada Lovelace" in text
    assert "ada@example.com" in text
    assert "Analytical Engines" in text
    assert "Cut latency by 40%" in text
    assert "Python" in text and "SQL" in text and "Docker" in text


# --------------------------------------------------------------------------- #
# Tailoring (truthful)
# --------------------------------------------------------------------------- #


def test_tailor_emphasizes_relevant_skills_first():
    cv = _sample_cv()  # skills: Python, SQL, Docker
    job = JobPosting(
        title="Data Engineer",
        company="Acme",
        description="SQL heavy role",
        tech_stack=["SQL", "Docker"],
    )
    tailored, report = tailor_resume(cv, job, embedder=HashingEmbedder())
    # SQL and Docker relevant -> ordered before Python.
    assert tailored.skills.index("SQL") < tailored.skills.index("Python")
    assert set(report.emphasized_skills) & {"SQL", "Docker"}


def test_tailor_never_fabricates():
    cv = _sample_cv()
    job = JobPosting(
        title="Rust Engineer",
        company="Acme",
        description="Rust systems",
        tech_stack=["Rust", "Kubernetes"],  # candidate has neither
    )
    tailored, report = tailor_resume(cv, job, embedder=HashingEmbedder())
    # No new skills invented; gaps reported instead.
    assert set(tailored.skills) == set(cv.skills)
    assert "rust" in report.gaps
    assert_no_fabrication(cv, tailored)  # must not raise


def test_assert_no_fabrication_catches_injected_skill():
    cv = _sample_cv()
    bad = cv.model_copy(update={"skills": cv.skills + ["Rust"]})
    try:
        assert_no_fabrication(cv, bad)
        raised = False
    except FabricationError:
        raised = True
    assert raised


def test_assert_no_fabrication_catches_recombined_title_and_company():
    """Company and title must match as a PAIR, not independently.

    Checking each field against its own set (all real companies, all real
    titles) would pass a resume claiming "Manager at Analytical Engines" for
    a candidate who was only ever "Engineer at Analytical Engines" and
    "Manager at Babbage Ltd" -- both fields are individually real, just
    never true together.
    """
    cv = _sample_cv()
    cv = cv.model_copy(
        update={
            "experiences": cv.experiences
            + [
                Experience(
                    title="Manager",
                    company="Babbage Ltd",
                    duration="2018-2020",
                    achievements=["Shipped the difference engine"],
                )
            ]
        }
    )
    recombined = cv.model_copy(
        update={
            "experiences": [cv.experiences[0].model_copy(update={"title": "Manager"})]
        }
    )
    try:
        assert_no_fabrication(cv, recombined)
        raised = False
    except FabricationError:
        raised = True
    assert raised
