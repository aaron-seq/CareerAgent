"""Tests for cover letter generation.

The point of these is the truthfulness gate. A letter that reads well but
claims a metric or employer the candidate never had is the worst possible
output: it is confident, plausible, and gets the candidate caught out in an
interview. So generation must fail loudly rather than ship an unverifiable
claim (CLAUDE.md guardrail 4).
"""

from unittest.mock import Mock

import pytest

from core.models import CVProfile, Experience, JobPosting
from core.resume import FabricationError, generate_cover_letter, verify_grounded


def _cv():
    return CVProfile(
        name="Aaron Sequeira",
        summary="Full-Stack AI Engineer",
        skills=["Python", "RAG", "FastAPI"],
        experiences=[
            Experience(
                title="Software Engineering Intern",
                company="Baker Hughes",
                duration="09/24 - 09/25",
                achievements=["Built a document intelligence system"],
                metrics=["Reduced service downtime by 70%", "Cut manual entry by 75%"],
                technologies=["Power Platform"],
            )
        ],
    )


def _job(description="Looking for a RAG engineer."):
    return JobPosting(
        title="AI Engineer",
        company="Acme",
        url="https://acme.test/jobs/1",
        description=description,
    )


class TestVerifyGrounded:
    def test_metric_present_in_cv_is_accepted(self):
        letter = "At Baker Hughes I reduced service downtime by 70%."
        assert verify_grounded(_cv(), _job(), letter) == []

    def test_invented_metric_is_flagged(self):
        """The model likes round, impressive numbers it was never given"""
        letter = "I improved throughput by 300% and cut costs by 45%."
        flagged = verify_grounded(_cv(), _job(), letter)
        assert any("300" in f for f in flagged)
        assert any("45" in f for f in flagged)

    def test_number_quoted_from_the_posting_is_allowed(self):
        """Citing the job ad's own figure is not a claim about the candidate"""
        job = _job(description="Join our team of 40+ engineers.")
        assert verify_grounded(_cv(), job, "Your team of 40+ engineers appeals.") == []

    def test_comma_formatting_does_not_cause_false_positives(self):
        cv = _cv()
        cv.experiences[0].metrics.append("Processed 2100+ samples")
        assert verify_grounded(cv, _job(), "I processed 2,100+ samples.") == []


class TestGenerateCoverLetter:
    def test_rejects_letter_citing_unsupported_metric(self):
        llm = Mock()
        llm.generate_json.return_value = {
            "letter": "I increased revenue by 500% single-handedly.",
            "gaps": [],
        }
        with pytest.raises(FabricationError, match="metrics absent"):
            generate_cover_letter(llm, _cv(), _job())

    def test_rejects_letter_naming_an_employer_not_in_the_cv(self):
        llm = Mock()
        llm.generate_json.return_value = {
            "letter": "During my years at Google I led the platform team.",
            "gaps": [],
        }
        with pytest.raises(FabricationError, match="employer not in the CV"):
            generate_cover_letter(llm, _cv(), _job())

    def test_accepts_grounded_letter_and_reports_gaps(self):
        llm = Mock()
        llm.generate_json.return_value = {
            "letter": (
                "Dear Hiring Manager,\n\nAt Baker Hughes I reduced service "
                "downtime by 70% building document automation. At Acme I would "
                "bring the same approach to your RAG stack.\n\nAaron"
            ),
            "gaps": ["No Kubernetes experience evidenced"],
        }
        letter, report = generate_cover_letter(llm, _cv(), _job())

        assert "Baker Hughes" in letter
        assert report.gaps == ["No Kubernetes experience evidenced"]
        assert report.word_count > 0
        assert any("70%" in m for m in report.cited_metrics)

    def test_empty_letter_fails_rather_than_returning_blank(self):
        llm = Mock()
        llm.generate_json.return_value = {"letter": "   ", "gaps": []}
        with pytest.raises(FabricationError):
            generate_cover_letter(llm, _cv(), _job())
