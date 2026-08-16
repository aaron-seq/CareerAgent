"""Tests for GmailDraftClient (OAuth2 Gmail draft-only integration)

Google APIs are mocked per CLAUDE.md -- no live network/OAuth calls in the
checked-in suite. Live testing this session confirmed (not checked in, no
real OAuth credentials available) that authenticate() fails loudly with a
clear, actionable FileNotFoundError when credentials.json is missing, and
create_draft() refuses to run before authenticate() -- both are exercised
here.
"""

from unittest.mock import Mock, mock_open, patch

import pytest
from googleapiclient.errors import HttpError

from core.gmail_drafts import GmailDraftClient


def _client(**kwargs):
    return GmailDraftClient(
        credentials_path=kwargs.get("credentials_path", "credentials.json"),
        token_path=kwargs.get("token_path", "token.json"),
    )


def _http_error(status=404, reason="Not Found"):
    resp = Mock(status=status, reason=reason)
    return HttpError(resp, b"error body")


class TestAuthenticate:
    @patch("core.gmail_drafts.os.path.exists", return_value=False)
    def test_missing_credentials_raises_actionable_error(self, _exists):
        client = _client()
        with pytest.raises(FileNotFoundError, match="Gmail credentials not found"):
            client.authenticate()

    @patch("core.gmail_drafts.build")
    @patch("core.gmail_drafts.InstalledAppFlow")
    @patch("builtins.open", new_callable=mock_open)
    @patch("core.gmail_drafts.os.path.exists")
    def test_runs_oauth_flow_when_no_token(
        self, mock_exists, _mock_open, mock_flow_cls, mock_build
    ):
        # token.json absent, credentials.json present.
        mock_exists.side_effect = lambda path: path == "credentials.json"
        mock_creds = Mock(valid=True)
        mock_creds.to_json.return_value = "{}"
        mock_flow = Mock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow
        mock_build.return_value = Mock()

        client = _client()
        assert client.authenticate() is True
        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            "credentials.json", ["https://www.googleapis.com/auth/gmail.compose"]
        )
        assert client.service is not None

    @patch("core.gmail_drafts.build", side_effect=Exception("build failed"))
    @patch("core.gmail_drafts.InstalledAppFlow")
    @patch("builtins.open", new_callable=mock_open)
    @patch("core.gmail_drafts.os.path.exists")
    def test_service_build_failure_is_surfaced(
        self, mock_exists, _mock_open, mock_flow_cls, _mock_build
    ):
        mock_exists.side_effect = lambda path: path == "credentials.json"
        mock_creds = Mock(valid=True)
        mock_creds.to_json.return_value = "{}"
        mock_flow = Mock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        client = _client()
        with pytest.raises(Exception, match="Failed to build Gmail service"):
            client.authenticate()

    @patch("core.gmail_drafts.build")
    @patch("core.gmail_drafts.Credentials")
    @patch("core.gmail_drafts.os.path.exists", return_value=True)
    def test_reuses_valid_existing_token(
        self, _exists, mock_credentials_cls, mock_build
    ):
        mock_creds = Mock(valid=True)
        mock_credentials_cls.from_authorized_user_file.return_value = mock_creds
        mock_build.return_value = Mock()

        client = _client()
        assert client.authenticate() is True
        mock_build.assert_called_once()


class TestCreateDraft:
    def test_refuses_without_authentication(self):
        client = _client()
        with pytest.raises(Exception, match="Not authenticated"):
            client.create_draft("to@example.com", "Subject", "Body")

    def test_creates_draft_and_returns_id(self):
        client = _client()
        client.service = Mock()
        client.service.users().drafts().create().execute.return_value = {
            "id": "draft123"
        }

        draft_id = client.create_draft("to@example.com", "Subject", "Body text")
        assert draft_id == "draft123"

    def test_wraps_http_error(self):
        client = _client()
        client.service = Mock()
        client.service.users().drafts().create().execute.side_effect = _http_error()

        with pytest.raises(Exception, match="Gmail API error"):
            client.create_draft("to@example.com", "Subject", "Body")


class TestListGetDeleteDraft:
    def test_list_drafts_refuses_without_authentication(self):
        client = _client()
        with pytest.raises(Exception, match="Not authenticated"):
            client.list_drafts()

    def test_list_drafts_returns_list(self):
        client = _client()
        client.service = Mock()
        client.service.users().drafts().list().execute.return_value = {
            "drafts": [{"id": "d1"}, {"id": "d2"}]
        }
        drafts = client.list_drafts()
        assert len(drafts) == 2

    def test_get_draft_refuses_without_authentication(self):
        client = _client()
        with pytest.raises(Exception, match="Not authenticated"):
            client.get_draft("d1")

    def test_get_draft_returns_draft(self):
        client = _client()
        client.service = Mock()
        client.service.users().drafts().get().execute.return_value = {"id": "d1"}
        assert client.get_draft("d1") == {"id": "d1"}

    def test_delete_draft_refuses_without_authentication(self):
        client = _client()
        with pytest.raises(Exception, match="Not authenticated"):
            client.delete_draft("d1")

    def test_delete_draft_returns_true_on_success(self):
        client = _client()
        client.service = Mock()
        client.service.users().drafts().delete().execute.return_value = {}
        assert client.delete_draft("d1") is True

    def test_delete_draft_wraps_http_error(self):
        client = _client()
        client.service = Mock()
        client.service.users().drafts().delete().execute.side_effect = _http_error()
        with pytest.raises(Exception, match="Failed to delete draft"):
            client.delete_draft("d1")
