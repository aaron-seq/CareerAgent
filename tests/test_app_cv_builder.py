"""Model-free CV creation, review and exports through real Streamlit reruns."""

from pathlib import Path
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from core import facade
from core.models import CVProfile, EmailDraft, Experience, JobPosting, Project
from core.storage import LocalStorage

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(tmp_path, **state):
    app = AppTest.from_file(APP, default_timeout=30)
    values = {
        "page": "onboarding",
        "storage": LocalStorage(str(tmp_path / "storage")),
        **state,
    }
    for key, value in values.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    return app


def _field(app, label, kind="text_input"):
    return next(field for field in getattr(app, kind) if field.label == label)


def _button(app, label="Create CV and check readiness"):
    return next(button for button in app.button if button.label == label)


def _downloads(app):
    return [item.proto.label for item in app.get("download_button")]


def _profile():
    return CVProfile(
        name="Synthetic Candidate",
        email="candidate@example.test",
        phone="+44 123456789",
        linkedin="https://example.test/linkedin",
        github="https://example.test/github",
        portfolio="https://example.test/portfolio",
        summary="A real candidate summary.",
        skills=["Python", "SQL"],
        education=["Community course"],
        raw_text="Stale claim: Rust",
        experiences=[
            Experience(
                title="Volunteer",
                company="Community library",
                duration="2024–present",
                achievements=[
                    "Organized an accessible catalogue for library visitors."
                ],
                metrics=["Catalogued 120 books"],
                technologies=["Python", "SQL"],
            )
        ],
        projects=[
            Project(
                name="Catalogue",
                description="Built a searchable catalogue for library volunteers.",
                technologies=["Python"],
                link="https://example.test/catalogue",
                github="https://example.test/repository",
                impact="Helped volunteers locate books.",
            )
        ],
    )


def test_build_project_only_cv_without_model_and_download_all_formats(
    temp_db, tmp_path
):
    app = _app(tmp_path)
    assert app.session_state["llm_client"] is None
    assert _button(app).disabled is False
    _field(app, "Project entries", "number_input").set_value(1).run()
    _field(app, "Full name").set_value("Entry Level Candidate")
    _field(app, "CV email").set_value("candidate@example.test")
    _field(app, "Skills (one per line)", "text_area").set_value("Python\nSQL")
    _field(app, "Education or training (one per line)", "text_area").set_value(
        "Community programming course"
    )
    _field(app, "Project 1: Name").set_value("Library catalogue")
    _field(app, "Project 1: Factual description", "text_area").set_value(
        "Built a searchable catalogue for the local library."
    )
    _field(app, "Project 1: Technologies (one per line)", "text_area").set_value(
        "Python\nSQL"
    )
    _button(app).click().run()
    assert not app.exception
    profile = app.session_state["cv_profile"]
    assert profile.name == "Entry Level Candidate"
    assert profile.experiences == []
    assert profile.projects[0].name == "Library catalogue"
    assert profile.raw_text == ""
    assert facade.load_cv(app.session_state["cv_id"]) == profile
    assert (
        next(
            metric for metric in app.metric if metric.label == "Local CV readiness"
        ).value
        == "100/100"
    )
    assert {
        "Download ATS-clean PDF",
        "Download Markdown",
        "Download JSON Resume",
    } <= set(_downloads(app))
    assert any("not an external ATS score" in caption.value for caption in app.caption)


def test_edit_preserves_all_facts_and_retains_original_saved_profile(temp_db, tmp_path):
    original = _profile()
    old_id = facade.persist_cv(original)
    app = _app(tmp_path, cv_profile=original, cv_id=old_id)
    assert _field(app, "CV phone (optional)").value == original.phone
    assert (
        _field(
            app, "Role 1: Existing metrics (optional) (one per line)", "text_area"
        ).value
        == "Catalogued 120 books"
    )
    assert (
        _field(app, "Project 1: Repository URL (optional)").value
        == original.projects[0].github
    )
    _field(app, "Professional summary (optional)", "text_area").set_value(
        "Updated factual summary."
    )
    _field(app, "Skills (one per line)", "text_area").set_value("SQL")
    _button(app).click().run()
    assert not app.exception
    edited = app.session_state["cv_profile"]
    assert app.session_state["cv_id"] != old_id
    assert facade.load_cv(old_id) == original
    expected = original.model_copy(
        update={
            "summary": "Updated factual summary.",
            "skills": ["SQL"],
            "raw_text": "",
        }
    )
    assert edited == expected
    assert (
        _field(app, "Professional summary (optional)", "text_area").value
        == edited.summary
    )
    assert _field(app, "Skills (one per line)", "text_area").value == "SQL"


def test_blank_builder_validation_keeps_user_draft_and_no_active_cv(temp_db, tmp_path):
    app = _app(tmp_path)
    _button(app).click().run()
    assert any("Add your name" in item.value for item in app.error)
    _field(app, "Full name").set_value("Candidate")
    _field(app, "CV email").set_value("not-an-email")
    _field(app, "Skills (one per line)", "text_area").set_value("Python")
    _button(app).click().run()
    assert not app.exception
    assert app.session_state["cv_profile"] is None
    assert facade.saved_cv_profiles() == []
    assert any("valid email" in item.value for item in app.error)
    assert _field(app, "Full name").value == "Candidate"


def test_incomplete_role_does_not_replace_active_profile(temp_db, tmp_path):
    original = _profile()
    app = _app(tmp_path, cv_profile=original)
    _field(app, "Role 1: Actual dates or duration").set_value("")
    _button(app).click().run()
    assert not app.exception
    assert any("Role 1" in item.value for item in app.error)
    assert app.session_state["cv_profile"] == original


