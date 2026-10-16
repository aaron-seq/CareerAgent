"""Tests for core/ diagnostics going through stdlib logging (issue #31).

Every former bare ``print()`` in core/ is now a levelled log record. These
tests pin two things for each converted path:

1. the signal survives - a failure handled in an ``except`` still produces a
   WARNING record (with the exception attached), so nothing is swallowed;
2. no PII reaches the log - CV text, candidate names, recipient addresses and
   email bodies must never appear in a record's rendered message or
   traceback.

All external services (LLM, DuckDuckGo, HTTP, Google OAuth, PDF readers) are
mocked; no network calls.
"""

import logging
from unittest.mock import Mock, patch

import pytest

from core.contact_finder import ContactFinder
from core.cv_parser import CVParser
from core.gmail_drafts import GmailDraftClient
from core.job_finder import JobFinder
from core.logging_config import LOG_LEVEL_ENV, configure_logging
from core.models import SearchQuery

CANDIDATE_NAME = "Jane Privateperson"
CANDIDATE_EMAIL = "jane.privateperson@example.com"
CANDIDATE_PHONE = "+1 555 0100 4242"
CV_TEXT = (
    f"{CANDIDATE_NAME}\n{CANDIDATE_EMAIL}\n{CANDIDATE_PHONE}\n"
    "Senior engineer with ten years of distributed systems experience.\n"
)


def _rendered(caplog: pytest.LogCaptureFixture) -> str:
    """Everything a handler could emit: messages plus formatted tracebacks."""
    formatter = logging.Formatter()
    parts = []
    for record in caplog.records:
        parts.append(record.getMessage())
        if record.exc_info:
            parts.append(formatter.formatException(record.exc_info))
    return "\n".join(parts)


def _assert_no_pii(caplog: pytest.LogCaptureFixture) -> None:
    text = _rendered(caplog)
    for secret in (CANDIDATE_NAME, CANDIDATE_EMAIL, CANDIDATE_PHONE, "ten years"):
        assert secret not in text


def _warnings(caplog: pytest.LogCaptureFixture, logger: str) -> list:
    return [
        r for r in caplog.records if r.name == logger and r.levelno == logging.WARNING
    ]


class TestNoPrintsInCore:
    def test_no_bare_print_calls_remain(self):
        """Regression guard: diagnostics in core/ must go through logging"""
        import pathlib
        import re

        core = pathlib.Path(__file__).resolve().parent.parent / "core"
        offenders = [
            f"{path.relative_to(core.parent)}:{lineno}"
            for path in core.rglob("*.py")
            for lineno, line in enumerate(path.read_text().splitlines(), 1)
            if re.match(r"\s*print\(", line)
        ]
        assert offenders == []


class TestCVParserLogging:
    def test_debug_records_carry_size_not_cv_text(self, caplog):
        llm = Mock()
        llm.generate_json.return_value = {"name": CANDIDATE_NAME}
        caplog.set_level(logging.DEBUG, logger="core.cv_parser")

        CVParser(llm).parse_text(CV_TEXT * 2)

        debug = [r for r in caplog.records if r.name == "core.cv_parser"]
        assert debug and all(r.levelno == logging.DEBUG for r in debug)
        assert any("chars" in r.getMessage() for r in debug)
        _assert_no_pii(caplog)

    @patch("core.cv_parser.PyPDF2.PdfReader", side_effect=RuntimeError("bad xref"))
    @patch("core.cv_parser.pdfplumber.open", side_effect=RuntimeError("bad header"))
    def test_extraction_failures_are_logged_as_warnings(
        self, _plumber, _pypdf, tmp_path, caplog
    ):
        pdf = tmp_path / "cv.pdf"
        pdf.write_bytes(b"%PDF-1.4 not really")
        caplog.set_level(logging.DEBUG, logger="core.cv_parser")

        with pytest.raises(ValueError, match="Could not extract text"):
            CVParser(Mock())._extract_text_from_pdf(str(pdf))

        records = _warnings(caplog, "core.cv_parser")
        assert len(records) == 2
        assert "pdfplumber" in records[0].getMessage()
        assert "PyPDF2" in records[1].getMessage()
        assert all(r.exc_info for r in records)
        _assert_no_pii(caplog)

    @patch("core.cv_parser.pdfplumber.open", side_effect=RuntimeError("no annots"))
    def test_hyperlink_failure_is_non_fatal_but_logged(self, _plumber, caplog):
        caplog.set_level(logging.DEBUG, logger="core.cv_parser")

        assert CVParser(Mock())._extract_hyperlinks_from_pdf("cv.pdf") == []

        records = _warnings(caplog, "core.cv_parser")
        assert len(records) == 1
        assert "hyperlink" in records[0].getMessage()
        assert records[0].exc_info


class TestContactFinderLogging:
    def test_failed_search_query_is_logged_and_skipped(self, caplog):
        llm = Mock()
        llm.generate_json.return_value = ["q1", "q2"]
        finder = ContactFinder(llm)
        finder.ddgs = Mock()
        finder.ddgs.text.side_effect = RuntimeError("rate limited")
        caplog.set_level(logging.DEBUG, logger="core.contact_finder")

        with patch("core.contact_finder.time.sleep"):
            assert finder.find_contacts("Acme", "Engineer") == []

        records = _warnings(caplog, "core.contact_finder")
        assert len(records) == 2
        assert all(r.exc_info for r in records)


