"""Synthetic Streamlit journeys: restore, discover, prepare, review, export."""

from pathlib import Path
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from core import facade
from core.db import get_session
from core.db.repository import JobRepository
from core.llm import LocalLLMClient
from core.models import CVProfile, EmailDraft, JobPosting
from core.storage import LocalStorage

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(tmp_path, page="onboarding", **state):
    app = AppTest.from_file(APP, default_timeout=30)
    values = {
        "page": page,
        "storage": LocalStorage(str(tmp_path / "storage")),
        **state,
    }
    for key, value in values.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    return app


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _input(app, label):
    return next(field for field in app.text_input if field.label == label)


def _area(app, label):
    return next(field for field in app.text_area if field.label == label)


def _draft_studio(tmp_path, **state):
    return _app(
        tmp_path,
        "draft",
        llm_client=LocalLLMClient(),
        cv_profile=CVProfile(name="Synthetic Candidate", email="cv@example.test"),
        selected_jobs=[
            JobPosting(title="Engineer", company="Alpha"),
            JobPosting(title="Engineer", company="Beta"),
        ],
        current_draft=EmailDraft(
            subject="Alpha subject", body="Alpha body", company="Alpha"
        ),
        **state,
    )


def test_switch_jobs_isolates_drafts_and_restores_edited_content(temp_db, tmp_path):
    app = _draft_studio(tmp_path)
    _input(app, "Subject").set_value("Edited Alpha subject").run()
    _area(app, "Body").set_value("Edited Alpha body").run()
    _input(app, "Recipient Email").set_value("alpha@example.test").run()

    app.selectbox(key="draft_job_selection").set_value(1).run()
    assert not app.exception
    assert app.session_state["current_draft"] is None
    assert not any(field.label == "Subject" for field in app.text_input)
    assert _input(app, "Recipient Email").value == ""

    app.selectbox(key="draft_job_selection").set_value(0).run()
    assert not app.exception
    assert _input(app, "Subject").value == "Edited Alpha subject"
    assert _area(app, "Body").value == "Edited Alpha body"
    assert _input(app, "Recipient Email").value == "alpha@example.test"
    assert app.session_state["current_draft"].company == "Alpha"


def test_new_generation_replaces_existing_editor_values(temp_db, tmp_path, monkeypatch):
    generate = Mock(
        return_value=EmailDraft(
            subject="Fresh subject", body="Fresh body", company="Alpha"
        )
    )
    monkeypatch.setattr(
        "core.personalization.PersonalizationEngine.generate_email", generate
    )
    app = _draft_studio(tmp_path)
    _area(app, "Body").set_value("Old manually edited text").run()
    _button(app, "Generate Email").click().run()
    assert not app.exception
    assert _input(app, "Subject").value == "Fresh subject"
    assert _area(app, "Body").value == "Fresh body"
    assert app.session_state["current_draft"].body == "Fresh body"


def test_regeneration_replaces_existing_editor_values(temp_db, tmp_path, monkeypatch):
    regenerate = Mock(
        return_value=EmailDraft(
            subject="New angle", body="Regenerated body", company="Alpha"
        )
    )
    monkeypatch.setattr(
        "core.personalization.PersonalizationEngine.regenerate_email_with_angle",
        regenerate,
    )
    app = _draft_studio(tmp_path)
    _button(app, "Regenerate").click().run()
    assert not app.exception
    assert _input(app, "Subject").value == "New angle"
    assert _area(app, "Body").value == "Regenerated body"


