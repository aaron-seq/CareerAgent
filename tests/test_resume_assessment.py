"""Meaningful examples for local readiness and exact factual job coverage."""

from __future__ import annotations

import pytest

from core.models import CVProfile, Experience, JobPosting, Project
from core.resume.assessment import assess_resume


def _cv() -> CVProfile:
    return CVProfile(
        name="Example Candidate",
        email="example@example.com",
        skills=["Python", "PostgreSQL", "Docker"],
        projects=[
            Project(
                name="Library catalogue",
                description="Built an accessible searchable catalogue for a local library.",
                technologies=["Python", "Postgres"],
            )
        ],
        education=["Community programming course"],
    )


def _match(cv: CVProfile, **kwargs):
    return assess_resume(cv, JobPosting(title="Engineer", company="Example", **kwargs))[
        "job_match"
    ]


def test_empty_cv_is_zero_and_actions_explain_all_weights():
    result = assess_resume(CVProfile())
    assert result["readiness_score"] == 0
    assert sum(check["weight"] for check in result["checks"]) == 100
    assert len(result["actions"]) == len(result["checks"])
    assert result["job_match"] is None


def test_projects_training_and_unquantified_work_can_earn_full_readiness():
    cv = _cv()
    assert not cv.experiences
    assert not cv.phone
    assert not cv.projects[0].link
    result = assess_resume(cv)
    assert result["readiness_score"] == 100
    assert result["actions"] == []


def test_whitespace_and_empty_records_are_not_useful_content():
    cv = CVProfile(
        name=" ",
        email=" ",
        skills=[" "],
        education=[""],
        experiences=[Experience(title="", company="", duration="")],
        projects=[Project(name="", description="")],
    )
    assert assess_resume(cv)["readiness_score"] == 0


@pytest.mark.parametrize(
    "email",
    [
        "person",
        "person@",
        "@example.com",
        "a@@example.com",
        "a@example",
        "a@.com",
        "a b@example.com",
        "a..b@example.com",
        ".a@example.com",
        "a@-example.com",
        "a<>@example.com",
    ],
)
def test_invalid_contact_does_not_earn_contact_weight(email):
    cv = _cv()
    cv.email = email
    result = assess_resume(cv)
    assert result["readiness_score"] == 85
    assert (
        next(check for check in result["checks"] if check["id"] == "email")["passed"]
        is False
    )


def test_incomplete_role_has_specific_action_and_does_not_require_fabricated_dates():
    cv = _cv()
    cv.experiences = [Experience(title="Volunteer", company="Library", duration="")]
    result = assess_resume(cv)
    assert result["readiness_score"] == 90
    assert any("duration" in action for action in result["actions"])


def test_role_with_real_achievement_needs_no_project_or_numeric_metric():
    cv = _cv()
    cv.projects = []
    cv.experiences = [
        Experience(
            title="Volunteer",
            company="Library",
            duration="2025–present",
            achievements=["Organized the catalogue to help visitors find books."],
        )
    ]
    assert assess_resume(cv)["readiness_score"] == 100


def test_bare_role_does_not_claim_supporting_evidence():
    cv = _cv()
    cv.projects = []
    cv.experiences = [Experience(title="Engineer", company="Example", duration="2025")]
    result = assess_resume(cv)
    assert result["readiness_score"] == 85
    assert any("accomplishment" in action for action in result["actions"])


def test_exact_language_boundaries_keep_c_languages_and_java_distinct():
    cv = CVProfile(skills=["C++", "JavaScript", "Node.js"])
    match = _match(cv, tech_stack=["C", "C#", "C++", "Java", "JavaScript", "Node.js"])
    assert match["matched"] == ["c++", "javascript", "node.js"]
    assert match["missing"] == ["c", "c#", "java"]
    assert match["score"] == 50


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("JS", "javascript"),
        ("NodeJS", "node.js"),
        ("csharp", "c#"),
        ("K8s", "kubernetes"),
        ("Amazon Web Services", "aws"),
        ("Postgres", "postgresql"),
        ("Go", "go"),
        ("R", "r"),
    ],
)
def test_explicit_aliases_are_normalized(alias, canonical):
    match = _match(CVProfile(skills=[alias]), tech_stack=[canonical])
    assert match["matched"] == [canonical]
    assert match["score"] == 100


