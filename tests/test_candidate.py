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


@pytest.mark.parametrize("amount", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize("field", ["minimum", "target"])
def test_pay_must_be_finite(field, amount):
    with pytest.raises(ValidationError, match="finite"):
        CandidateProfile.model_validate({"compensation": {field: amount}})


def test_expected_pay_must_not_be_below_saved_minimum():
    with pytest.raises(ValidationError, match="at least the minimum"):
        Compensation(minimum=42.75, target=40)
    assert Compensation(minimum=42.75, target=42.75).target == 42.75
    assert Compensation(target=0).is_complete()


@pytest.mark.parametrize(
    "amount",
    ["42.12345678901234567", "123456789012345678.90", 123456789012345678, True],
)
def test_stated_pay_is_rejected_when_float_storage_would_change_its_value(amount):
    with pytest.raises(ValidationError, match="precision|yes/no"):
        CandidateProfile.model_validate({"compensation": {"target": amount}})


@pytest.mark.parametrize(
    "amount,expected",
    [("42.75", 42.75), ("0.0000001", 0.0000001), ("1234567.25", 1234567.25), ("0", 0)],
)
def test_ordinary_decimal_text_is_accepted_without_changing_its_stated_value(
    amount, expected
):
    candidate = CandidateProfile.model_validate({"compensation": {"target": amount}})
    assert candidate.compensation.target == expected


def test_blank_editor_fields_are_unknown_and_explicit_false_and_zero_survive():
    candidate = CandidateProfile.model_validate(
        {
            "location": "  ",
            "websites": [
                " ",
                " https://example.test/work ",
                "https://example.test/work",
            ],
            "work_authorization": {
                "country": " United Kingdom ",
                "authorized": False,
                "requires_sponsorship": "",
                "visa_status": "  ",
            },
            "compensation": {"minimum": "", "target": "0"},
            "availability": {"notice_period_weeks": "0", "earliest_start_date": " "},
            "preferences": {"desired_titles": [" Engineer ", "", "Engineer"]},
            "demographics": {"pronouns": " ", "share_on_applications": False},
            "default_cover_note": " A note I wrote. ",
        }
    )
    assert candidate.location is None
    assert candidate.websites == ["https://example.test/work"]
    assert candidate.work_authorization.country == "United Kingdom"
    assert candidate.work_authorization.authorized is False
    assert candidate.work_authorization.requires_sponsorship is None
    assert candidate.work_authorization.visa_status is None
    assert candidate.compensation.minimum is None
    assert candidate.compensation.target == 0
    assert candidate.availability.notice_period_weeks == 0
    assert candidate.availability.earliest_start_date is None
    assert candidate.preferences.desired_titles == ["Engineer"]
    assert candidate.demographics.pronouns is None
    assert candidate.default_cover_note == "A note I wrote."


@pytest.mark.parametrize(
    "url",
    [
        "not a website",
        "javascript:alert(1)",
        "https://[invalid",
        "https://example.test:abc/work",
        "https://user:pass@example.test/work",
        "https://example.test/work\nsecond-line",
        "https://example.test/work\x00",
        "https://example.test\\other.test/work",
    ],
)
def test_candidate_websites_reject_malformed_links_locally(url):
    with pytest.raises(ValidationError, match="complete HTTP"):
        CandidateProfile(websites=[url])


def test_extension_text_limits_reject_instead_of_silently_truncating():
    with pytest.raises(ValidationError, match="5000"):
        CandidateProfile(default_cover_note="x" * 5001)
    with pytest.raises(ValidationError, match="100"):
        WorkAuthorization(country="x" * 101)


@pytest.mark.parametrize("weeks", [-1, 1.5, 105])
def test_notice_period_does_not_round_or_exceed_bounds(weeks):
    with pytest.raises(ValidationError):
        CandidateProfile(availability={"notice_period_weeks": weeks})


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
