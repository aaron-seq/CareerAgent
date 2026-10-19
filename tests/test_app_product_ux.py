"""Task-first product journeys through real Streamlit reruns, without AI/network."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from core import facade
from core.models import ContactCandidate, CVProfile, JobPosting
from core.storage import LocalStorage

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(tmp_path, page="onboarding", **state):
    app = AppTest.from_file(APP, default_timeout=30)
    for key, value in {
        "page": page,
        "storage": LocalStorage(str(tmp_path / "storage")),
        **state,
    }.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    return app


def _field(app, label, kind="text_input"):
    return next(item for item in getattr(app, kind) if item.label == label)


def _button(app, label):
    return next(item for item in app.button if item.label == label)


def _contacts(tmp_path, **state):
    return _app(
        tmp_path,
        "contacts",
        selected_jobs=[
            JobPosting(
                title="Engineer",
                company="Example",
                url="https://jobs.lever.co/example/posting",
            )
        ],
        **state,
    )


def test_first_run_builder_is_usable_and_ai_is_optional(temp_db, tmp_path):
    app = _app(tmp_path)
    assert _field(app, "Full name")
    assert _button(app, "Create CV and check readiness").disabled is False
    assert not any("Not Connected" in warning.value for warning in app.warning)
    assert any("Optional · off" in caption.value for caption in app.caption)
    assert (
        next(
            expander for expander in app.expander if expander.label == "AI settings"
        ).proto.expanded
        is False
    )
    assert _button(app, "Parse CV").disabled is True
    assert [tab.label for tab in app.tabs] == [
        "Build or edit a CV",
        "Import PDF or text",
    ]
    assert _field(app, "Target Roles (one per line)", "text_area").value == ""
    restored = facade.restore_workspace(app.session_state["storage"])
    assert restored is not None
    assert restored["state"]["preferences"]["seniority"] == "Any"
    assert not app.session_state["workspace_save_warning"]


def test_editing_one_cv_entry_path_keeps_other_unsaved_facts(temp_db, tmp_path):
    app = _app(tmp_path)
    _field(app, "Full name").set_value("Unsaved Synthetic Candidate").run()
    _field(app, "Skills (one per line)", "text_area").set_value("Python\nSQL").run()
    app.run()
    assert _button(app, "Parse CV").disabled is True
    _field(app, "Paste CV text", "text_area").set_value(
        "Original unsaved CV text."
    ).run()
    app.run()
    assert _field(app, "Full name").value == "Unsaved Synthetic Candidate"
    assert _field(app, "Skills (one per line)", "text_area").value == "Python\nSQL"
    app.run()
    assert (
        _field(app, "Paste CV text", "text_area").value == "Original unsaved CV text."
    )
    assert app.session_state["cv_profile"] is None
    assert facade.saved_cv_profiles() == []


def test_active_cv_review_and_downloads_remain_available_alongside_import(
    temp_db, tmp_path
):
    profile = CVProfile(name="Synthetic Candidate", skills=["Python"])
    app = _app(tmp_path, cv_profile=profile)
    app.run()
    assert not app.exception
    assert any(item.value == "CV Profile" for item in app.subheader)
    labels = {item.proto.label for item in app.get("download_button")}
    assert {
        "Download ATS-clean PDF",
        "Download Markdown",
        "Download JSON Resume",
    } <= labels
    assert app.session_state["cv_profile"] == profile


@pytest.mark.parametrize("address", ["not-an-email", "", ".person@example.test"])
def test_invalid_manual_contact_has_error_and_does_not_mutate_workspace(
    temp_db, tmp_path, address, monkeypatch
):
    no_dns = Mock(side_effect=AssertionError("Manual inputs do not need DNS"))
    monkeypatch.setattr("core.outreach.verification._default_resolver", no_dns)
    app = _contacts(tmp_path)
    _field(app, "Name").set_value("Synthetic Recruiter")
    _field(app, "Email").set_value(address)
    _button(app, "Add").click().run()
    assert not app.exception
    assert any("valid email address" in item.value for item in app.error)
    assert app.session_state["found_contacts"] == {}
    assert _field(app, "Name").value == "Synthetic Recruiter"
    no_dns.assert_not_called()


def test_manual_contact_has_provenance_can_be_deduplicated_and_removed(
    temp_db, tmp_path
):
    app = _contacts(tmp_path)
    _field(app, "Name").set_value("Synthetic Recruiter")
    _field(app, "Email").set_value("person@example.test")
    _button(app, "Add").click().run()
    assert not app.exception
    assert len(app.session_state["found_contacts"]["Example"]) == 1
    assert any(item.value == "User provided · unverified" for item in app.caption)
    assert not any(
        "Verified" in item.value or "100%" in item.value for item in app.caption
    )
    _field(app, "Email").set_value("PERSON@example.test")
    _button(app, "Add").click().run()
    assert len(app.session_state["found_contacts"]["Example"]) == 1
    assert any("already in your contacts" in item.value for item in app.info)
    app.button(key="remove_contact_0_0").click().run()
    assert app.session_state["found_contacts"]["Example"] == []


def test_old_confirmed_contact_is_not_displayed_as_independently_verified(
    temp_db, tmp_path
):
    app = _contacts(
        tmp_path,
        found_contacts={
            "Example": [
                ContactCandidate(
                    name="Legacy Person",
                    email="person@example.test",
                    email_confidence="confirmed",
                    source="manual",
                    confidence_score=1,
                )
            ]
        },
    )
    assert any(item.value == "User provided · unverified" for item in app.caption)
    assert not any(
        "Verified" in item.value or "100%" in item.value for item in app.caption
    )
    assert not any("[High]" in item.value for item in app.markdown)


def test_patterns_never_infer_company_domain_and_validate_before_generation(
    temp_db, tmp_path
):
    app = _contacts(tmp_path)
    assert _field(app, "Employer email domain").value == ""
    _field(app, "First Name").set_value("Jane")
    _field(app, "Last Name").set_value("Smith")
    _button(app, "Generate Permutations").click().run()
    assert any("known email domain" in item.value for item in app.error)
    assert app.session_state["found_contacts"] == {}
    _field(app, "Employer email domain").set_value("example.test")
    _button(app, "Generate Permutations").click().run()
    assert not app.exception
    contacts = app.session_state["found_contacts"]["Example"]
    assert len(contacts) == 3
    assert all(contact.email.endswith("@example.test") for contact in contacts)
    assert any(item.value == "Generated pattern · unverified" for item in app.caption)
    _button(app, "Generate Permutations").click().run()
    assert len(app.session_state["found_contacts"]["Example"]) == 3


def test_selected_job_can_go_directly_to_materials_without_contacts(temp_db, tmp_path):
    profile = CVProfile(name="Synthetic Candidate", skills=["Python"])
    app = _app(
        tmp_path,
        "discovery",
        cv_profile=profile,
        selected_jobs=[JobPosting(title="Engineer", company="Example")],
    )
    _button(app, "Next: Prepare application materials").click().run()
    assert not app.exception
    assert app.session_state["page"] == "draft"
    assert _button(app, "Tailor resume to this job").disabled is False
    assert app.session_state["found_contacts"] == {}


def test_neutral_preference_and_existing_explicit_seniority_both_restore(
    temp_db, tmp_path
):
    from core.workspace import (
        WorkspacePreferences,
        WorkspaceSnapshot,
        load_workspace,
        save_workspace,
    )

    storage = LocalStorage(str(tmp_path / "neutral-preferences"))
    for level in ("Any", "Senior", "Junior"):
        save_workspace(
            storage,
            WorkspaceSnapshot(
                preferences=WorkspacePreferences.model_validate({"seniority": level})
            ),
        )
        restored = load_workspace(storage)
        assert restored is not None
        assert restored.preferences is not None
        assert restored.preferences.seniority == level


def test_pending_builder_facts_survive_sidebar_navigation_without_saving(
    temp_db, tmp_path
):
    from core.workspace import load_workspace

    app = _app(tmp_path)
    _field(app, "Project entries", "number_input").set_value(1).run()
    # Blur edits and sidebar navigation can arrive together. Value callbacks
    # must retain them even though the builder page will not execute this run.
    _field(app, "Full name").set_value("Unsaved Synthetic Candidate")
    _field(app, "Skills (one per line)", "text_area").set_value("Python\nSQL")
    _field(app, "Project 1: Name").set_value("Unsaved library project")
    _field(app, "Project 1: Factual description", "text_area").set_value(
        "Built a real catalogue."
    )
    app.button(key="nav_discovery").click().run()
    assert not app.exception
    app.button(key="nav_onboarding").click().run()
    assert not app.exception
    assert _field(app, "Full name").value == "Unsaved Synthetic Candidate"
    assert _field(app, "Skills (one per line)", "text_area").value == "Python\nSQL"
    assert _field(app, "Project entries", "number_input").value == 1
    assert _field(app, "Project 1: Name").value == "Unsaved library project"
    assert (
        _field(app, "Project 1: Factual description", "text_area").value
        == "Built a real catalogue."
    )
    assert app.session_state["cv_profile"] is None
    assert facade.saved_cv_profiles() == []
    snapshot = load_workspace(app.session_state["storage"])
    assert snapshot is not None
    assert snapshot.cv_id is None
    assert "Unsaved Synthetic Candidate" not in snapshot.model_dump_json()


def test_deliberately_restoring_another_profile_starts_its_own_editor_scope(
    temp_db, tmp_path
):
    original = CVProfile(name="Original Candidate", skills=["Python"])
    original_id = facade.persist_cv(original)
    replacement = CVProfile(name="Replacement Candidate", skills=["SQL"])
    replacement_id = facade.persist_cv(replacement)
    app = _app(tmp_path, cv_profile=original, cv_id=original_id)
    _field(app, "Full name").set_value("Unsaved original edit").run()
    old_scope = app.session_state["cv_builder_draft"]["scope"]
    _field(app, "Saved profile", "selectbox").set_value(replacement_id)
    _button(app, "Use this CV").click().run()
    assert not app.exception
    assert _field(app, "Full name").value == replacement.name
    assert _field(app, "Skills (one per line)", "text_area").value == "SQL"
    assert app.session_state["cv_builder_draft"]["scope"] != old_scope
    assert app.session_state["cv_builder_draft"]["values"] == {}
    assert facade.load_cv(original_id) == original