def test_cover_and_tailored_resume_stay_with_their_job(temp_db, tmp_path, monkeypatch):
    covers = Mock(
        side_effect=[
            {
                "letter": "Alpha letter",
                "word_count": 2,
                "cited_metrics": [],
                "gaps": [],
            },
            {
                "letter": "Fresh Alpha letter",
                "word_count": 3,
                "cited_metrics": [],
                "gaps": [],
            },
        ]
    )
    monkeypatch.setattr(facade, "cover_letter_for_job", covers)
    app = _draft_studio(tmp_path)
    _button(app, "Draft cover letter").click().run()
    _area(app, "Letter").set_value("Edited Alpha letter").run()
    _button(app, "Tailor resume to this job").click().run()
    alpha_tailored = app.session_state["tailored"]

    app.selectbox(key="draft_job_selection").set_value(1).run()
    assert not app.exception
    assert app.session_state["cover"] is None
    assert app.session_state["tailored"] is None
    assert not any(field.label == "Letter" for field in app.text_area)
    app.selectbox(key="draft_job_selection").set_value(0).run()
    assert not app.exception
    assert _area(app, "Letter").value == "Edited Alpha letter"
    assert app.session_state["tailored"] == alpha_tailored

    _button(app, "Draft cover letter").click().run()
    assert not app.exception
    assert _area(app, "Letter").value == "Fresh Alpha letter"


def test_restore_saved_cv_without_connecting_a_model(temp_db, tmp_path):
    profile = CVProfile(name="Saved Synthetic Candidate", skills=["Python"])
    profile_id = facade.persist_cv(profile)
    app = _app(tmp_path)
    assert app.session_state["llm_client"] is None
    app.radio(key="onboarding_mode").set_value("Upload a CV (uses AI)").run()
    assert _button(app, "Read my CV").disabled
    _button(app, "Use this profile").click().run()
    assert not app.exception
    assert app.session_state["cv_id"] == profile_id
    assert app.session_state["cv_profile"] == profile
    assert any(heading.value == "Application answers" for heading in app.subheader)
    assert _button(app, "Next: find jobs")


def test_disconnected_onboarding_keeps_profile_review_visible(temp_db, tmp_path):
    app = _app(tmp_path, cv_profile=CVProfile(name="Synthetic Candidate"))
    assert not app.exception
    assert any(heading.value == "Application answers" for heading in app.subheader)
    assert any(element.proto.label == "PDF" for element in app.get("download_button"))


def test_profile_restore_failure_keeps_existing_profile(temp_db, tmp_path, monkeypatch):
    facade.persist_cv(CVProfile(name="Saved Candidate"))
    monkeypatch.setattr(
        facade, "load_cv", Mock(side_effect=ValueError("Invalid token"))
    )
    current = CVProfile(name="Current Candidate")
    app = _app(tmp_path, cv_profile=current)
    _button(app, "Use this profile").click().run()
    assert not app.exception
    assert app.session_state["cv_profile"] == current
    assert any("original encryption key" in error.value for error in app.error)


def test_restoring_another_cv_discards_previous_generated_material(temp_db, tmp_path):
    facade.persist_cv(CVProfile(name="New Candidate"))
    app = _app(
        tmp_path,
        cv_profile=CVProfile(name="Old Candidate"),
        current_draft=EmailDraft(
            subject="Old profile", body="Old body", company="Alpha"
        ),
        draft_workspaces={"old-job": {"cover": {"letter": "Old candidate's letter"}}},
    )
    _button(app, "Use this profile").click().run()
    assert not app.exception
    assert app.session_state["current_draft"] is None
    assert app.session_state["draft_workspaces"] == {}
    assert app.session_state["cv_profile"].name == "New Candidate"


def test_job_discovery_accepts_pasted_job_before_cv_or_llm(temp_db, tmp_path):
    app = _app(tmp_path, "discovery")
    next(radio for radio in app.radio if radio.label == "Discovery mode").set_value(
        "Paste Job Description"
    ).run()
    _area(app, "Paste Job Description").set_value(
        "Build reliable Python services."
    ).run()
    _input(app, "Job Title").set_value("Backend Engineer").run()
    _input(app, "Company Name").set_value("Synthetic Company").run()
    _button(app, "Add Job").click().run()
    assert not app.exception
    assert app.session_state["llm_client"] is None
    assert app.session_state["cv_profile"] is None
    assert app.session_state["selected_jobs"][0].company == "Synthetic Company"


