"""Tests for ContactFinder (DuckDuckGo-backed hiring-contact discovery)

External APIs (DuckDuckGo, LLM) are mocked per CLAUDE.md -- no live network
calls in the checked-in suite. Live testing this session (not checked in)
found `_extract_name_from_title` misfired on all-caps and non-name titles
("TALENT ACQUISITION TEAM", "Hiring Committee") -- see the regression tests
below, which cover exactly the inputs that misfired before the fix.
"""

from unittest.mock import Mock, patch

import pytest

from core.contact_finder import ContactFinder
from core.models import ContactCandidate


def _finder():
    llm = Mock()
    finder = ContactFinder(llm)
    finder.ddgs = Mock()
    return finder, llm


class TestExtractRoleKeyword:
    def test_matches_known_keyword(self):
        finder, _ = _finder()
        assert finder._extract_role_keyword("Senior Software Engineer") == "engineer"

    def test_falls_back_to_first_word(self):
        finder, _ = _finder()
        assert finder._extract_role_keyword("Recruiter Extraordinaire") == "Recruiter"

    def test_empty_title_falls_back_to_manager(self):
        finder, _ = _finder()
        assert finder._extract_role_keyword("") == "manager"


class TestGenerateEmailPermutations:
    def test_generates_top_three_patterns_with_decreasing_confidence(self):
        finder, _ = _finder()
        candidates = finder.generate_email_permutations("Jane", "Smith", "acme.com")
        assert len(candidates) == 3
        assert all(isinstance(c, ContactCandidate) for c in candidates)
        assert [c.email for c in candidates] == [
            "jane.smith@acme.com",
            "jane@acme.com",
            "janesmith@acme.com",
        ]
        assert all(c.email_confidence == "guessed" for c in candidates)
        scores = [c.confidence_score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_strips_at_prefix_from_domain(self):
        finder, _ = _finder()
        candidates = finder.generate_email_permutations(
            "Jane", "Smith", "user@acme.com"
        )
        assert candidates[0].email == "jane.smith@acme.com"

    def test_lowercases_and_strips_names(self):
        finder, _ = _finder()
        candidates = finder.generate_email_permutations(
            "  Jane ", " SMITH ", "ACME.com"
        )
        assert candidates[0].email == "jane.smith@acme.com"
        assert candidates[0].name == "  Jane   SMITH "


class TestExtractNameFromTitle:
    """Regression coverage for the fragile-capitalization bug found via
    live testing: the original heuristic treated any two capitalized words
    as a name, so all-caps job/team labels and recruiting phrases were
    mistaken for a person's name.
    """

    def test_linkedin_pattern_extracts_name(self):
        finder, _ = _finder()
        assert (
            finder._extract_name_from_title("Jane Smith - Senior Recruiter | LinkedIn")
            == "Jane Smith"
        )

    def test_linkedin_pattern_with_credentials(self):
        finder, _ = _finder()
        assert (
            finder._extract_name_from_title("John Doe, PhD - Head of Talent | LinkedIn")
            == "John Doe, PhD"
        )

    def test_plain_two_capitalized_words_extracts_name(self):
        finder, _ = _finder()
        assert finder._extract_name_from_title("Maria Garcia") == "Maria Garcia"

    def test_rejects_all_caps_team_label(self):
        finder, _ = _finder()
        assert finder._extract_name_from_title("TALENT ACQUISITION TEAM") is None

    def test_rejects_hiring_committee_phrase(self):
        finder, _ = _finder()
        assert finder._extract_name_from_title("Hiring Committee") is None

    def test_rejects_all_caps_role_title(self):
        finder, _ = _finder()
        assert (
            finder._extract_name_from_title("ENGINEERING MANAGER AT ANTHROPIC") is None
        )

    def test_rejects_generic_cta_phrase(self):
        finder, _ = _finder()
        assert (
            finder._extract_name_from_title("APPLY NOW - Software Engineer Position")
            is None
        )
        assert finder._extract_name_from_title("We Are Hiring - Join Our Team") is None

    def test_single_word_title_returns_none(self):
        finder, _ = _finder()
        assert finder._extract_name_from_title("Anthropic") is None


class TestExtractEmail:
    def test_finds_email_in_text(self):
        finder, _ = _finder()
        assert (
            finder._extract_email("Contact Jane at jane.smith@acme.com for details")
            == "jane.smith@acme.com"
        )

    def test_returns_none_when_absent(self):
        finder, _ = _finder()
        assert finder._extract_email("No email here") is None


class TestExtractRole:
    def test_extracts_role_around_keyword(self):
        finder, _ = _finder()
        role = finder._extract_role("Jane Smith Engineering Manager", "")
        assert "Manager" in role

    def test_unknown_role_when_no_keyword(self):
        finder, _ = _finder()
        assert finder._extract_role("Jane Smith", "") == "Unknown Role"


class TestCalculateConfidence:
    def test_base_score_with_nothing(self):
        finder, _ = _finder()
        assert finder._calculate_confidence(None, None, "Acme", "") == pytest.approx(
            0.3
        )

    def test_full_score_capped_at_one(self):
        finder, _ = _finder()
        score = finder._calculate_confidence(
            "a@acme.com", "https://linkedin.com/in/x", "Acme", "Works at Acme"
        )
        assert score == pytest.approx(1.0)


class TestFindContacts:
    @patch("core.contact_finder.time.sleep")
    def test_uses_llm_queries_and_dedupes_by_name(self, _sleep):
        finder, llm = _finder()
        llm.generate_json.return_value = ["Acme hiring manager engineer"]
        finder.ddgs.text.return_value = [
            {
                "title": "Jane Smith - Recruiter | LinkedIn",
                "body": "Works at Acme",
                "href": "https://linkedin.com/in/janesmith",
            },
            {
                "title": "Jane Smith - Recruiter | LinkedIn",
                "body": "Works at Acme",
                "href": "https://linkedin.com/in/janesmith",
            },
        ]
        contacts = finder.find_contacts("Acme", "Software Engineer")
        assert len(contacts) == 1
        assert contacts[0].name == "Jane Smith"

    @patch("core.contact_finder.time.sleep")
    def test_falls_back_to_default_queries_when_llm_fails(self, _sleep):
        finder, llm = _finder()
        llm.generate_json.side_effect = Exception("LLM down")
        finder.ddgs.text.return_value = []
        contacts = finder.find_contacts("Acme", "Software Engineer")
        assert contacts == []
        called_query = finder.ddgs.text.call_args_list[0][0][0]
        assert "Acme" in called_query

    @patch("core.contact_finder.time.sleep")
    def test_continues_past_a_failed_query(self, _sleep):
        finder, llm = _finder()
        llm.generate_json.return_value = ["query one", "query two"]
        finder.ddgs.text.side_effect = [
            Exception("202 Ratelimit"),
            [
                {
                    "title": "Jane Smith - Recruiter | LinkedIn",
                    "body": "",
                    "href": "https://linkedin.com/in/janesmith",
                }
            ],
        ]
        contacts = finder.find_contacts("Acme", "Software Engineer")
        assert len(contacts) == 1

    def test_dict_queries_are_flattened_to_values(self):
        finder, llm = _finder()
        llm.generate_json.return_value = {"q1": "query one", "q2": "query two"}
        finder.ddgs.text.return_value = []
        finder.find_contacts("Acme", "Software Engineer")
        # Both dict values were used as queries (order-independent).
        called = {c[0][0] for c in finder.ddgs.text.call_args_list}
        assert called == {"query one", "query two"}