def test_descriptions_use_recognized_vocabulary_not_filler_money_or_counts():
    match = _match(
        CVProfile(skills=["Python"]),
        description="Join our great team! Earn $120,000 with 5 years experience. Build Python services and PostgreSQL databases.",
    )
    assert match["matched"] == ["python"]
    assert match["missing"] == ["postgresql"]
    assert match["score"] == 50


def test_explicit_job_evidence_takes_precedence_over_description_and_nice_to_have():
    match = _match(
        CVProfile(skills=["Python"]),
        tech_stack=["Python"],
        requirements=["Experience with Docker."],
        description="Our historical platform was Java and Rust.",
        nice_to_have=["Kubernetes"],
    )
    assert match["matched"] == ["python"]
    assert match["missing"] == ["docker"]
    assert "explicit" in match["method"]


@pytest.mark.parametrize(
    "description",
    [
        "",
        "We are hiring! Join our team.",
        "Salary $120,000. Requires 5 years. Go above and beyond. Spring into action.",
    ],
)
def test_no_useful_job_evidence_means_no_numeric_score(description):
    match = _match(_cv(), description=description)
    assert match["score"] is None
    assert match["matched"] == match["missing"] == []


def test_unrecognized_explicit_prose_falls_back_to_description():
    match = _match(
        _cv(),
        requirements=["We are hiring", "5 years experience"],
        description="Build in Python.",
    )
    assert match["matched"] == ["python"]
    assert match["score"] == 100


def test_custom_explicit_technology_has_exact_missing_and_supported_evidence():
    match = _match(CVProfile(skills=["Elixir"]), tech_stack=["Elixir", "COBOL"])
    assert match["matched"] == ["elixir"]
    assert match["missing"] == ["cobol"]
    assert match["score"] == 50


def test_candidate_facts_include_projects_and_achievements_but_not_raw_text():
    cv = CVProfile(
        projects=[
            Project(
                name="Demo", description="Built using Node.js", technologies=["Docker"]
            )
        ],
        experiences=[
            Experience(
                title="Developer",
                company="Example",
                duration="2025",
                achievements=["Built Python APIs."],
            )
        ],
        raw_text="Technical Skills\nPostgreSQL",
    )
    match = _match(cv, tech_stack=["NodeJS", "Python", "Docker", "Postgres"])
    assert match["matched"] == ["docker", "node.js", "python"]
    assert match["missing"] == ["postgresql"]
    assert match["score"] == 75


def test_employer_names_and_contact_urls_are_not_skill_claims():
    cv = CVProfile(
        name="Java Python",
        github="https://github.com/Rust",
        email="sql@example.com",
        experiences=[Experience(title="Developer", company="Docker", duration="2025")],
    )
    match = _match(cv, tech_stack=["Java", "Python", "Rust", "SQL", "Docker"])
    assert match["score"] == 0
    assert not match["matched"]


def test_reordering_and_repeating_keywords_does_not_improve_job_alignment():
    cv = _cv()
    job = JobPosting(
        title="Engineer", company="Example", tech_stack=["Python", "Docker", "Rust"]
    )
    before = assess_resume(cv, job)
    reordered = cv.model_copy(update={"skills": list(reversed(cv.skills)) * 10})
    after = assess_resume(reordered, job)
    assert before["job_match"] == after["job_match"]
    assert before["readiness_score"] == after["readiness_score"]


def test_assessment_does_not_mutate_profile_or_job_and_explains_score_limits():
    cv = _cv()
    job = JobPosting(title="Engineer", company="Example", tech_stack=["Rust"])
    original = cv.model_dump(), job.model_dump()
    result = assess_resume(cv, job)
    assert (cv.model_dump(), job.model_dump()) == original
    assert result["job_match"]["missing"] == ["rust"]
    assert "not an ATS vendor score" in result["job_match"]["method"]


def test_raw_extraction_identity_contacts_and_employers_never_inflate_coverage():
    cv = CVProfile(
        name="Alex Rust",
        email="sql@example.test",
        raw_text="Alex Rust\nEmail: sql@example.test\nClerk at Docker",
        experiences=[Experience(title="Clerk", company="Docker", duration="2025")],
    )
    match = _match(cv, tech_stack=["Rust", "SQL", "Docker"])
    assert match["score"] == 0
    assert match["matched"] == []
    assert match["missing"] == ["docker", "rust", "sql"]


