"""Apply flow: URL classification, screening answers, extension JSON contract."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

from core import facade
from core.apply import (
    AUTOFILL_HOSTS,
    BOOLEAN_ANSWER_KEYS,
    CONSENT_KEY,
    DEMOGRAPHIC_ANSWER_KEYS,
    MAX_RESUME_BYTES,
    TEXT_ANSWER_KEYS,
    build_answers,
    resolve_apply_url,
    resume_attachment,
)
from core.candidate import CandidateProfile
from core.models import CVProfile, JobPosting

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
FIXTURE = EXTENSION / "test" / "fixtures" / "candidate_profile.json"

CV = CVProfile(
    name="Ada Lovelace",
    email="ada@example.com",
    phone="+44 20 7946 0958",
    linkedin="https://linkedin.com/in/ada",
    github="https://github.com/ada",
)

CANDIDATE = CandidateProfile.model_validate(
    {
        "location": "London, UK",
        "websites": ["https://ada.dev"],
        "work_authorization": {
            "authorized": True,
            "requires_sponsorship": False,
            "visa_status": "British citizen",
        },
        "compensation": {"minimum": 90000, "currency": "GBP"},
        "availability": {"notice_period_weeks": 4, "earliest_start_date": "2026-12-01"},
        "preferences": {"open_to_relocation": False},
        "default_cover_note": "I build reliable data systems.",
        "demographics": {"pronouns": "she/her", "share_on_applications": True},
    }
)


# --------------------------------------------------------------------------- #
# resolve_apply_url
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,ats",
    [
        ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse"),
        ("https://job-boards.greenhouse.io/acme/jobs/123", "greenhouse"),
        ("https://jobs.lever.co/acme/abc-123", "lever"),
        ("https://jobs.ashbyhq.com/acme/abc-123", "ashby"),
    ],
)
def test_supported_ats_pages_get_autofill(url, ats):
    target = resolve_apply_url(url)
    assert target.autofill_supported is True
    assert target.ats == ats
    assert target.url == url


def test_recognised_but_unsupported_ats_is_honest():
    target = resolve_apply_url("https://acme.wd5.myworkdayjobs.com/External/job/1")
    assert target.ats == "workday"
    assert target.autofill_supported is False
    assert "manually" in target.note


def test_ats_slug_on_a_foreign_host_is_not_autofill_supported():
    # The content script only runs on the manifest hosts; a Greenhouse URL
    # mentioned in a query string elsewhere must not promise autofill.
    target = resolve_apply_url(
        "https://acme.example/careers?src=boards.greenhouse.io/acme"
    )
    assert target.autofill_supported is False


def test_unknown_site_opens_the_posting_without_autofill():
    target = resolve_apply_url("https://careers.acme.example/jobs/1")
    assert target.url == "https://careers.acme.example/jobs/1"
    assert target.ats is None and target.autofill_supported is False


@pytest.mark.parametrize(
    "url",
    [None, "", "   ", "javascript:alert(1)", "ftp://x.example/a", "not a url"],
)
def test_missing_or_non_web_links_are_never_returned(url):
    target = resolve_apply_url(url)
    assert target.url is None
    assert target.autofill_supported is False
    assert target.note


def test_autofill_hosts_match_the_extension_manifest():
    manifest = json.loads((EXTENSION / "manifest.json").read_text())
    hosts = {
        re.match(r"https://([^/]+)/", pattern).group(1)
        for script in manifest["content_scripts"]
        for pattern in script["matches"]
    }
    assert hosts == set(AUTOFILL_HOSTS)


# --------------------------------------------------------------------------- #
# build_answers
# --------------------------------------------------------------------------- #


def test_unknown_answers_are_absent_never_guessed():
    assert build_answers(CandidateProfile()) == {}


def test_false_is_exported_as_a_real_answer():
    answers = build_answers(
        CandidateProfile.model_validate({"work_authorization": {"authorized": False}})
    )
    assert answers == {"work_authorized": False}


def test_answers_cover_the_blocking_questions():
    answers = build_answers(CANDIDATE)
    assert answers["work_authorized"] is True
    assert answers["requires_sponsorship"] is False
    assert answers["salary_expectation"] == "GBP 90,000 per year"
    assert answers["notice_period"] == "4 weeks"
    assert answers["start_date"] == "2026-12-01"
    assert answers["willing_to_relocate"] is False


def test_demographics_need_explicit_consent():
    data = CANDIDATE.model_dump()
    data["demographics"] = {"gender": "Woman", "share_on_applications": False}
    answers = build_answers(CandidateProfile.model_validate(data))
    assert not set(DEMOGRAPHIC_ANSWER_KEYS) & set(answers)
    assert CONSENT_KEY not in answers

    data["demographics"]["share_on_applications"] = True
    answers = build_answers(CandidateProfile.model_validate(data))
    assert answers["gender"] == "Woman"
    assert answers[CONSENT_KEY] is True


def test_consent_without_any_demographic_answer_sends_nothing():
    answers = build_answers(
        CandidateProfile.model_validate(
            {"demographics": {"share_on_applications": True}}
        )
    )
    assert answers == {}


def test_every_answer_key_is_understood_by_the_extension():
    source = (EXTENSION / "src" / "field_mapping.js").read_text()
    for key in (
        *BOOLEAN_ANSWER_KEYS,
        *TEXT_ANSWER_KEYS,
        *DEMOGRAPHIC_ANSWER_KEYS,
        CONSENT_KEY,
    ):
        assert f"'{key}'" in source, key


# --------------------------------------------------------------------------- #
# resume_attachment
# --------------------------------------------------------------------------- #


def test_resume_attachment_encodes_a_pdf_with_a_safe_name():
    block = resume_attachment(b"%PDF-1.4 test", "Ada  Lovelace/../x")
    assert block["mime"] == "application/pdf"
    assert block["filename"] == "Ada_Lovelacex.pdf"
    assert base64.b64decode(block["data_b64"]) == b"%PDF-1.4 test"
    assert resume_attachment(b"%PDF", None)["filename"] == "resume.pdf"


def test_resume_attachment_rejects_non_pdf_and_oversize():
    with pytest.raises(ValueError):
        resume_attachment(b"<html>", "Ada")
    with pytest.raises(ValueError):
        resume_attachment(b"%PDF" + b"0" * MAX_RESUME_BYTES, "Ada")


# --------------------------------------------------------------------------- #
# Facade: extension_profile (the JSON the popup imports)
# --------------------------------------------------------------------------- #


def test_candidate_extension_profile_matches_the_shared_fixture():
    # extension/test/*.test.js feed this same file through parseImport and
    # answerFor, so both sides of the contract are pinned to one document.
    assert facade.extension_profile(CV, CANDIDATE) == json.loads(FIXTURE.read_text())


def test_cv_only_extension_profile_keeps_its_seven_string_keys():
    profile = facade.extension_profile(CV, CandidateProfile())
    assert set(profile) == {
        "fullName",
        "email",
        "phone",
        "linkedin",
        "github",
        "portfolio",
        "location",
    }
    assert all(isinstance(v, str) for v in profile.values())


def test_extension_profile_can_embed_the_rendered_resume():
    profile = facade.extension_profile(CV, include_resume=True)
    resume = profile["resume"]
    assert resume["filename"] == "Ada_Lovelace.pdf"
    assert base64.b64decode(resume["data_b64"]).startswith(b"%PDF")


def test_cv_portfolio_wins_over_candidate_websites():
    cv = CV.model_copy(update={"portfolio": "https://cv.example"})
    assert facade.extension_profile(cv, CANDIDATE)["portfolio"] == "https://cv.example"


# --------------------------------------------------------------------------- #
# Facade: candidate profile persistence + completeness
# --------------------------------------------------------------------------- #


def test_facade_saves_and_loads_answers_for_a_saved_cv(temp_db):
    cv_id = facade.persist_cv(CV)
    assert facade.load_candidate_profile(cv_id) == CandidateProfile()
    assert facade.save_candidate_profile(cv_id, CANDIDATE.model_dump(mode="json")) == {
        "ok": True,
        "cv_id": cv_id,
    }
    assert facade.load_candidate_profile(cv_id) == CANDIDATE
    # The saved-profile listing (and the CV itself) are unaffected.
    assert facade.load_cv(cv_id) == CV
    assert [p["id"] for p in facade.saved_cv_profiles()] == [cv_id]


def test_facade_reports_invalid_answers_instead_of_storing_them(temp_db):
    cv_id = facade.persist_cv(CV)
    result = facade.save_candidate_profile(cv_id, {"compensation": {"minimum": -5}})
    assert result["ok"] is False
    assert "compensation.minimum" in result["error"]
    assert facade.load_candidate_profile(cv_id) == CandidateProfile()


def test_facade_candidate_calls_handle_a_missing_cv(temp_db):
    assert facade.load_candidate_profile(404) is None
    assert facade.save_candidate_profile(404, CandidateProfile())["ok"] is False


def test_facade_profile_completeness_is_a_plain_dict():
    data = facade.profile_completeness(CV, CANDIDATE)
    json.dumps(data)  # UI-ready: serializable, no dataclasses/models
    assert 0 < data["percent"] <= 100
    assert data["next_best_action"]["key"] in {m["key"] for m in data["missing"]}


# --------------------------------------------------------------------------- #
# Facade: apply_target + mark_applied
# --------------------------------------------------------------------------- #


def _job(url: str = "https://jobs.lever.co/acme/1", title: str = "Engineer") -> int:
    return facade.persist_manual_job(JobPosting(title=title, company="Acme", url=url))


def test_apply_target_for_a_stored_job(temp_db):
    job_id = _job()
    target = facade.apply_target(job_id)
    assert target == {
        "ok": True,
        "job_id": job_id,
        "title": "Engineer",
        "company": "Acme",
        "url": "https://jobs.lever.co/acme/1",
        "ats": "lever",
        "autofill_supported": True,
        "note": target["note"],
    }


def test_apply_target_for_a_missing_job(temp_db):
    assert facade.apply_target(12345)["ok"] is False


def test_mark_applied_tracks_and_advances_once(temp_db):
    job_id = _job()
    first = facade.mark_applied(job_id)
    assert first["ok"] and first["status"] == "applied" and first["changed"]
    again = facade.mark_applied(job_id)
    assert again == {**first, "changed": False}
    card = facade.pipeline_board()["applied"][0]
    assert card["application_id"] == first["application_id"]


def test_mark_applied_advances_an_existing_saved_application(temp_db):
    job_id = _job()
    saved = facade.add_to_pipeline(job_id)
    result = facade.mark_applied(job_id)
    assert result["application_id"] == saved["application_id"]
    assert result["status"] == "applied" and result["changed"]


def test_mark_applied_leaves_later_and_closed_statuses_alone(temp_db):
    job_id = _job()
    app_id = facade.mark_applied(job_id)["application_id"]
    facade.advance_application(app_id, "screening")
    assert facade.mark_applied(job_id)["status"] == "screening"

    other = _job("https://jobs.lever.co/acme/2", title="Designer")
    other_app = facade.add_to_pipeline(other)["application_id"]
    facade.advance_application(other_app, "withdrawn")
    closed = facade.mark_applied(other)
    assert closed["ok"] is False and closed["status"] == "withdrawn"


def test_mark_applied_respects_the_blacklist(temp_db):
    job_id = _job()
    facade.blacklist_company("Acme")
    result = facade.mark_applied(job_id)
    assert result["ok"] is False and "blacklisted" in result["error"]