def test_api_discovery_shows_partial_result_warning_and_pipeline_handoff(
    temp_db, tmp_path, monkeypatch
):
    discover = Mock(
        return_value={
            "stored": 2,
            "method": "ats",
            "ats_type": "smartrecruiters",
            "warnings": ["More jobs remain; resume at offset 100."],
        }
    )
    refresh = Mock()
    monkeypatch.setattr(facade, "discover_from_url", discover)
    monkeypatch.setattr(facade, "refresh_matches", refresh)
    app = _app(tmp_path, "discovery")
    _input(app, "Careers page or job board URL").set_value(
        "https://jobs.example.test"
    ).run()
    _button(app, "Discover jobs").click().run()
    assert not app.exception
    assert any("resume at offset 100" in warning.value for warning in app.warning)
    refresh.assert_not_called()
    _button(app, "View saved jobs in Pipeline").click().run()
    assert not app.exception
    assert app.session_state["page"] == "pipeline"


def test_pipeline_prepares_api_job_and_tailors_without_a_model(temp_db, tmp_path):
    job = JobPosting(
        title="Python Engineer",
        company="Synthetic Company",
        description="Python services",
        url="https://example.test/jobs/1",
    )
    with get_session() as session:
        job_id = (
            JobRepository(session)
            .upsert(job, source="remoteok", source_id="synthetic-job")
            .id
        )
    app = _app(
        tmp_path, "pipeline", cv_profile=CVProfile(name="Candidate", skills=["Python"])
    )
    assert any("remoteok" in caption.value for caption in app.caption)
    assert any("RemoteOK" in caption.value for caption in app.caption)
    app.button(key=f"prepare_{job_id}").click().run()
    assert not app.exception
    assert app.session_state["page"] == "draft"
    assert app.session_state["selected_jobs"] == [job]
    assert _button(app, "Generate Email").disabled
    assert _button(app, "Draft cover letter").disabled
    assert not _button(app, "Tailor resume to this job").disabled
    _button(app, "Tailor resume to this job").click().run()
    assert not app.exception
    assert app.session_state["tailored"]["profile"].skills == ["Python"]


def test_pipeline_prepare_without_cv_guides_to_onboarding(temp_db, tmp_path):
    with get_session() as session:
        job_id = (
            JobRepository(session)
            .upsert(
                JobPosting(title="Engineer", company="Synthetic Company"),
                source="manual",
            )
            .id
        )
    app = _app(tmp_path, "pipeline")
    app.button(key=f"prepare_{job_id}").click().run()
    assert not app.exception
    assert app.session_state["page"] == "onboarding"
    assert app.session_state["selected_jobs"][0].company == "Synthetic Company"


def test_withdrawn_and_duplicate_titled_applications_remain_selectable(
    temp_db, tmp_path, monkeypatch
):
    cards = [
        {
            "application_id": 1,
            "title": "Engineer",
            "company": "Synthetic",
            "notes": "First application",
        },
        {
            "application_id": 2,
            "title": "Engineer",
            "company": "Synthetic",
            "notes": "Second application",
        },
    ]
    monkeypatch.setattr(
        facade,
        "pipeline_board",
        lambda: {
            "saved": cards,
            "withdrawn": [
                {
                    "application_id": 3,
                    "title": "Withdrawn Engineer",
                    "company": "Synthetic",
                    "notes": "Archived",
                }
            ],
        },
    )
    app = _app(tmp_path, "pipeline")
    application = next(box for box in app.selectbox if box.label == "Application")
    assert len(application.options) == 3
    application.set_value(2).run()
    assert not app.exception
    assert _area(app, "Notes").value == "Second application"
    next(box for box in app.selectbox if box.label == "Application").set_value(3).run()
    assert not app.exception
    assert _area(app, "Notes").value == "Archived"
    assert any(expander.label == "Withdrawn (1)" for expander in app.expander)