@pytest.mark.parametrize(
    "summary",
    [
        "I have no experience with Python.",
        "I do not know Python.",
        "I have never used Python.",
        "I am unfamiliar with Python.",
        "I work without Python.",
        "I lack Python experience.",
        "Our product is Python-free.",
    ],
)
def test_clear_candidate_negation_is_not_positive_skill_evidence(summary):
    match = _match(CVProfile(summary=summary), tech_stack=["Python"])
    assert match["score"] == 0
    assert match["matched"] == []


def test_negative_project_role_and_custom_technology_mentions_are_not_evidence():
    cv = CVProfile(
        projects=[Project(name="Tool", description="Built the tool without Elixir.")],
        experiences=[
            Experience(
                title="Developer",
                company="Example",
                duration="2025",
                achievements=["No Python experience."],
            )
        ],
    )
    match = _match(cv, tech_stack=["Python", "Elixir"])
    assert match["score"] == 0


@pytest.mark.parametrize(
    "description",
    [
        "No Python experience required. We work in Java.",
        "Python is not required; use Java.",
        "We do not use Python, but use Java.",
        "Python experience is unnecessary. Build Java services.",
    ],
)
def test_negative_job_mentions_are_not_required_signals(description):
    match = _match(CVProfile(skills=["Java"]), description=description)
    assert match["matched"] == ["java"]
    assert match["missing"] == []
    assert match["score"] == 100


def test_negation_in_explicit_requirement_is_suppressed_and_positive_requirement_retained():
    match = _match(
        CVProfile(skills=["Java"]),
        requirements=["No Python experience required", "Java"],
    )
    assert match["matched"] == ["java"]
    assert match["missing"] == []


def test_separate_positive_evidence_survives_candidate_negation():
    match = _match(
        CVProfile(
            summary="No Python experience, but built Java applications. Used Docker to deploy them."
        ),
        tech_stack=["Python", "Java", "Docker"],
    )
    assert match["matched"] == ["docker", "java"]
    assert match["missing"] == ["python"]


def test_mixed_negative_clause_abstains_instead_of_guessing_scope():
    match = _match(
        CVProfile(summary="Used Python, not Java."), tech_stack=["Python", "Java"]
    )
    assert match["matched"] == []
    assert match["score"] == 0


def test_c_level_title_cannot_claim_c_programming():
    match = _match(
        CVProfile(summary="C-level stakeholder management"), tech_stack=["C"]
    )
    assert match["score"] == 0


@pytest.mark.parametrize(
    "evidence",
    [
        "Built services in the C language.",
        "Practised C programming.",
        "Experienced in programming in C.",
    ],
)
def test_unambiguous_c_programming_prose_is_positive(evidence):
    match = _match(CVProfile(summary=evidence), tech_stack=["C", "C++", "C#"])
    assert match["matched"] == ["c"]
    assert match["missing"] == ["c#", "c++"]


def test_bare_c_is_still_valid_as_an_explicit_skill():
    assert _match(CVProfile(skills=["C"]), tech_stack=["C"])["score"] == 100


def test_contact_identifiers_embedded_in_summary_are_not_skills():
    match = _match(
        CVProfile(
            summary="Email sql@example.test or visit https://example.test/Python"
        ),
        tech_stack=["SQL", "Python"],
    )
    assert match["score"] == 0


@pytest.mark.parametrize(
    "summary",
    [
        "I don’t have experience with Python.",
        "I haven't used Python.",
        "The team hasn’t used Python.",
        "I hadn’t used Python before.",
        "I couldn’t program in Python.",
        "I wouldn't claim Python experience.",
        "I shouldn’t list Python as a skill.",
    ],
)
def test_common_straight_and_smart_quote_negation_contractions_are_suppressed(summary):
    match = _match(CVProfile(summary=summary), tech_stack=["Python"])
    assert match["score"] == 0


def test_contracted_negative_job_clause_does_not_create_a_requirement():
    match = _match(
        CVProfile(skills=["Java"]),
        description="You don’t need Python. Build Java services.",
    )
    assert match["matched"] == ["java"]
    assert match["missing"] == []
