"""
Gmail integration for creating drafts
Uses OAuth2 for authentication, never sends emails automatically
"""

import os
import base64
from email.mime.text import MIMEText
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailDraftClient:
    """Gmail API client for draft creation only"""

    def __init__(
        self, credentials_path: str = "credentials.json", token_path: str = "token.json"
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None

    def authenticate(self) -> bool:
        """Authenticate with Gmail API using OAuth2"""
        creds = None

        # Load existing token
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception as e:
                print(f"Failed to load token: {e}")

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Token refresh failed: {e}")
                    creds = None

            if not creds:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {self.credentials_path}. "
                        "Please download OAuth2 credentials from Google Cloud Console."
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials
            with open(self.token_path, "w") as token:
                token.write(creds.to_json())

        try:
            self.service = build("gmail", "v1", credentials=creds)
            return True
        except Exception as e:
            raise Exception(f"Failed to build Gmail service: {e}")

    def create_draft(
        self, to: str, subject: str, body: str, sender: Optional[str] = None
    ) -> str:
        """Create a Gmail draft (does not send)"""

        if not self.service:
            raise Exception("Not authenticated. Call authenticate() first.")

        try:
            # Create message
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            if sender:
                message["from"] = sender

            # Encode message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Create draft
            draft = {"message": {"raw": raw_message}}

            result = (
                self.service.users().drafts().create(userId="me", body=draft).execute()
            )

            draft_id = result["id"]
            print(f"Draft created successfully with ID: {draft_id}")

            return draft_id

        except HttpError as error:
            raise Exception(f"Gmail API error: {error}")
        except Exception as e:
            raise Exception(f"Failed to create draft: {e}")

    def list_drafts(self, max_results: int = 10) -> list:
        """List existing drafts"""

        if not self.service:
            raise Exception("Not authenticated.")

        try:
            results = (
                self.service.users()
                .drafts()
                .list(userId="me", maxResults=max_results)
                .execute()
            )

            drafts = results.get("drafts", [])
            return drafts

        except HttpError as error:
            raise Exception(f"Failed to list drafts: {error}")

    def get_draft(self, draft_id: str) -> dict:
        """Get draft by ID"""

        if not self.service:
            raise Exception("Not authenticated.")

        try:
            draft = (
                self.service.users().drafts().get(userId="me", id=draft_id).execute()
            )

            return draft

        except HttpError as error:
            raise Exception(f"Failed to get draft: {error}")

    def delete_draft(self, draft_id: str) -> bool:
        """Delete a draft"""

        if not self.service:
            raise Exception("Not authenticated.")

        try:
            self.service.users().drafts().delete(userId="me", id=draft_id).execute()

            return True

        except HttpError as error:
            raise Exception(f"Failed to delete draft: {error}")
