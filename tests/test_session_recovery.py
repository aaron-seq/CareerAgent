"""Independent browser sessions recover narrow choices without reviving authority."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from core import facade
from core.db import get_session
from core.db.crypto import _get_key, encrypt_payload
from core.db.tables import CVProfileRow, JobPostingRow
from core.models import ContactCandidate, CVProfile, JobPosting
from core.storage import LocalStorage
from core.workspace import (
    MAX_WORKSPACE_BYTES,
    WorkspaceSnapshot,
    load_workspace,
    reset_workspace,
    save_workspace,
)

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app(storage, **state):
    app = AppTest.from_file(APP, default_timeout=30)
    app.session_state["storage"] = storage
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    return app


def _field(app, label, kind="text_input"):
    return next(value for value in getattr(app, kind) if value.label == label)


def _button(app, label):
    return next(value for value in app.button if value.label == label)


def _state(job, cv_id=None):
    return {
        "cv_id": cv_id,
        "selected_jobs": [job],
        "found_contacts": {
            job.company: [
                ContactCandidate(
                    name="Synthetic Recruiter", email="recruiter@example.test"
                )
            ]
        },
        "preferences": {
            "target_roles": ["Data Engineer"],
            "target_locations": ["Remote"],
            "industries": ["AI/ML"],
            "seniority": "Mid-level",
        },
        "page": "contacts",
    }


def test_private_encrypted_roundtrip_and_explicit_export(tmp_path):
    storage = LocalStorage(str(tmp_path))
    snapshot = WorkspaceSnapshot(
        found_contacts={
            "Example": [{"name": "Private Recruiter", "email": "private@example.test"}]
        }
    )
    save_workspace(storage, snapshot)
    raw = (tmp_path / "workspace.json").read_text()
    assert "Private Recruiter" not in raw
    assert "private@example.test" not in raw
    assert os.stat(tmp_path / "workspace.json").st_mode & 0o777 == 0o600
    assert load_workspace(storage) == snapshot
    with ZipFile(storage.create_export_zip()) as archive:
        assert "workspace.json" in archive.namelist()
        assert (
            json.loads(archive.read("workspace.json"))["found_contacts"]["Example"][0][
                "email"
            ]
            == "private@example.test"
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"version": True},
        {"version": "1"},
        {"version": 2},
        {"cv_id": True},
        {"cv_id": -1},
        {"selected_job_ids": [False]},
        {"selected_job_ids": [1, 1]},
        {"selected_job_ids": list(range(1, 202))},
        {"page": "secret"},
        {"llm_client": "secret"},
        {"preferences": {"seniority": "made-up"}},
        {"found_contacts": {"X": [{"name": "X", "confidence_score": float("nan")}]}},
        {"found_contacts": {"X": [{"name": "X", "unknown_secret": "x"}]}},
        {"found_contacts": {"X": [{"name": "X"}] * 101}},
        {"preferences": {"target_roles": ["x" * 501]}},
    ],
)
def test_invalid_snapshot_shape_is_rejected(payload):
    with pytest.raises(ValidationError):
        WorkspaceSnapshot.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"format": "careeragent.fernet.v1"},
        {"format": "plain", "ciphertext": "x"},
        {"version": 1},
    ],
)
def test_corrupt_or_plaintext_workspace_is_never_overwritten(tmp_path, payload):
    storage = LocalStorage(str(tmp_path))
    path = tmp_path / "workspace.json"
    original = json.dumps(payload)
    path.write_text(original)
    with pytest.raises((ValueError, TypeError)):
        save_workspace(storage, WorkspaceSnapshot())
    assert path.read_text() == original


def test_oversized_file_is_rejected_without_decrypting(tmp_path):
    storage = LocalStorage(str(tmp_path))
    path = tmp_path / "workspace.json"
    path.write_bytes(b"x" * (MAX_WORKSPACE_BYTES + 1))
    with pytest.raises(ValueError, match="size limit"):
        load_workspace(storage)


def test_wrong_key_refuses_read_and_overwrite(tmp_path, monkeypatch):
    storage = LocalStorage(str(tmp_path))
    save_workspace(storage, WorkspaceSnapshot(page="contacts"))
    original = (tmp_path / "workspace.json").read_bytes()
    monkeypatch.setenv("CAREERAGENT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _get_key.cache_clear()
    try:
        with pytest.raises(InvalidToken):
            load_workspace(storage)
        with pytest.raises(InvalidToken):
            save_workspace(storage, WorkspaceSnapshot())
        assert (tmp_path / "workspace.json").read_bytes() == original
    finally:
        _get_key.cache_clear()


def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(
    tmp_path, monkeypatch
):
    storage = LocalStorage(str(tmp_path))
    save_workspace(storage, WorkspaceSnapshot(page="contacts"))
    original = (tmp_path / "workspace.json").read_bytes()
    monkeypatch.setattr(
        "core.workspace.os.replace", Mock(side_effect=OSError("disk unavailable"))
    )
    with pytest.raises(OSError):
        save_workspace(storage, WorkspaceSnapshot(page="draft"))
    assert (tmp_path / "workspace.json").read_bytes() == original
    assert list(tmp_path.glob(".workspace-*.part")) == []


def test_symlink_workspace_is_not_read_or_reset(tmp_path):
    storage = LocalStorage(str(tmp_path / "storage"))
    external = tmp_path / "other.json"
    external.write_text("untouched")
    (Path(storage.storage_dir) / "workspace.json").symlink_to(external)
    for operation in (load_workspace, reset_workspace):
        with pytest.raises(ValueError, match="regular"):
            operation(storage)
    assert external.read_text() == "untouched"


def test_facade_restores_database_facts_and_warns_for_deleted_references(
    temp_db, tmp_path
):
    storage = LocalStorage(str(tmp_path))
    job = JobPosting(
        title="Engineer", company="Example", description="Original factual source"
    )
    job_id = facade.persist_manual_job(job)
    cv_id = facade.persist_cv(CVProfile(name="Synthetic Candidate"))
    facade.save_workspace(storage, _state(job, cv_id))
    with get_session() as session:
        row = session.get(JobPostingRow, job_id)
        row.description = "Updated factual source"
        session.add(row)
    assert (
        facade.restore_workspace(storage)["state"]["selected_jobs"][0].description
        == "Updated factual source"
    )
    with get_session() as session:
        session.delete(session.get(JobPostingRow, job_id))
        session.delete(session.get(CVProfileRow, cv_id))
    recovered = facade.restore_workspace(storage)
    assert recovered["state"]["cv_profile"] is None
    assert recovered["state"]["cv_id"] is None
    assert recovered["state"]["selected_jobs"] == []
    assert len(recovered["notices"]) == 2


def test_unsaved_job_cannot_replace_valid_snapshot(temp_db, tmp_path):
    storage = LocalStorage(str(tmp_path))
    save_workspace(storage, WorkspaceSnapshot(page="draft"))
    with pytest.raises(ValueError, match="database first"):
        facade.save_workspace(
            storage, _state(JobPosting(title="Unsaved", company="Example"))
        )
    assert load_workspace(storage).page == "draft"


def test_new_browser_restores_manual_job_contact_cv_preferences_without_model(
    temp_db, tmp_path, monkeypatch
):
    storage = LocalStorage(str(tmp_path))
    cv = CVProfile(name="Synthetic Candidate", skills=["Python"])
    cv_id = facade.persist_cv(cv)
    app = _app(storage)
    _button(app, "Use this CV").click().run()
    _field(app, "Target Roles (one per line)", "text_area").set_value(
        "Data Engineer"
    ).run()
    _field(app, "Target Locations (one per line)", "text_area").set_value(
        "Remote only"
    ).run()
    app.session_state["page"] = "discovery"
    app.run()
    _field(app, "Discovery mode", "radio").set_value("Paste Job Description").run()
    _field(app, "Paste Job Description", "text_area").set_value(
        "Build factual Python tools."
    )
    _field(app, "Job Title").set_value("Engineer")
    _field(app, "Company Name").set_value("Example")
    _button(app, "Add Job").click().run()
    app.session_state["page"] = "contacts"
    app.run()
    _field(app, "Name").set_value("Synthetic Recruiter")
    _field(app, "Email").set_value("recruiter@example.test")
    _field(app, "Role").set_value("Recruiter")
    _button(app, "Add").click().run()
    assert not app.exception
    # Fresh AppTest, same durable storage: no injected CV/job/contact/preferences.
    no_refresh = Mock(side_effect=AssertionError("Recovery must not refresh matches"))
    monkeypatch.setattr(facade, "refresh_matches", no_refresh)
    restored = _app(storage)
    assert restored.session_state["cv_id"] == cv_id
    assert any("Re-score matches" in warning.value for warning in restored.warning)
    assert restored.session_state["cv_profile"] == cv
    assert (
        restored.session_state["selected_jobs"][0].description
        == "Build factual Python tools."
    )
    assert (
        restored.session_state["found_contacts"]["Example"][0].email
        == "recruiter@example.test"
    )
    assert restored.session_state["preferences"]["target_roles"] == ["Data Engineer"]
    assert restored.session_state["preferences"]["target_locations"] == ["Remote only"]
    assert restored.session_state["page"] == "contacts"
    assert restored.session_state["llm_client"] is None
    assert restored.session_state["gmail_client"] is None
    assert restored.session_state["current_draft"] is None
    assert restored.session_state["draft_workspaces"] == {}
    no_refresh.assert_not_called()
    # Recovery is once per session; live edits are not replaced on a rerun.
    restored.session_state["found_contacts"] = {}
    restored.run()
    assert restored.session_state["found_contacts"] == {}


def test_removed_selection_survives_refresh_without_selecting_other_database_jobs(
    temp_db, tmp_path
):
    storage = LocalStorage(str(tmp_path))
    job = JobPosting(title="Selected", company="Example")
    facade.persist_manual_job(job)
    facade.persist_manual_job(JobPosting(title="Imported only", company="Other"))
    facade.save_workspace(storage, _state(job))
    app = _app(storage)
    app.session_state["page"] = "discovery"
    app.run()
    _button(app, "Remove").click().run()
    assert app.session_state["selected_jobs"] == []
    restored = _app(storage)
    assert restored.session_state["selected_jobs"] == []
    assert len(facade.top_jobs()) == 2


def test_corrupt_recovery_is_visible_and_explicit_reset_retains_backup(
    temp_db, tmp_path
):
    storage = LocalStorage(str(tmp_path))
    path = tmp_path / "workspace.json"
    path.write_text("unreadable saved workspace")
    app = _app(storage)
    assert any("recovery failed" in warning.value for warning in app.warning)
    assert path.read_text() == "unreadable saved workspace"
    _field(app, "Target Roles (one per line)", "text_area").set_value(
        "Preserved new preference"
    ).run()
    assert path.read_text() == "unreadable saved workspace"
    _button(app, "Start a new saved workspace").click().run()
    assert not app.exception
    backup = next(tmp_path.glob("workspace-unreadable-*.bak"))
    assert backup.read_text() == "unreadable saved workspace"
    assert os.stat(backup).st_mode & 0o777 == 0o600
    assert load_workspace(storage).preferences.target_roles == [
        "Preserved new preference"
    ]


def test_save_failure_keeps_live_builder_input_and_previous_workspace(
    temp_db, tmp_path, monkeypatch
):
    storage = LocalStorage(str(tmp_path))
    app = _app(storage)
    original = (tmp_path / "workspace.json").read_bytes()
    monkeypatch.setattr(
        facade, "save_workspace", Mock(side_effect=OSError("Disk unavailable"))
    )
    _field(app, "Full name").set_value("Unsent CV builder input")
    _field(app, "Target Roles (one per line)", "text_area").set_value(
        "New preference"
    ).run()
    assert not app.exception
    assert _field(app, "Full name").value == "Unsent CV builder input"
    assert app.session_state["preferences"]["target_roles"] == ["New preference"]
    assert (tmp_path / "workspace.json").read_bytes() == original
    assert any(
        "previous saved workspace is retained" in warning.value
        for warning in app.warning
    )


def test_no_changed_workspace_means_no_write_or_repeated_restore(
    temp_db, tmp_path, monkeypatch
):
    storage = LocalStorage(str(tmp_path))
    app = _app(storage)
    restore = Mock(side_effect=AssertionError("Repeated recovery"))
    save = Mock(side_effect=AssertionError("Unchanged rerun must not write"))
    monkeypatch.setattr(facade, "restore_workspace", restore)
    monkeypatch.setattr(facade, "save_workspace", save)
    _field(app, "Full name").set_value("Unsent CV input").run()
    assert not app.exception
    restore.assert_not_called()
    save.assert_not_called()


def test_new_browser_with_wrong_key_shows_recovery_error_and_retains_file(
    temp_db, tmp_path, monkeypatch
):
    storage = LocalStorage(str(tmp_path))
    save_workspace(storage, WorkspaceSnapshot(page="contacts"))
    original = (tmp_path / "workspace.json").read_bytes()
    monkeypatch.setenv("CAREERAGENT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _get_key.cache_clear()
    try:
        app = _app(storage)
        assert any("recovery failed" in warning.value for warning in app.warning)
        assert app.session_state["workspace_recovery_blocked"] is True
        assert app.session_state["found_contacts"] == {}
        assert (tmp_path / "workspace.json").read_bytes() == original
    finally:
        _get_key.cache_clear()


def test_changed_active_cv_invalidates_artifacts_and_new_browser_keeps_latest_id(
    temp_db, tmp_path
):
    storage = LocalStorage(str(tmp_path))
    old_cv = CVProfile(name="Old synthetic CV")
    old_id = facade.persist_cv(old_cv)
    new_cv = CVProfile(name="New synthetic CV")
    new_id = facade.persist_cv(new_cv)
    save_workspace(storage, WorkspaceSnapshot(cv_id=old_id))
    app = _app(
        storage,
        tailored={"old": "generated"},
        cover={"letter": "old"},
        draft_workspaces={"old": {}},
    )
    assert app.session_state["cv_id"] == old_id
    _field(app, "Saved profile", "selectbox").set_value(new_id)
    _button(app, "Use this CV").click().run()
    assert not app.exception
    assert app.session_state["tailored"] is None
    assert app.session_state["cover"] is None
    assert app.session_state["draft_workspaces"] == {}
    restored = _app(storage)
    assert restored.session_state["cv_id"] == new_id
    assert restored.session_state["cv_profile"] == new_cv
    assert facade.load_cv(old_id) == old_cv


def test_missing_version_inside_valid_ciphertext_is_rejected(tmp_path):
    storage = LocalStorage(str(tmp_path))
    (tmp_path / "workspace.json").write_text(
        json.dumps(encrypt_payload({"page": "draft"}))
    )
    with pytest.raises(ValueError, match="schema version"):
        load_workspace(storage)


@pytest.mark.parametrize("operation", [load_workspace, reset_workspace])
def test_dangling_symlink_is_rejected(tmp_path, operation):
    storage = LocalStorage(str(tmp_path / "storage"))
    path = Path(storage.storage_dir) / "workspace.json"
    path.symlink_to(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="regular"):
        operation(storage)
    assert path.is_symlink()


def test_failed_private_file_flush_preserves_previous_snapshot(tmp_path, monkeypatch):
    storage = LocalStorage(str(tmp_path))
    save_workspace(storage, WorkspaceSnapshot(page="contacts"))
    old = (tmp_path / "workspace.json").read_bytes()
    monkeypatch.setattr(
        "core.workspace.os.fsync", Mock(side_effect=OSError("disk full"))
    )
    with pytest.raises(OSError):
        save_workspace(storage, WorkspaceSnapshot(page="draft"))
    assert (tmp_path / "workspace.json").read_bytes() == old
    assert list(tmp_path.glob(".workspace-*.part")) == []


def test_encrypted_output_size_limit_preserves_previous_snapshot(tmp_path, monkeypatch):
    storage = LocalStorage(str(tmp_path))
    save_workspace(storage, WorkspaceSnapshot())
    old = (tmp_path / "workspace.json").read_bytes()
    # Permit reading the old snapshot but reject the larger new encrypted payload.
    monkeypatch.setattr("core.workspace.MAX_WORKSPACE_BYTES", len(old) + 10)
    snapshot = WorkspaceSnapshot(
        found_contacts={"Example": [{"name": "Long contact " * 20}]}
    )
    with pytest.raises(ValueError, match="size limit"):
        save_workspace(storage, snapshot)
    assert (tmp_path / "workspace.json").read_bytes() == old


def test_failed_reset_retains_unreadable_original_and_cleans_backup(
    tmp_path, monkeypatch
):
    storage = LocalStorage(str(tmp_path))
    path = tmp_path / "workspace.json"
    path.write_text("unreadable original")
    monkeypatch.setattr(
        "core.workspace.os.fsync", Mock(side_effect=OSError("disk full"))
    )
    with pytest.raises(OSError):
        reset_workspace(storage)
    assert path.read_text() == "unreadable original"
    assert list(tmp_path.glob("workspace-unreadable-*.bak")) == []


def test_empty_reset_and_document_bounds(tmp_path):
    storage = LocalStorage(str(tmp_path))
    assert reset_workspace(storage) is None
    assert load_workspace(storage) is None
    with pytest.raises(ValidationError, match="Too many saved companies"):
        WorkspaceSnapshot(found_contacts={str(i): [] for i in range(201)})
    with pytest.raises(ValidationError, match="Too many saved contacts"):
        WorkspaceSnapshot(
            found_contacts={str(i): [{"name": "Contact"}] * 100 for i in range(6)}
        )


@pytest.mark.parametrize("shared_url", [None, "https://example.test/job"])
def test_same_fingerprint_never_substitutes_other_source_facts(
    temp_db, tmp_path, shared_url
):
    from core.db.repository import JobRepository

    storage = LocalStorage(str(tmp_path))
    api = JobPosting(
        title="Engineer",
        company="Example",
        description="Older API facts",
        url=shared_url or "https://example.test/api",
    )
    with get_session() as session:
        api_id = JobRepository(session).upsert(api, "greenhouse", "api-1").id
    manual = JobPosting(
        title="Engineer",
        company="Example",
        description="Distinct pasted facts",
        url=shared_url,
    )
    manual_id = facade.persist_manual_job(manual)
    assert api_id != manual_id
    # Legacy session fallback requires exact full facts, including an absent URL.
    facade.save_workspace(storage, _state(manual))
    assert load_workspace(storage).selected_job_ids == [manual_id]
    assert facade.restore_workspace(storage)["state"]["selected_jobs"] == [manual]
    # An intentional API choice must preserve its actual row identity too.
    state = _state(api)
    state["selected_job_refs"] = {facade.workspace_job_key(api): api_id}
    facade.save_workspace(storage, state)
    assert load_workspace(storage).selected_job_ids == [api_id]
    assert facade.restore_workspace(storage)["state"]["selected_jobs"] == [api]


def test_known_reference_preserves_intent_after_source_facts_change(temp_db, tmp_path):
    storage = LocalStorage(str(tmp_path))
    job = JobPosting(title="Engineer", company="Example", description="Original facts")
    job_id = facade.persist_manual_job(job)
    state = _state(job)
    state["selected_job_refs"] = {facade.workspace_job_key(job): job_id}
    with get_session() as session:
        row = session.get(JobPostingRow, job_id)
        row.description = "Updated source facts"
        session.add(row)
    facade.save_workspace(storage, state)
    restored = facade.restore_workspace(storage)["state"]
    assert restored["selected_jobs"][0].description == "Updated source facts"
    assert restored["selected_job_refs"] == {
        facade.workspace_job_key(restored["selected_jobs"][0]): job_id
    }


@pytest.mark.parametrize("reference", [True, -1, "1", 99999])
def test_invalid_known_reference_cannot_replace_workspace(temp_db, tmp_path, reference):
    storage = LocalStorage(str(tmp_path))
    job = JobPosting(title="Engineer", company="Example")
    facade.persist_manual_job(job)
    facade.save_workspace(storage, _state(job))
    previous = (tmp_path / "workspace.json").read_bytes()
    state = _state(job)
    state["selected_job_refs"] = {facade.workspace_job_key(job): reference}
    with pytest.raises(ValueError, match="reference"):
        facade.save_workspace(storage, state)
    assert (tmp_path / "workspace.json").read_bytes() == previous


@pytest.mark.parametrize(
    "label,kind,value,preference,expected",
    [
        (
            "Target Roles (one per line)",
            "text_area",
            "Data Engineer\nSoftware Engineer",
            "target_roles",
            ["Data Engineer", "Software Engineer"],
        ),
        (
            "Target Locations (one per line)",
            "text_area",
            "Remote only\nLondon",
            "target_locations",
            ["Remote only", "London"],
        ),
        (
            "Preferred Industries",
            "multiselect",
            ["Healthcare"],
            "industries",
            ["Healthcare"],
        ),
        ("Seniority Level", "select_slider", "Junior", "seniority", "Junior"),
    ],
)
def test_pending_preference_edit_and_navigation_same_event_survive_reload(
    temp_db, tmp_path, label, kind, value, preference, expected
):
    storage = LocalStorage(str(tmp_path))
    app = _app(storage)
    # Deliberately no run() between edit and navigation: real browser blur and
    # sidebar click may arrive together before page_onboarding can execute.
    _field(app, label, kind).set_value(value)
    _button(app, "Job Discovery").click().run()
    assert not app.exception
    assert app.session_state["page"] == "discovery"
    assert app.session_state["preferences"][preference] == expected
    restored = _app(storage)
    assert restored.session_state["page"] == "discovery"
    assert restored.session_state["preferences"][preference] == expected
    _button(restored, "Onboarding").click().run()
    assert not restored.exception
    assert _field(restored, label, kind).value == value