def test_zip_export_is_downloadable_in_the_browser(temp_db, tmp_path):
    app = _app(tmp_path, "export")
    _button(app, "Export All Data (ZIP)").click().run()
    assert not app.exception
    assert app.session_state["export_zip"].startswith(b"PK")
    assert any(
        element.proto.label == "Download all data (ZIP)"
        for element in app.get("download_button")
    )


def test_profile_can_be_typed_in_without_a_model(temp_db, tmp_path):
    """Real-user blocker: no model meant no way to create a profile at all."""
    app = _app(tmp_path)
    assert app.session_state["llm_client"] is None
    assert app.radio(key="onboarding_mode").value == "Type it in"
    _input(app, "Full name *").set_value("Synthetic Candidate")
    _input(app, "Email *").set_value("not-an-email")
    _area(app, "Skills").set_value("Python, SQL")
    _button(app, "Save my profile").click().run()
    assert not app.exception
    assert app.session_state["cv_profile"] is None
    assert any("valid email" in item.value for item in app.markdown)

    _input(app, "Email *").set_value("candidate@example.test")
    _button(app, "Save my profile").click().run()
    assert not app.exception
    saved = app.session_state["cv_profile"]
    assert saved.skills == ["Python", "SQL"]
    assert facade.load_cv(app.session_state["cv_id"]) == saved
    assert any("Profile saved" in item.value for item in app.success)

    # Survives navigation, and the answers form is offered next.
    app.button(key="nav_pipeline").click().run()
    app.button(key="nav_onboarding").click().run()
    assert not app.exception
    assert _input(app, "Full name *").value == "Synthetic Candidate"
    assert any(heading.value == "Application answers" for heading in app.subheader)


def test_application_answers_keep_unknown_as_unknown(temp_db, tmp_path):
    cv_id = facade.persist_cv(CVProfile(name="Synthetic", email="s@example.test"))
    app = _app(tmp_path, cv_profile=facade.load_cv(cv_id), cv_id=cv_id)
    # Form values reach the app together with the submit click, as in a browser.
    app.selectbox(key="ans_sponsor").set_value("No")
    _button(app, "Save answers").click().run()
    assert not app.exception
    answers = facade.load_candidate_profile(cv_id)
    assert answers.work_authorization.requires_sponsorship is False
    # Untouched yes/no questions stay unknown rather than defaulting to No.
    assert answers.work_authorization.authorized is None
    assert answers.preferences.open_to_relocation is None


def test_removing_selected_job_resets_invalid_draft_selection(temp_db, tmp_path):
    app = _draft_studio(tmp_path)
    app.selectbox(key="draft_job_selection").set_value(1).run()
    app.button(key="nav_discovery").click().run()
    app.button(key="remove_1").click().run()
    app.button(key="nav_draft").click().run()
    assert not app.exception
    assert app.session_state["draft_job_selection"] == 0
    assert app.selectbox(key="draft_job_selection").options == ["Engineer at Alpha"]


def test_restored_cv_automatically_updates_previous_candidate_scores(temp_db, tmp_path):
    first = CVProfile(name="Python Candidate", skills=["Python"])
    second = CVProfile(name="Rust Candidate", skills=["Rust"])
    facade.persist_manual_job(
        JobPosting(
            title="Python Engineer",
            company="Synthetic",
            description="Build Python services",
            requirements=["Python"],
            tech_stack=["Python"],
        )
    )
    facade.refresh_matches(first)
    first_score = facade.top_jobs()[0]["score"]
    facade.persist_cv(second)
    app = _app(tmp_path, cv_profile=first)
    _button(app, "Use this profile").click().run()
    assert not app.exception
    assert app.session_state["cv_profile"] == second
    assert facade.top_jobs()[0]["score"] < first_score
    assert not app.session_state["match_refresh_warning"]


