"""Tests for CV parsing.

Focus: the model must never be left to guess a contact URL. A CV renders
its links as anchor text ("Github") with the URL only in the PDF annotation
layer; when that layer was dropped the model invented a plausible-looking
profile URL from the candidate's name. Fabricated credentials are a hard no
(CLAUDE.md guardrail 4), and a guessed link 404s in front of a recruiter.
"""

from unittest.mock import MagicMock, Mock, patch

from core.cv_parser import CVParser


def _llm_returning(payload):
    llm = Mock()
    llm.generate_json.return_value = dict(payload)
    return llm


def _prompt_sent(llm):
    return llm.generate_json.call_args[0][0]


class TestHyperlinkRecovery:
    def test_links_reach_the_prompt(self):
        """Real URLs must be in the model's input, not inferred from a name"""
        llm = _llm_returning({"name": "Aaron Sequeira"})
        parser = CVParser(llm)

        parser.parse_text(
            "Aaron Sequeira\nSoftware Engineer\n" + "x" * 60,
            links=["https://github.com/aaron-seq", "https://linkedin.com/in/a"],
        )

        prompt = _prompt_sent(llm)
        assert "https://github.com/aaron-seq" in prompt
        assert "https://linkedin.com/in/a" in prompt

    def test_links_survive_truncation_of_a_long_cv(self):
        """Contact links sit at the end of a CV - naive truncation drops them"""
        llm = _llm_returning({"name": "A"})
        parser = CVParser(llm)

        parser.parse_text("y" * 30000, links=["https://github.com/aaron-seq"])

        assert "https://github.com/aaron-seq" in _prompt_sent(llm)

    def test_no_links_section_when_there_are_none(self):
        llm = _llm_returning({"name": "A"})
        parser = CVParser(llm)

        parser.parse_text("z" * 200, links=[])

        # Matches the appended block's header, not rule 2's mention of it.
        assert "real URLs behind" not in _prompt_sent(llm)

    @patch("core.cv_parser.pdfplumber.open")
    def test_extracts_and_dedupes_annotation_urls(self, mock_open):
        """Repeated project links appear once, in document order"""
        page = MagicMock()
        page.hyperlinks = [
            {"uri": "https://github.com/aaron-seq"},
            {"uri": "https://linkedin.com/in/a"},
            {"uri": "https://github.com/aaron-seq"},
        ]
        mock_open.return_value.__enter__.return_value.pages = [page]

        urls = CVParser(Mock())._extract_hyperlinks_from_pdf("cv.pdf")

        assert urls == ["https://github.com/aaron-seq", "https://linkedin.com/in/a"]

    @patch("core.cv_parser.pdfplumber.open", side_effect=OSError("unreadable"))
    def test_link_extraction_failure_is_non_fatal(self, mock_open):
        """A PDF with no annotation layer still parses, just without links"""
        assert CVParser(Mock())._extract_hyperlinks_from_pdf("cv.pdf") == []


class TestPromptGuardrails:
    def test_prompt_forbids_inventing_urls(self):
        """The rule the fix depends on must stay in the prompt"""
        from core.prompts import CV_PARSE_PROMPT

        assert "NEVER invent a URL" in CV_PARSE_PROMPT
        # The old placeholder taught the model to fill in a fake username.
        assert "github.com/username" not in CV_PARSE_PROMPT
