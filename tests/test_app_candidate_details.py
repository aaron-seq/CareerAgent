"""Saved application answers through real Streamlit callbacks and navigation."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from core import facade
from core.candidate import CandidateProfile
from core.models import CVProfile, JobPosting
from core.storage import LocalStorage

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(tmp_path, profile, cv_id, page="onboarding", **state):
    app = AppTest.from_file(APP, default_timeout=30)
    for key, value in {
        "page": page,
        "storage": LocalStorage(str(tmp_path / "storage")),
        "cv_profile": profile,
        "cv_id": cv_id,
        **state,
    }.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    return app


def _field(app, label, kind="text_input"):
    return next(field for field in getattr(app, kind) if field.label == label)


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _saved_cv(name="Synthetic Candidate"):
    profile = CVProfile(name=name, email="synthetic@example.test", skills=["Python"])
    return profile, facade.persist_cv(profile)


def _saved_answers(cv_id: int) -> CandidateProfile:
    candidate = facade.load_candidate_profile(cv_id)
    assert candidate is not None
    return candidate


def _export(app):
    app.button(key="nav_export").click().run()
    assert not app.exception
    return json.loads(app.json[0].value)


def _capture_downloads(monkeypatch):
    downloads = []
    real_download = st.download_button

    def capture(label, *args, **kwargs):
        if label == "Download autofill profile (JSON)":
            downloads.append(json.loads(kwargs["data"]))
        return real_download(label, *args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture)
    return downloads


def test_blank_editor_guesses_no_answers_and_false_zero_survive_save(temp_db, tmp_path):
    profile, cv_id = _saved_cv()
    app = _app(tmp_path, profile, cv_id)
    for label in (
        "Authorized to work in that country?",
        "Require sponsorship now or in the future in that country?",
        "Open to relocation?",
    ):
        assert _field(app, label, "selectbox").value is None
    for label in (
        "Expected pay to share on applications (optional)",
        "Minimum pay fallback (optional)",
        "Notice period in weeks (optional)",
        "Earliest start date or availability (optional)",
    ):
        assert _field(app, label).value == ""
    _button(app, "Save application details").click().run()
    assert not app.exception
    assert facade.load_candidate_profile(cv_id) == CandidateProfile()

    _field(app, "Country this work eligibility applies to (optional)").set_value(
        "India"
    )
    _field(app, "Authorized to work in that country?", "selectbox").set_value(False)
    _field(
        app, "Require sponsorship now or in the future in that country?", "selectbox"
    ).set_value(False)
    _field(app, "Open to relocation?", "selectbox").set_value(False)
    _field(app, "Expected pay to share on applications (optional)").set_value("0")
    _field(app, "Notice period in weeks (optional)").set_value("0")
    _button(app, "Save application details").click().run()
    assert not app.exception
    stored = facade.load_candidate_profile(cv_id)
    assert stored is not None
    assert stored.work_authorization.authorized is False
    assert stored.work_authorization.requires_sponsorship is False
    assert stored.compensation.target == 0
    assert stored.availability.notice_period_weeks == 0
    assert stored.preferences.open_to_relocation is False
    exported = _export(app)
    assert exported["answers"] == {
        "work_authorized": False,
        "requires_sponsorship": False,
        "work_authorization_country": "India",
        "salary_expectation": "USD 0 per year",
        "notice_period": "0 weeks",
        "willing_to_relocate": False,
    }
    assert any(
        "Expected pay in this download: USD 0 per year" in x.value for x in app.info
    )


def test_pending_details_survive_navigation_but_export_only_saved_values(
    temp_db, tmp_path
):
    profile, cv_id = _saved_cv()
    assert facade.save_candidate_profile(cv_id, {"location": "Saved region"})["ok"]
    app = _app(tmp_path, profile, cv_id)
    # Edit and navigation are sent in the same rerun: callbacks must retain it.
    _field(app, "Current city or region (optional)").set_value("Unsaved region")
    assert _export(app)["location"] == "Saved region"
    assert any("last saved answers" in x.value for x in app.warning)
    app.button(key="nav_onboarding").click().run()
    assert _field(app, "Current city or region (optional)").value == "Unsaved region"
    _button(app, "Save application details").click().run()
    assert not app.exception
    assert _export(app)["location"] == "Unsaved region"


def test_two_saved_cv_rows_keep_their_own_answers_drafts_and_consent(temp_db, tmp_path):
    first, first_id = _saved_cv("First Synthetic Candidate")
    second, second_id = _saved_cv("Second Synthetic Candidate")
    assert facade.save_candidate_profile(
        first_id,
        {
            "location": "First region",
            "demographics": {"pronouns": "they/them", "share_on_applications": True},
        },
    )["ok"]
    app = _app(tmp_path, first, first_id)
    _field(app, "Current city or region (optional)").set_value("Unsaved first").run()
    _field(app, "Saved profile", "selectbox").set_value(second_id)
    _button(app, "Use this CV").click().run()
    assert not app.exception
    assert app.session_state["cv_id"] == second_id
    assert _field(app, "Current city or region (optional)").value == ""
    assert not _field(
        app, "Include these voluntary answers in my autofill profile", "checkbox"
    ).value
    _field(app, "Current city or region (optional)").set_value("Second region")
    _button(app, "Save application details").click().run()
    assert _export(app)["location"] == "Second region"
    assert "answers" not in json.loads(app.json[0].value)
    app.button(key="nav_onboarding").click().run()
    _field(app, "Saved profile", "selectbox").set_value(first_id)
    _button(app, "Use this CV").click().run()
    assert _field(app, "Current city or region (optional)").value == "Unsaved first"
    assert _field(
        app, "Include these voluntary answers in my autofill profile", "checkbox"
    ).value
    exported = _export(app)
    assert exported["fullName"] == first.name
    assert exported["location"] == "First region"
    assert exported["answers"] == {"pronouns": "they/them", "share_demographics": True}
    assert _saved_answers(second_id).location == "Second region"


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("Expected pay to share on applications (optional)", "nan"),
        ("Expected pay to share on applications (optional)", "-1"),
        ("Expected pay to share on applications (optional)", "42.12345678901234567"),
        ("Notice period in weeks (optional)", "1.5"),
        ("Notice period in weeks (optional)", "105"),
        ("Pay currency (three-letter code)", "usd"),
        ("Other portfolio websites (one per line, optional)", "not a URL"),
    ],
)
def test_invalid_editor_values_keep_saved_answers_and_correction_text(
    temp_db, tmp_path, label, value
):
    profile, cv_id = _saved_cv()
    assert facade.save_candidate_profile(cv_id, {"location": "Original region"})["ok"]
    app = _app(tmp_path, profile, cv_id)
    kind = "text_area" if label.startswith("Other portfolio") else "text_input"
    _field(app, label, kind).set_value(value)
    _button(app, "Save application details").click().run()
    assert not app.exception
    assert app.error
    assert not any("Application details saved" in x.value for x in app.success)
    assert _field(app, label, kind).value == value
    assert _saved_answers(cv_id).location == "Original region"
    assert _saved_answers(cv_id).compensation.target is None


def test_failed_commit_keeps_draft_and_saved_answers_then_can_retry(
    temp_db, tmp_path, monkeypatch
):
    profile, cv_id = _saved_cv()
    assert facade.save_candidate_profile(cv_id, {"location": "Original region"})["ok"]
    app = _app(tmp_path, profile, cv_id)
    real_save = facade.save_candidate_profile
    monkeypatch.setattr(
        facade,
        "save_candidate_profile",
        Mock(side_effect=OSError("database unavailable")),
    )
    _field(app, "Current city or region (optional)").set_value("Changed region")
    _button(app, "Save application details").click().run()
    assert not app.exception
    assert any("Your edits remain here" in x.value for x in app.error)
    assert not any("Application details saved" in x.value for x in app.success)
    assert _field(app, "Current city or region (optional)").value == "Changed region"
    assert _saved_answers(cv_id).location == "Original region"
    monkeypatch.setattr(facade, "save_candidate_profile", real_save)
    _button(app, "Save application details").click().run()
    assert not app.exception
    assert _saved_answers(cv_id).location == "Changed region"


def test_clearing_fields_and_revoking_consent_removes_exports_preserving_hidden_answers(
    temp_db, tmp_path
):
    profile, cv_id = _saved_cv()
    assert facade.save_candidate_profile(
        cv_id,
        {
            "websites": ["https://synthetic.example.test"],
            "work_authorization": {"authorized": False},
            "compensation": {"minimum": 42.75, "period": "hour"},
            "availability": {"open_to_contract": False},
            "preferences": {"desired_titles": ["Engineer"]},
            "demographics": {"pronouns": "they/them", "share_on_applications": True},
        },
    )["ok"]
    app = _app(tmp_path, profile, cv_id)
    _field(app, "Authorized to work in that country?", "selectbox").set_value(None)
    _field(
        app, "Other portfolio websites (one per line, optional)", "text_area"
    ).set_value("")
    _field(app, "Minimum pay fallback (optional)").set_value("")
    _field(
        app, "Include these voluntary answers in my autofill profile", "checkbox"
    ).set_value(False)
    _button(app, "Save application details").click().run()
    assert not app.exception
    assert not app.error
    stored = _saved_answers(cv_id)
    assert stored.work_authorization.authorized is None
    assert stored.websites == []
    assert stored.compensation.minimum is None
    assert stored.availability.open_to_contract is False
    assert stored.preferences.desired_titles == ["Engineer"]
    assert stored.demographics.pronouns == "they/them"
    assert stored.demographics.share_on_applications is False
    assert "answers" not in _export(app)
    assert any(x.value == "Voluntary answers excluded." for x in app.caption)


def test_reset_reloads_saved_answers_and_new_cv_has_no_implicit_answer_copy(
    temp_db, tmp_path
):
    profile, cv_id = _saved_cv()
    assert facade.save_candidate_profile(cv_id, {"location": "Saved region"})["ok"]
    app = _app(tmp_path, profile, cv_id)
    _field(app, "Current city or region (optional)").set_value("Discard this")
    _button(app, "Reset unsaved changes").click().run()
    assert _field(app, "Current city or region (optional)").value == "Saved region"
    _field(app, "Full name").set_value("New Synthetic Snapshot")
    _button(app, "Create CV and check readiness").click().run()
    assert not app.exception
    new_id = app.session_state["cv_id"]
    assert new_id != cv_id
    assert facade.load_candidate_profile(new_id) == CandidateProfile()
    assert _saved_answers(cv_id).location == "Saved region"
    assert _field(app, "Current city or region (optional)").value == ""


def test_details_read_failure_blocks_editor_and_export_without_overwriting(
    temp_db, tmp_path, monkeypatch
):
    profile, cv_id = _saved_cv()
    assert facade.save_candidate_profile(cv_id, {"location": "Saved region"})["ok"]
    load = facade.load_candidate_profile
    save = Mock(side_effect=AssertionError("Never overwrite unreadable answers"))
    monkeypatch.setattr(
        facade, "load_candidate_profile", Mock(side_effect=ValueError("bad key"))
    )
    monkeypatch.setattr(facade, "save_candidate_profile", save)
    app = _app(tmp_path, profile, cv_id)
    assert any("could not be opened" in x.value for x in app.error)
    assert not any(x.label == "Save application details" for x in app.button)
    app.button(key="nav_export").click().run()
    assert not app.exception
    assert any("could not be opened" in x.value for x in app.error)
    assert not any(
        x.proto.label == "Download autofill profile (JSON)"
        for x in app.get("download_button")
    )
    save.assert_not_called()
    unchanged = load(cv_id)
    assert unchanged is not None
    assert unchanged.location == "Saved region"


@pytest.mark.parametrize(
    "failure", [ValueError("Unsupported PDF glyph"), OSError("renderer unavailable")]
)
def test_optional_pdf_failure_keeps_saved_answers_download_and_never_records_submission(
    temp_db, tmp_path, monkeypatch, failure
):
    profile, cv_id = _saved_cv()
    assert facade.save_candidate_profile(
        cv_id, {"compensation": {"minimum": 42.75, "period": "hour"}}
    )["ok"]
    downloads = _capture_downloads(monkeypatch)
    submitted = Mock(
        side_effect=AssertionError("Downloads never submit or mark applied")
    )
    monkeypatch.setattr(facade, "mark_applied", submitted)
    monkeypatch.setattr(facade, "resume_pdf", Mock(side_effect=failure))
    app = _app(tmp_path, profile, cv_id, "export")
    _field(app, "Include my CV PDF for resume upload", "checkbox").check().run()
    assert not app.exception
    assert any("answers only, without a PDF" in x.value for x in app.warning)
    assert downloads[-1]["answers"]["salary_expectation"] == "USD 42.75 per hour"
    assert "resume" not in downloads[-1]
    assert any("Minimum pay fallback in this download" in x.value for x in app.info)
    submitted.assert_not_called()


def test_embedded_pdf_download_uses_visible_active_cv_and_saved_answers(
    temp_db, tmp_path, monkeypatch
):
    profile, cv_id = _saved_cv("Visible Synthetic Candidate")
    assert facade.save_candidate_profile(cv_id, {"location": "Saved region"})["ok"]
    downloads = _capture_downloads(monkeypatch)
    render = Mock(return_value=b"%PDF-1.7\nSynthetic PDF")
    monkeypatch.setattr(facade, "resume_pdf", render)
    app = _app(tmp_path, profile, cv_id, "export")
    _field(app, "Include my CV PDF for resume upload", "checkbox").check().run()
    assert not app.exception
    render.assert_called_once_with(profile)
    assert downloads[-1]["fullName"] == profile.name
    assert downloads[-1]["location"] == "Saved region"
    assert downloads[-1]["resume"]["filename"] == "Visible_Synthetic_Candidate.pdf"


def test_unsaved_cv_export_does_not_borrow_another_rows_answers(temp_db, tmp_path):
    saved, cv_id = _saved_cv("Saved Synthetic Candidate")
    assert facade.save_candidate_profile(cv_id, {"location": "Do not copy"})["ok"]
    active = CVProfile(name="Unsaved Synthetic Candidate")
    app = _app(tmp_path, active, None, "export")
    exported = json.loads(app.json[0].value)
    assert exported["fullName"] == active.name
    assert exported["location"] == ""
    assert "answers" not in exported
    _button(app, "Edit application details").click().run()
    assert not app.exception
    assert _button(app, "Save this CV")
    assert facade.load_cv(cv_id) == saved


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://[invalid",
        "https://jobs.lever.co:bad/example/1",
        "https://user:password@jobs.lever.co/example/1",
        "https://jobs.lever.co/example/\n1",
    ],
)
def test_pipeline_and_draft_never_render_invalid_stored_application_links(
    temp_db, tmp_path, monkeypatch, url
):
    profile, cv_id = _saved_cv()
    job_id = facade.persist_manual_job(
        JobPosting(title="Engineer", company="Synthetic Employer", url=url)
    )
    assert facade.add_to_pipeline(job_id, cv_id)["ok"]
    submitted = Mock(side_effect=AssertionError("Preparing is not submission"))
    monkeypatch.setattr(facade, "mark_applied", submitted)
    app = _app(tmp_path, profile, cv_id, "pipeline")
    assert not app.get("link_button")
    assert any("not a web address" in x.value for x in app.caption)
    app.button(key=f"prepare_{job_id}").click().run()
    assert not app.exception
    assert app.session_state["page"] == "draft"
    assert not app.get("link_button")
    assert any("not a web address" in x.value for x in app.caption)
    assert len(facade.pipeline_board()["saved"]) == 1
    _button(app, "Prepare browser autofill profile").click().run()
    assert not app.exception
    assert app.session_state["page"] == "export"
    assert len(facade.pipeline_board()["saved"]) == 1
    submitted.assert_not_called()


def test_draft_handoff_uses_persisted_supported_target_and_visible_cv(
    temp_db, tmp_path
):
    profile, cv_id = _saved_cv()
    job = JobPosting(
        title="Engineer",
        company="Synthetic Employer",
        url="https://jobs.lever.co/synthetic/1",
    )
    job_id = facade.persist_manual_job(job)
    app = _app(
        tmp_path,
        profile,
        cv_id,
        "draft",
        selected_jobs=[job],
        selected_job_refs={facade.workspace_job_key(job): job_id},
    )
    links = app.get("link_button")
    assert len(links) == 1
    assert links[0].proto.label == "Open application"
    assert links[0].proto.url == job.url
    assert any("Review before submitting" in x.value for x in app.caption)
    assert any(f"saved CV #{cv_id}" in x.value for x in app.caption)
    assert not any(facade.pipeline_board().values())
