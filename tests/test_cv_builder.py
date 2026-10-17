"""Builder boundaries preserve only explicitly supplied candidate facts."""

import copy

import pytest

from core.resume.builder import build_cv_profile


def _draft():
    return {
        "name": "  Synthetic Candidate  ",
        "email": "candidate@example.test",
        "skills": "Python\nSQL\nPython\n",
        "education": "BSc Computing",
        "experiences": [
            {
                "title": "Engineer",
                "company": "Example",
                "duration": "2021–2024",
                "achievements": "Reduced latency by 23%",
                "metrics": [],
                "technologies": "Python\nSQL",
            },
            {},
        ],
        "projects": [
            {
                "name": "Tool",
                "description": "Built an internal tool",
                "technologies": ["Python"],
                "link": "https://example.test/tool",
                "github": "https://github.com/example/tool",
                "impact": "Used by 12 teammates",
            }
        ],
        "raw_text": "Obsolete claim: Rust expert",
    }


def test_builder_preserves_facts_dates_links_and_source_input():
    data = _draft()
    before = copy.deepcopy(data)
    profile = build_cv_profile(data)
    assert data == before
    assert profile.name == "Synthetic Candidate"
    assert profile.skills == ["Python", "SQL"]
    assert len(profile.experiences) == 1
    assert profile.experiences[0].duration == "2021–2024"
    assert profile.experiences[0].achievements == ["Reduced latency by 23%"]
    assert profile.projects[0].github == "https://github.com/example/tool"
    assert profile.projects[0].impact == "Used by 12 teammates"
    assert profile.raw_text == ""
    assert "Rust" not in profile.model_dump_json()


def test_project_only_entry_level_cv_needs_no_invented_employer():
    profile = build_cv_profile(
        {
            "name": "Student",
            "projects": [
                {"name": "Class project", "description": "Implemented a parser"}
            ],
        }
    )
    assert profile.experiences == []
    assert profile.email is None
    assert profile.projects[0].description == "Implemented a parser"


@pytest.mark.parametrize(
    "data, message",
    [
        ({}, "name"),
        ({"name": "Candidate"}, "Add skills"),
        ({"name": "Candidate", "skills": [123]}, "text"),
        ({"name": "Candidate", "email": "invalid", "skills": ["SQL"]}, "email"),
        ({"name": "Candidate", "experiences": [{"title": "Engineer"}]}, "Role 1"),
        ({"name": "Candidate", "projects": [{"name": "Tool"}]}, "Project 1"),
        ({"name": "Candidate", "experiences": ["Engineer"]}, "named fields"),
        ({"name": "Candidate", "projects": [{}] * 31}, "at most 30"),
    ],
)
def test_invalid_or_partial_builder_input_is_actionable(data, message):
    with pytest.raises(ValueError, match=message):
        build_cv_profile(data)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://user:password@example.test",
        "https://",
        "https://example.test:invalid",
        "https://example .test",
    ],
)
def test_builder_rejects_unsafe_or_broken_links(url):
    with pytest.raises(ValueError, match="HTTP"):
        build_cv_profile({"name": "Candidate", "skills": ["SQL"], "portfolio": url})


def test_builder_validation_never_queries_dns(monkeypatch):
    def unexpected_query(_):
        pytest.fail("Builder validation must remain local")

    monkeypatch.setattr(
        "core.outreach.verification._default_resolver", unexpected_query
    )
    assert build_cv_profile(_draft()).email == "candidate@example.test"


def test_existing_profile_can_be_edited_without_old_extraction_claims():
    original = build_cv_profile(_draft())
    original.raw_text = "Old skill Kubernetes"
    data = original.model_dump()
    data["skills"] = ["SQL"]
    updated = build_cv_profile(data)
    assert original.skills == ["Python", "SQL"]
    assert updated.skills == ["SQL"]
    assert updated.raw_text == ""
