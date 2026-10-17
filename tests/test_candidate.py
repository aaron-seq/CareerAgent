"""Candidate profile: tri-state answers, validation, completeness, storage."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from core.candidate import (
    CandidateProfile,
    Compensation,
    RemotePreference,
    WorkAuthorization,
    compute_completeness,
)
from core.db.repository import CVRepository
from core.models import CVProfile, Experience


def _full_cv() -> CVProfile:
    return CVProfile(
        name="Ada Lovelace",
        email="ada@example.com",
        phone="+44 20 7946 0958",
        linkedin="https://linkedin.com/in/ada",
        github="https://github.com/ada",
        summary="Engineer.",
        experiences=[
            Experience(company="Analytical Engines", title="Engineer", duration="2y")
        ],
        skills=["python"],
        education=["BSc Mathematics"],
    )


def _full_candidate() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "location": "London, UK",
            "work_authorization": {
                "country": "United Kingdom",
                "authorized": True,
                "requires_sponsorship": False,
            },
            "compensation": {"minimum": 90000, "currency": "GBP"},
            "availability": {"notice_period_weeks": 4},
            "preferences": {
                "desired_titles": ["Backend Engineer"],
                "remote_preference": "hybrid",
            },
        }
    )


def test_every_answer_defaults_to_unknown_not_no():
    c = CandidateProfile()
    assert c.work_authorization.authorized is None
    assert c.work_authorization.requires_sponsorship is None
    assert c.preferences.open_to_relocation is None
    assert c.compensation.minimum is None
    assert c.demographics.share_on_applications is False


def test_work_authorization_needs_country_and_both_answers():
    assert not WorkAuthorization(authorized=True).is_complete()
    # False is a real answer, distinct from unknown.
    assert not WorkAuthorization(
        authorized=False, requires_sponsorship=False
    ).is_complete()
    assert not WorkAuthorization(
        country="   ", authorized=True, requires_sponsorship=False
    ).is_complete()
    assert WorkAuthorization(
        country="United Kingdom", authorized=False, requires_sponsorship=False
    ).is_complete()


@pytest.mark.parametrize(
    "bad",
    [
        {"compensation": {"minimum": -1}},
        {"compensation": {"currency": "pounds"}},
        {"compensation": {"period": "fortnight"}},
        {"availability": {"notice_period_weeks": -2}},
        {"preferences": {"remote_preference": "mars"}},
    ],
)
def test_invalid_answers_are_rejected(bad):
    with pytest.raises(ValidationError):
        CandidateProfile.model_validate(bad)


def test_completeness_is_100_for_a_complete_profile():
    result = compute_completeness(_full_cv(), _full_candidate())
    assert result.percent == 100
    assert result.missing == []
    assert result.to_dict()["next_best_action"] is None


def test_completeness_ranks_work_authorization_first():
    result = compute_completeness(_full_cv(), CandidateProfile())
    assert 0 < result.percent < 100
    assert result.missing[0].key == "work_authorization"
    data = result.to_dict()
    assert data["next_best_action"]["key"] == "work_authorization"
    assert {"key", "label", "done", "weight", "why", "section"} <= set(data["items"][0])


def test_completeness_without_answers_matches_an_empty_profile():
    cv = CVProfile(name="A")
    assert (
        compute_completeness(cv).percent
        == compute_completeness(cv, CandidateProfile()).percent
    )


def test_websites_count_toward_the_portfolio_item():
    cv = CVProfile()
    c = CandidateProfile(websites=["https://ada.dev"])
    done = {i.key: i.done for i in compute_completeness(cv, c).items}
    assert done["portfolio"] is True


def test_candidate_round_trips_encrypted_beside_its_cv(session):
    repo = CVRepository(session)
    row = repo.save(_full_cv())
    # A CV with no answers yet reads back as all-unknown, not None.
    assert repo.get_candidate(row.id) == CandidateProfile()

    candidate = _full_candidate()
    candidate.compensation = Compensation(minimum=120000)
    assert repo.save_candidate(row.id, candidate)
    session.commit()

    loaded = repo.get_candidate(row.id)
    assert loaded == candidate
    assert loaded.preferences.remote_preference is RemotePreference.HYBRID
    # The CV itself is untouched by saving answers.
    assert repo.get(row.id) == _full_cv()

    raw = session.exec(
        text("SELECT candidate_payload FROM cv_profile WHERE id = :id").bindparams(
            id=row.id
        )
    ).one()[0]
    assert "London" not in raw and "requires_sponsorship" not in raw


def test_missing_cv_is_reported_not_created(session):
    repo = CVRepository(session)
    assert repo.get_candidate(999) is None
    assert repo.save_candidate(999, CandidateProfile()) is False
