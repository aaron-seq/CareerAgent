"""Profile and contact entry without a model (real-user blocker, 2026-10-16).

A first-time user without Ollama or a Groq key could not create a profile at
all; these pin the facade path the hand-entry form uses.
"""

import pytest

from core import facade
from core.outreach import is_valid_email


@pytest.mark.parametrize(
    "email, ok",
    [
        ("jordan@example.com", True),
        ("j.o+jobs@mail.example.co.uk", True),
        ("not-an-email", False),
        ("jordan@", False),
        ("", False),
        (None, False),
    ],
)
def test_is_valid_email(email, ok):
    assert is_valid_email(email) is ok


def _form(**overrides):
    form = {
        "name": "Jordan Example",
        "email": "jordan@example.com",
        "phone": "",
        "linkedin": "",
        "github": "",
        "portfolio": "",
        "summary": "Data engineer.",
        "skills": "Python, SQL\nAirflow, , python",
        "education": "BSc Computer Science\n",
        "experiences": [
            {
                "title": "Data Engineer",
                "company": "Acme",
                "duration": "2021-2024",
                "achievements": "Cut pipeline cost 30%\n\nOwned the warehouse",
            },
            {"title": "", "company": "", "duration": "", "achievements": ""},
        ],
    }
    form.update(overrides)
    return form


def test_save_manual_profile_creates_a_loadable_cv(temp_db):
    result = facade.save_manual_profile(_form())
    assert result["ok"] is True and result["errors"] == []
    cv = facade.load_cv(result["cv_id"])
    assert cv.name == "Jordan Example"
    # Comma/newline lists are split, trimmed, blank-free and de-duplicated
    # case-insensitively, keeping the first spelling.
    assert cv.skills == ["Python", "SQL", "Airflow"]
    assert cv.education == ["BSc Computer Science"]
    # Fully blank experience rows are ignored rather than stored empty.
    assert len(cv.experiences) == 1
    assert cv.experiences[0].achievements == [
        "Cut pipeline cost 30%",
        "Owned the warehouse",
    ]
    # Empty optional fields are unknown, not "" -- nothing is invented.
    assert cv.phone is None and cv.linkedin is None
    assert result["profile"] == cv


def test_save_manual_profile_reports_every_problem_and_stores_nothing(temp_db):
    result = facade.save_manual_profile(
        _form(
            name="  ",
            email="not-an-email",
            linkedin="javascript:alert(1)",
            experiences=[{"title": "Engineer", "company": "", "duration": ""}],
        )
    )
    assert result["ok"] is False and result["cv_id"] is None
    joined = " ".join(result["errors"]).lower()
    assert "name" in joined
    assert "email" in joined
    assert "linkedin" in joined
    assert "company" in joined
    assert facade.saved_cv_profiles() == []


def test_save_manual_profile_updates_in_place_and_keeps_answers(temp_db):
    first = facade.save_manual_profile(_form())
    facade.save_candidate_profile(first["cv_id"], {"location": "Berlin"})
    again = facade.save_manual_profile(_form(summary="Senior."), cv_id=first["cv_id"])
    assert again["ok"] and again["cv_id"] == first["cv_id"]
    assert facade.load_cv(first["cv_id"]).summary == "Senior."
    assert facade.load_candidate_profile(first["cv_id"]).location == "Berlin"
    assert len(facade.saved_cv_profiles()) == 1


def test_save_manual_profile_unknown_cv_id_is_an_error(temp_db):
    result = facade.save_manual_profile(_form(), cv_id=9999)
    assert result["ok"] is False
    assert result["errors"]


def test_manual_contact_validates_and_never_claims_verification():
    ok = facade.manual_contact("Pat Recruiter", "pat@example.com", "Recruiter")
    assert ok["ok"] is True
    contact = ok["contact"]
    assert contact.source == "manual"
    # The user typed it; nothing checked deliverability.
    assert contact.email_confidence != "confirmed"

    bad = facade.manual_contact("Pat", "not-an-email", "")
    assert bad["ok"] is False and "email" in bad["error"].lower()
    empty = facade.manual_contact("", "", "")
    assert empty["ok"] is False and "name" in empty["error"].lower()
