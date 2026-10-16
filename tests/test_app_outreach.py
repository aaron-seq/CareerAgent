"""Exercise real Streamlit reruns with fake Gmail and DNS boundaries."""

from pathlib import Path
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest

from core import facade
from core.llm import LocalLLMClient
from core.models import ContactCandidate, CVProfile, EmailDraft, JobPosting
from core.storage import LocalStorage


def _draft_studio(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.outreach.verification._default_resolver",
        lambda domain: ["mx.example.test"],
    )
    gmail = Mock()
    gmail.create_draft.return_value = "synthetic-draft-id"
    at = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    initial_state = {
        "page": "draft",
        "llm_client": LocalLLMClient(),
        "cv_profile": CVProfile(name="Ada", email="ada@example.test"),
        "selected_jobs": [JobPosting(title="Engineer", company="Example")],
        "found_contacts": {
            "Example": [
                ContactCandidate(name="Hiring Manager", email="hm@example.test")
            ]
        },
        "current_draft": EmailDraft(
            subject="Application",
            body="I would love to discuss Example's role.",
            recipient_email="hm@example.test",
            company="Example",
        ),
        "gmail_client": gmail,
        "storage": LocalStorage(str(tmp_path / "storage")),
    }
    for key, value in initial_state.items():
        at.session_state[key] = value
    at.run()
    assert not at.exception
    next(
        field for field in at.text_input if field.label == "Physical postal address"
    ).set_value("1 Example Street").run()
    return at, gmail


def test_gmail_action_survives_rerun_and_uses_compliant_body(
    temp_db, tmp_path, monkeypatch
):
    at, gmail = _draft_studio(tmp_path, monkeypatch)
    next(
        button for button in at.button if button.label == "Run compliance check"
    ).click().run()
    next(
        button for button in at.button if button.label == "Create Gmail Draft"
    ).click().run()
    assert not at.exception
    gmail.create_draft.assert_called_once()
    kwargs = gmail.create_draft.call_args.kwargs
    assert kwargs["to"] == "hm@example.test"
    assert "1 Example Street" in kwargs["body"]
    assert "To opt out" in kwargs["body"]


def test_opt_out_after_preview_is_rechecked_at_gmail_action(
    temp_db, tmp_path, monkeypatch
):
    at, gmail = _draft_studio(tmp_path, monkeypatch)
    next(
        button for button in at.button if button.label == "Run compliance check"
    ).click().run()
    facade.record_opt_out("hm@example.test")
    next(
        button for button in at.button if button.label == "Create Gmail Draft"
    ).click().run()
    assert not at.exception
    gmail.create_draft.assert_not_called()
    assert any("suppression" in error.value for error in at.error)


def test_initialize_does_not_connect_an_uninstalled_model(temp_db, monkeypatch):
    monkeypatch.setattr("core.llm.LocalLLMClient.check_connection", lambda self: True)
    monkeypatch.setattr(
        "core.llm.LocalLLMClient.check_model_availability", lambda self, model: False
    )
    at = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    ).run()
    next(
        button for button in at.button if button.label == "Initialize LLM"
    ).click().run()
    assert not at.exception
    assert at.session_state["llm_client"] is None
    assert any("model" in error.value.lower() for error in at.error)


def test_switching_provider_disconnects_the_previous_client(temp_db):
    at = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    at.session_state["llm_client"] = LocalLLMClient()
    at.run()
    assert at.session_state["llm_client"] is not None
    at.radio(key="llm_provider").set_value("Groq (cloud, free tier)").run()
    assert not at.exception
    assert at.session_state["llm_client"] is None