def test_counts_add_blank_rows_without_changing_existing_facts(temp_db, tmp_path):
    original = _profile()
    app = _app(tmp_path, cv_profile=original)
    _field(app, "Full name").set_value("Edited name").run()
    _field(app, "Project entries", "number_input").set_value(2).run()
    assert _field(app, "Full name").value == "Edited name"
    assert _field(app, "Project 1: Name").value == "Catalogue"
    assert _field(app, "Project 2: Name").value == ""
    assert app.session_state["cv_profile"] == original
    _button(app).click().run()
    assert not app.exception
    assert app.session_state["cv_profile"].name == "Edited name"
    assert app.session_state["cv_profile"].projects == original.projects


def test_database_failure_preserves_previous_cv_and_application_materials(
    temp_db, tmp_path, monkeypatch
):
    original = _profile()
    old_id = facade.persist_cv(original)
    draft = EmailDraft(subject="Existing", body="Reviewed material")
    app = _app(tmp_path, cv_profile=original, cv_id=old_id, current_draft=draft)
    monkeypatch.setattr(
        facade, "persist_cv", Mock(side_effect=OSError("Database unavailable"))
    )
    _field(app, "Full name").set_value("Unsaved change")
    _button(app).click().run()
    assert not app.exception
    assert app.session_state["cv_profile"] == original
    assert app.session_state["cv_id"] == old_id
    assert app.session_state["current_draft"] == draft
    assert facade.load_cv(old_id) == original
    assert any(
        "Your current CV and application materials are unchanged" in item.value
        for item in app.error
    )
    assert _field(app, "Full name").value == "Unsaved change"


def test_backup_failure_warns_after_success_and_across_reruns(
    temp_db, tmp_path, monkeypatch
):
    storage = LocalStorage(str(tmp_path / "backup"))
    monkeypatch.setattr(
        storage, "save_cv_profile", Mock(side_effect=OSError("Read only"))
    )
    app = _app(tmp_path, storage=storage)
    _field(app, "Full name").set_value("Saved Candidate")
    _field(app, "Skills (one per line)", "text_area").set_value("Python")
    _button(app).click().run()
    assert not app.exception
    assert facade.load_cv(app.session_state["cv_id"]).name == "Saved Candidate"
    assert any(
        "local backup could not be written" in item.value for item in app.warning
    )
    app.run()
    assert any(
        "local backup could not be written" in item.value for item in app.warning
    )


def test_selected_job_coverage_is_explained_without_llm(temp_db, tmp_path):
    app = _app(
        tmp_path,
        cv_profile=_profile(),
        selected_jobs=[
            JobPosting(
                title="Backend Engineer",
                company="Example",
                tech_stack=["Python", "Kubernetes"],
            )
        ],
    )
    _field(app, "Compare CV with a selected job", "selectbox").set_value(0).run()
    assert not app.exception
    assert app.session_state["llm_client"] is None
    assert (
        next(
            metric for metric in app.metric if metric.label == "Job skill coverage"
        ).value
        == "50%"
    )
    assert any("kubernetes" in item.value for item in app.markdown)
    assert any(
        "Reordering the same facts does not increase coverage" in item.value
        for item in app.caption
    )


def test_unsupported_pdf_keeps_markdown_and_json_available(temp_db, tmp_path):
    profile = _profile()
    profile.name = "候補者"
    app = _app(tmp_path, cv_profile=profile)
    assert not app.exception
    assert "Download ATS-clean PDF" not in _downloads(app)
    assert {"Download Markdown", "Download JSON Resume"} <= set(_downloads(app))
    assert any(
        "Markdown and JSON downloads remain available" in item.value
        for item in app.warning
    )


def test_tailored_resume_has_assessment_and_fallback_downloads(temp_db, tmp_path):
    profile = _profile()
    profile.name = "候補者"
    app = _app(
        tmp_path,
        page="draft",
        cv_profile=profile,
        selected_jobs=[
            JobPosting(
                title="Python Engineer", company="Example", tech_stack=["Python"]
            )
        ],
    )
    _button(app, "Tailor resume to this job").click().run()
    assert not app.exception
    assert "Download tailored ATS PDF" not in _downloads(app)
    assert {"Download tailored Markdown", "Download tailored JSON Resume"} <= set(
        _downloads(app)
    )
    assert (
        next(
            metric for metric in app.metric if metric.label == "Job skill coverage"
        ).value
        == "100%"
    )
    assert app.session_state["tailored"]["profile"].name == "候補者"


def test_oversized_saved_profile_is_never_silently_truncated(temp_db, tmp_path):
    profile = _profile()
    profile.projects = profile.projects * 31
    app = _app(tmp_path, cv_profile=profile)
    assert not app.exception
    assert app.session_state["cv_profile"] == profile
    assert any("avoid dropping your records" in item.value for item in app.warning)
    assert not any(
        button.label == "Create CV and check readiness" for button in app.button
    )
    assert "Download JSON Resume" in _downloads(app)


def test_zip_export_calls_complete_facade_export(temp_db, tmp_path, monkeypatch):
    archive = tmp_path / "complete.zip"
    archive.write_bytes(b"PK-complete-database-and-artifacts")
    exporter = Mock(return_value=str(archive))
    monkeypatch.setattr(facade, "export_all_data", exporter)
    app = _app(tmp_path, page="export")
    _button(app, "Export All Data (ZIP)").click().run()
    assert not app.exception
    exporter.assert_called_once_with(app.session_state["storage"])
    assert app.session_state["export_zip"] == archive.read_bytes()
