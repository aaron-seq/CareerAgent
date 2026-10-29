"""Draft previews must show current facts without changing the saved workspace."""

from io import BytesIO
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from core import facade
from core.models import CVProfile, EmailDraft
from tests.test_app_cv_builder import _app, _button, _downloads, _field, _profile


def _preview(app):
    _button(app, "Update draft preview").click().run()
    assert not app.exception
    return app.session_state["cv_editor_preview"]


def _pdf_text(data):
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def test_preview_before_save_exports_current_facts_without_model_or_database_write(
    temp_db, tmp_path
):
    app = _app(tmp_path)
    _field(app, "Full name").set_value("Draft Candidate")
    _field(app, "CV email").set_value("draft@example.test")
    _field(app, "Skills (one per line)", "text_area").set_value("Python\nSQL")
    preview = _preview(app)
    assert app.session_state["cv_profile"] is None
    assert app.session_state["llm_client"] is None
    assert facade.saved_cv_profiles() == []
    assert "Draft Candidate" in _pdf_text(preview["pdf"])
    assert "draft@example.test" in _pdf_text(preview["pdf"])
    assert {"Download draft PDF", "Download draft Overleaf ZIP"} <= set(_downloads(app))
    with ZipFile(BytesIO(preview["project"])) as archive:
        assert "Draft Candidate" in archive.read("main.tex").decode("utf-8")


def test_preview_does_not_activate_edits_or_invalidate_application_materials(
    temp_db, tmp_path
):
    original = _profile()
    cv_id = facade.persist_cv(original)
    material = EmailDraft(subject="Reviewed", body="Preserve this material")
    app = _app(tmp_path, cv_profile=original, cv_id=cv_id, current_draft=material)
    _field(app, "Full name").set_value("Unsaved Candidate")
    preview = _preview(app)
    assert "Unsaved Candidate" in _pdf_text(preview["pdf"])
    assert app.session_state["cv_profile"] == original
    assert app.session_state["cv_id"] == cv_id
    assert facade.load_cv(cv_id) == original
    assert app.session_state["current_draft"] == material
    assert len(facade.saved_cv_profiles()) == 1


def test_edits_hide_outdated_preview_and_its_downloads(temp_db, tmp_path):
    app = _app(tmp_path, cv_profile=_profile())
    _preview(app)
    _field(app, "Full name").set_value("Newer edit").run()
    assert "Download draft PDF" not in _downloads(app)
    assert "Download draft Overleaf ZIP" not in _downloads(app)
    assert any("out of date" in item.value for item in app.info)
    preview = _preview(app)
    assert "Newer edit" in _pdf_text(preview["pdf"])


def test_invalid_draft_clears_previous_preview_but_preserves_saved_cv(
    temp_db, tmp_path
):
    original = _profile()
    app = _app(tmp_path, cv_profile=original)
    _preview(app)
    _field(app, "CV email").set_value("invalid-email")
    _button(app, "Update draft preview").click().run()
    assert not app.exception
    assert app.session_state["cv_editor_preview"] is None
    assert app.session_state["cv_profile"] == original
    assert "Download draft PDF" not in _downloads(app)
    assert any("valid email" in item.value for item in app.error)
    assert _field(app, "CV email").value == "invalid-email"


def test_unsupported_pdf_keeps_lossless_draft_exports(temp_db, tmp_path):
    app = _app(tmp_path, cv_profile=_profile())
    _field(app, "Full name").set_value("候補者")
    preview = _preview(app)
    assert preview["pdf"] is None
    assert "Download draft PDF" not in _downloads(app)
    assert {
        "Download draft Markdown",
        "Download draft JSON Resume",
        "Download draft Overleaf ZIP",
    } <= set(_downloads(app))
    assert "候補者" in preview["latex"]
    assert any("PDF" in item.value for item in app.warning)


def test_profile_switch_does_not_expose_previous_draft_preview(temp_db, tmp_path):
    app = _app(tmp_path, cv_profile=_profile(), cv_id=1)
    _preview(app)
    app.session_state["cv_profile"] = CVProfile(name="Different CV", skills=["Rust"])
    app.session_state["cv_id"] = 2
    app.run()
    assert not app.exception
    assert "Download draft PDF" not in _downloads(app)
    assert app.session_state["cv_editor_preview"] is None
    assert _field(app, "Full name").value == "Different CV"


def test_failed_save_keeps_current_draft_preview_and_previous_profile(
    temp_db, tmp_path, monkeypatch
):
    original = _profile()
    app = _app(tmp_path, cv_profile=original)
    _field(app, "Full name").set_value("Unsaved correction")
    preview = _preview(app)
    monkeypatch.setattr(facade, "persist_cv", Mock(side_effect=OSError("Unavailable")))
    _button(app).click().run()
    assert not app.exception
    assert app.session_state["cv_profile"] == original
    assert "Unsaved correction" in _pdf_text(preview["pdf"])
    assert "Download draft PDF" in _downloads(app)


def test_source_asset_failure_keeps_saved_cv_and_other_exports(
    temp_db, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        facade, "resume_latex_project", Mock(side_effect=OSError("Missing font"))
    )
    app = _app(tmp_path, cv_profile=_profile())
    assert {
        "Download ATS-clean PDF",
        "Download Markdown",
        "Download JSON Resume",
    } <= set(_downloads(app))
    assert "Download Overleaf project" not in _downloads(app)
    assert any("LaTeX export is unavailable" in item.value for item in app.warning)


@pytest.mark.parametrize("tailored", [False, True])
def test_missing_shared_fonts_keep_text_downloads(
    temp_db, tmp_path, monkeypatch, tailored
):
    from core.models import JobPosting

    monkeypatch.setattr(facade, "resume_pdf", Mock(side_effect=OSError("Missing font")))
    monkeypatch.setattr(
        facade, "resume_latex_project", Mock(side_effect=OSError("Missing font"))
    )
    state = {"cv_profile": _profile()}
    if tailored:
        state.update(
            page="draft",
            selected_jobs=[JobPosting(title="Engineer", company="Example")],
        )
    app = _app(tmp_path, **state)
    if tailored:
        _button(app, "Tailor resume to this job").click().run()
    assert not app.exception
    prefix = "tailored " if tailored else ""
    assert {
        f"Download {prefix}Markdown",
        f"Download {prefix}JSON Resume",
    } <= set(_downloads(app))


def test_successful_save_clears_draft_preview(temp_db, tmp_path):
    app = _app(tmp_path, cv_profile=_profile())
    _preview(app)
    _button(app).click().run()
    assert not app.exception
    assert app.session_state["cv_editor_preview"] is None
    assert "Download draft PDF" not in _downloads(app)
