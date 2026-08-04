"""The Apply flow: job link -> autofillable form -> tracked application."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from core import facade
from core.apply import (
    build_autofill_profile,
    resolve_apply_url,
    split_name,
)
from core.db import reset_engine
from core.models import CVProfile, Experience, JobPosting


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'apply.db'}")
    reset_engine()
    facade.init_persistence()
    yield
    reset_engine()


def _cv() -> CVProfile:
    return CVProfile(
        name="Ada Lovelace",
        email="ada@example.com",
        phone="+44 20 7946 0000",
        linkedin="https://linkedin.com/in/ada",
        github="https://github.com/ada",
        skills=["Python"],
        experiences=[
            Experience(
                title="Engineer", company="AE", duration="3y", technologies=["Python"]
            )
        ],
    )


# --------------------------------------------------------------------------- #
# Apply URL resolution
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,ats",
    [
        ("https://boards.greenhouse.io/acme/jobs/1", "greenhouse"),
        ("https://jobs.lever.co/acme/abc-123", "lever"),
        ("https://jobs.ashbyhq.com/acme/xyz", "ashby"),
    ],
)
def test_supported_ats_is_autofillable(url, ats):
    target = resolve_apply_url(url)
    assert target.ats == ats
    assert target.autofill_supported is True
    assert target.url == url


def test_recognized_but_unsupported_ats_says_so():
    target = resolve_apply_url("https://acme.wd5.myworkdayjobs.com/External/job/1")
    assert target.ats == "workday"
    assert target.autofill_supported is False
    assert "not supported" in target.note


def test_unknown_host_still_opens_but_warns():
    target = resolve_apply_url("https://careers.example.com/apply/9")
    assert target.url is not None
    assert target.autofill_supported is False
    assert "Autofill only runs" in target.note


def test_missing_url_is_handled():
    target = resolve_apply_url(None)
    assert target.url is None
    assert "no application link" in target.note


# --------------------------------------------------------------------------- #
# Autofill profile derived from the real CV
# --------------------------------------------------------------------------- #


def test_split_name_handles_edge_cases():
    assert split_name("Ada Lovelace") == ("Ada", "Lovelace")
    assert split_name("Ada") == ("Ada", "")
    assert split_name("Ada King Lovelace") == ("Ada", "Lovelace")
    assert split_name(None) == ("", "")
    assert split_name("   ") == ("", "")


def test_profile_is_derived_from_cv_not_invented():
    cv = _cv()
    profile = build_autofill_profile(cv).to_dict()
    assert profile["fullName"] == "Ada Lovelace"
    assert profile["firstName"] == "Ada"
    assert profile["lastName"] == "Lovelace"
    assert profile["email"] == "ada@example.com"
    assert profile["linkedin"] == cv.linkedin
    # CVProfile has no location; we must not invent one for a real form.
    assert profile["location"] == ""


def test_absent_cv_fields_stay_empty():
    sparse = CVProfile(name="Grace Hopper")
    profile = build_autofill_profile(sparse).to_dict()
    assert profile["email"] == ""
    assert profile["phone"] == ""
    assert profile["github"] == ""
    assert "resume" not in profile  # nothing to attach


def test_resume_pdf_is_embedded_for_the_file_input():
    profile = build_autofill_profile(
        _cv(), resume_pdf=b"%PDF-1.4 fake", resume_filename="ada.pdf"
    ).to_dict()
    assert profile["resume"]["filename"] == "ada.pdf"
    assert profile["resume"]["mime"] == "application/pdf"
    assert base64.b64decode(profile["resume"]["data_b64"]) == b"%PDF-1.4 fake"


# --------------------------------------------------------------------------- #
# Facade: export + mark applied
# --------------------------------------------------------------------------- #


def test_autofill_profile_json_round_trips(temp_db):
    payload = json.loads(facade.autofill_profile_json(_cv(), location="London, UK"))
    assert payload["email"] == "ada@example.com"
    assert payload["location"] == "London, UK"
    # A real ATS-clean PDF is generated and embedded.
    assert base64.b64decode(payload["resume"]["data_b64"]).startswith(b"%PDF")
    assert payload["meta"]["never_submits"] is True


def test_autofill_profile_can_omit_resume(temp_db):
    payload = json.loads(facade.autofill_profile_json(_cv(), include_resume=False))
    assert "resume" not in payload


@respx.mock
def test_apply_target_and_mark_applied(temp_db):
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 1,
                        "title": "ML Engineer",
                        "location": {"name": "Remote"},
                        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                        "content": "Python",
                    }
                ]
            },
        )
    )
    with httpx.Client() as client:
        facade.ingest_ats("greenhouse", "acme", "Acme", client=client)
    job_id = facade.top_jobs()[0]["id"]

    target = facade.apply_target(job_id)
    assert target["autofill_supported"] is True
    assert target["url"].startswith("https://boards.greenhouse.io/")

    # Applying to an untracked job creates and advances it in one step.
    result = facade.mark_applied(job_id)
    assert result["ok"] is True
    assert result["status"] == "applied"
    assert result["changed"] is True
    assert len(facade.pipeline_board()["applied"]) == 1

    # Doing it again is safe and does not regress the status.
    again = facade.mark_applied(job_id)
    assert again["ok"] is True
    assert again["changed"] is False


def test_apply_target_for_missing_job(temp_db):
    assert facade.apply_target(4242)["url"] is None


def test_mark_applied_rejects_unknown_job(temp_db):
    assert facade.mark_applied(4242)["ok"] is False


def test_apply_context_includes_job_identity():
    from core.apply import apply_context

    ctx = apply_context(
        JobPosting(
            title="SRE",
            company="Globex",
            url="https://jobs.lever.co/globex/1",
        )
    )
    assert ctx["title"] == "SRE"
    assert ctx["company"] == "Globex"
    assert ctx["autofill_supported"] is True