class TestJobFinderLogging:
    def test_unparseable_result_is_logged_and_skipped(self, caplog):
        finder = JobFinder(Mock())
        finder.ddgs = Mock()
        finder.ddgs.text.return_value = [{"title": "x"}]
        caplog.set_level(logging.DEBUG, logger="core.job_finder")

        with patch.object(finder, "_is_job_related", side_effect=KeyError("href")):
            assert finder.search_jobs(SearchQuery(query="engineer")) == []

        records = _warnings(caplog, "core.job_finder")
        assert len(records) == 1
        assert records[0].exc_info

    @patch("core.job_finder.requests.get", side_effect=RuntimeError("timeout"))
    def test_failed_job_fetch_is_logged_with_url(self, _get, caplog):
        caplog.set_level(logging.DEBUG, logger="core.job_finder")
        url = "https://jobs.example.com/123"

        assert JobFinder(Mock()).fetch_job_details(url) is None

        records = _warnings(caplog, "core.job_finder")
        assert len(records) == 1
        assert url in records[0].getMessage()
        assert records[0].exc_info


class TestGmailDraftsLogging:
    @patch("core.gmail_drafts.build")
    @patch("core.gmail_drafts.Credentials")
    def test_unreadable_token_is_logged_without_its_contents(
        self, mock_credentials_cls, _build, caplog, tmp_path
    ):
        secret = "ya29.SECRET-REFRESH-TOKEN"
        mock_credentials_cls.from_authorized_user_file.side_effect = ValueError(
            f"bad token payload {secret}"
        )
        caplog.set_level(logging.DEBUG, logger="core.gmail_drafts")
        client = GmailDraftClient(
            credentials_path=str(tmp_path / "missing.json"),
            token_path=str(tmp_path / "token.json"),
        )

        with patch("core.gmail_drafts.os.path.exists", side_effect=[True, False]):
            with pytest.raises(FileNotFoundError):
                client.authenticate()

        records = _warnings(caplog, "core.gmail_drafts")
        assert len(records) == 1
        assert "ValueError" in records[0].getMessage()
        assert secret not in _rendered(caplog)

    @patch("core.gmail_drafts.build")
    @patch("core.gmail_drafts.Request")
    @patch("core.gmail_drafts.Credentials")
    def test_failed_refresh_is_logged_without_token_details(
        self, mock_credentials_cls, _request, _build, caplog, tmp_path
    ):
        secret = "1//SECRET-REFRESH-TOKEN"
        creds = Mock(valid=False, expired=True, refresh_token=secret)
        creds.refresh.side_effect = RuntimeError(f"invalid_grant for {secret}")
        mock_credentials_cls.from_authorized_user_file.return_value = creds
        caplog.set_level(logging.DEBUG, logger="core.gmail_drafts")
        client = GmailDraftClient(
            credentials_path=str(tmp_path / "missing.json"),
            token_path=str(tmp_path / "token.json"),
        )

        with patch("core.gmail_drafts.os.path.exists", side_effect=[True, False]):
            with pytest.raises(FileNotFoundError):
                client.authenticate()

        records = _warnings(caplog, "core.gmail_drafts")
        assert len(records) == 1
        assert "refresh" in records[0].getMessage()
        assert secret not in _rendered(caplog)

    def test_draft_creation_logs_id_not_recipient_or_body(self, caplog):
        client = GmailDraftClient(credentials_path="c.json", token_path="t.json")
        client.service = Mock()
        client.service.users().drafts().create().execute.return_value = {
            "id": "draft123"
        }
        caplog.set_level(logging.DEBUG, logger="core.gmail_drafts")

        client.create_draft(CANDIDATE_EMAIL, "Hello", f"Hi, I'm {CANDIDATE_NAME}")

        messages = [r.getMessage() for r in caplog.records]
        assert any("draft123" in m for m in messages)
        _assert_no_pii(caplog)


class TestConfigureLogging:
    @pytest.fixture(autouse=True)
    def _restore_logging_state(self):
        """basicConfig mutates the root logger; undo it so no handler or
        level leaks into later tests."""
        root, core_logger = logging.getLogger(), logging.getLogger("core")
        handlers, root_level, core_level = (
            root.handlers[:],
            root.level,
            core_logger.level,
        )
        yield
        for handler in root.handlers[:]:
            if handler not in handlers:
                root.removeHandler(handler)
        root.setLevel(root_level)
        core_logger.setLevel(core_level)

    def test_level_comes_from_env(self, monkeypatch):
        monkeypatch.setenv(LOG_LEVEL_ENV, "debug")
        configure_logging()
        assert logging.getLogger("core").level == logging.DEBUG

    def test_defaults_to_info(self, monkeypatch):
        monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
        configure_logging()
        assert logging.getLogger("core").level == logging.INFO

    def test_unknown_level_falls_back_to_info(self, monkeypatch):
        monkeypatch.setenv(LOG_LEVEL_ENV, "chatty")
        configure_logging()
        assert logging.getLogger("core").level == logging.INFO
