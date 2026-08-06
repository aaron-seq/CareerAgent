"""Candidate profile: completeness scoring and form-answer derivation."""

from __future__ import annotations

import json

import pytest

from core import facade
from core.apply import build_answers, build_profile_from_candidate
from core.candidate import (
    Availability,
    CandidateProfile,
    Compensation,
    Demographics,
    JobPreferences,
    RemotePreference,
    WorkAuthorization,
    compute_completeness,
)
from core.db import reset_engine
from core.models import CVProfile, Experience


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cand.db'}")
    reset_engine()
    facade.init_persistence()
    yield
    reset_engine()


def _full_candidate() -> CandidateProfile:
    return CandidateProfile(
        cv=CVProfile(
            name="Ada Lovelace",
            email="ada@example.com",
            phone="+44 20 7946 0000",
            linkedin="https://linkedin.com/in/ada",
            github="https://github.com/ada",
            summary="Engineer.",
            skills=["Python"],
            education=["BSc"],
            experiences=[
                Experience(
                    title="Eng", company="AE", duration="3y", technologies=["Python"]
                )
            ],
        ),
        location="London, UK",
        work_authorization=WorkAuthorization(
            country="United Kingdom", authorized=True, requires_sponsorship=False
        ),
        compensation=Compensation(minimum=90000, currency="GBP"),
        availability=Availability(notice_period_weeks=4),
        preferences=JobPreferences(
            desired_titles=["ML Engineer"],
            remote_preference=RemotePreference.REMOTE_ONLY,
            open_to_relocation=False,
        ),
    )


# --------------------------------------------------------------------------- #
# Completeness
# --------------------------------------------------------------------------- #


def test_empty_profile_scores_zero():
    result = compute_completeness(CandidateProfile())
    assert result.percent == 0
    assert result.next_best_action() is not None


def test_full_profile_scores_100():
    assert compute_completeness(_full_candidate()).percent == 100


def test_completeness_prioritises_work_authorization():
    """Work auth blocks submissions, so it must outrank cosmetic fields."""
    candidate = _full_candidate()
    candidate.work_authorization = WorkAuthorization()  # clear it
    candidate.cv.github = ""
    candidate.cv.portfolio = None
    result = compute_completeness(candidate)
    top = result.next_best_action()
    assert top.key == "work_auth"
    assert result.percent < 100


def test_missing_items_carry_a_reason_and_section():
    result = compute_completeness(CandidateProfile())
    for item in result.missing:
        assert item.why
        assert item.section
    assert "Eligibility" in result.by_section()


def test_partial_work_authorization_is_not_complete():
    auth = WorkAuthorization(authorized=True)  # sponsorship unanswered
    assert auth.is_complete() is False


# --------------------------------------------------------------------------- #
# Form answers
# --------------------------------------------------------------------------- #


def test_answers_cover_the_blocking_questions():
    answers = build_answers(_full_candidate())
    assert answers["work_authorized"] is True
    assert answers["requires_sponsorship"] is False
    assert "GBP 90,000" in answers["salary_expectation"]
    assert answers["notice_period"] == "4 weeks"
    assert answers["willing_to_relocate"] is False
    assert answers["remote_preference"] == "remote_only"


def test_unanswered_questions_are_absent_not_false():
    """The core safety property: silence, not a guessed 'No'."""
    answers = build_answers(CandidateProfile())
    assert "work_authorized" not in answers
    assert "requires_sponsorship" not in answers
    assert answers == {}


def test_demographics_require_explicit_consent():
    candidate = _full_candidate()
    candidate.demographics = Demographics(pronouns="she/her", gender="Female")
    # Consent not given -> nothing shared.
    assert "pronouns" not in build_answers(candidate)

    candidate.demographics.share_on_applications = True
    answers = build_answers(candidate)
    assert answers["pronouns"] == "she/her"
    assert answers["gender"] == "Female"


def test_autofill_profile_merges_cv_and_answers():
    profile = build_profile_from_candidate(_full_candidate()).to_dict()
    assert profile["email"] == "ada@example.com"
    assert profile["location"] == "London, UK"
    assert profile["answers"]["work_authorized"] is True


# --------------------------------------------------------------------------- #
# Persistence + facade
# --------------------------------------------------------------------------- #


def test_candidate_round_trips_through_encrypted_storage(temp_db):
    candidate = _full_candidate()
    cv_id = facade.save_candidate(candidate)
    loaded = facade.load_candidate(cv_id)
    assert loaded is not None
    assert loaded.cv.name == "Ada Lovelace"
    assert loaded.work_authorization.requires_sponsorship is False
    assert loaded.compensation.minimum == 90000
    assert loaded.preferences.remote_preference == RemotePreference.REMOTE_ONLY


def test_saving_twice_updates_rather_than_duplicates(temp_db):
    candidate = _full_candidate()
    cv_id = facade.save_candidate(candidate)
    candidate.location = "Manchester, UK"
    same_id = facade.save_candidate(candidate, cv_id=cv_id)
    assert same_id == cv_id
    assert facade.load_candidate(cv_id).location == "Manchester, UK"


def test_legacy_cv_only_row_upgrades_to_candidate(temp_db):
    """Rows saved before candidate profiles existed must still load."""
    cv_id = facade.persist_cv(_full_candidate().cv)
    loaded = facade.load_candidate(cv_id)
    assert loaded is not None
    assert loaded.cv.name == "Ada Lovelace"
    assert loaded.work_authorization.authorized is None  # nothing invented


def test_profile_completeness_facade_shape(temp_db):
    report = facade.profile_completeness(CandidateProfile())
    assert report["percent"] == 0
    assert report["next_best_action"]["key"]
    assert all({"key", "label", "why", "section"} <= set(m) for m in report["missing"])


def test_candidate_autofill_json_includes_answers(temp_db):
    payload = json.loads(
        facade.candidate_autofill_json(_full_candidate(), include_resume=False)
    )
    assert payload["answers"]["work_authorized"] is True
    assert "resume" not in payload