def test_profile_score_failure_notice_survives_reruns(temp_db, tmp_path, monkeypatch):
    facade.persist_cv(CVProfile(name="Saved Candidate"))
    monkeypatch.setattr(
        facade, "refresh_matches", Mock(side_effect=OSError("Synthetic failure"))
    )
    app = _app(tmp_path)
    _button(app, "Use this profile").click().run()
    assert not app.exception
    assert app.session_state["cv_profile"].name == "Saved Candidate"
    assert any("could not be updated" in warning.value for warning in app.warning)
    app.button(key="nav_pipeline").click().run()
    assert not app.exception
    assert any("could not be updated" in warning.value for warning in app.warning)


def test_pasted_job_is_available_in_pipeline(temp_db, tmp_path):
    app = _app(tmp_path, "discovery")
    next(radio for radio in app.radio if radio.label == "Discovery mode").set_value(
        "Paste Job Description"
    ).run()
    _area(app, "Paste Job Description").set_value(
        "Build reliable Python services."
    ).run()
    _input(app, "Job Title").set_value("Backend Engineer").run()
    _input(app, "Company Name").set_value("Synthetic Company").run()
    _button(app, "Add Job").click().run()
    _button(app, "Add Job").click().run()
    _button(app, "View saved jobs in Pipeline").click().run()
    assert not app.exception
    assert any(
        "Backend Engineer - Synthetic Company" in expander.label
        for expander in app.expander
    )
    assert len(facade.top_jobs()) == 1
    assert len(app.session_state["selected_jobs"]) == 1


def test_pasted_job_database_failure_retains_job_and_visible_notice(
    temp_db, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        facade, "persist_manual_job", Mock(side_effect=OSError("Synthetic failure"))
    )
    app = _app(tmp_path, "discovery")
    next(radio for radio in app.radio if radio.label == "Discovery mode").set_value(
        "Paste Job Description"
    ).run()
    _area(app, "Paste Job Description").set_value(
        "Build reliable Python services."
    ).run()
    _input(app, "Job Title").set_value("Backend Engineer").run()
    _input(app, "Company Name").set_value("Synthetic Company").run()
    _button(app, "Add Job").click().run()
    assert not app.exception
    assert len(app.session_state["selected_jobs"]) == 1
    assert any(
        "could not be saved or scored" in warning.value for warning in app.warning
    )


def test_existing_email_can_be_reviewed_and_saved_without_a_model(temp_db, tmp_path):
    app = _draft_studio(tmp_path)
    app.session_state["llm_client"] = None
    app.run()
    _input(app, "Recipient Email").set_value("reviewed@example.test").run()
    _area(app, "Body").set_value("Manually reviewed body").run()
    assert _button(app, "Generate Email").disabled
    _button(app, "Save Local").click().run()
    assert not app.exception
    storage = app.session_state["storage"]
    saved = storage.load_email_draft(storage.list_email_drafts()[0])
    assert saved.body == "Manually reviewed body"
    assert saved.recipient_email == "reviewed@example.test"


def test_smartrecruiters_import_can_continue_a_partial_board(
    temp_db, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    ingest = Mock(
        return_value=SimpleNamespace(
            fetched=3,
            upserted=3,
            errors=[],
            warnings=["More jobs remain; resume at offset 103."],
        )
    )
    monkeypatch.setattr(facade, "ingest_ats", ingest)
    app = _app(tmp_path, "pipeline")
    next(box for box in app.selectbox if box.label == "ATS").set_value(
        "smartrecruiters"
    ).run()
    _input(app, "Board slug").set_value("SyntheticBoard").run()
    next(
        field
        for field in app.number_input
        if field.label == "Skip jobs already imported"
    ).set_value(100).run()
    next(
        field for field in app.number_input if field.label == "Jobs per import"
    ).set_value(3).run()
    _button(app, "Ingest").click().run()
    assert not app.exception
    ingest.assert_called_once_with(
        "smartrecruiters", "SyntheticBoard", "", offset=100, max_jobs=3
    )
    assert any("resume at offset 103" in warning.value for warning in app.warning)
