"""
Local storage for drafts and export to JSON/ZIP
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import List
from zipfile import ZipFile

from .db.crypto import decrypt_payload, encrypt_payload
from .models import CVProfile, EmailDraft, JobPosting, WhatsAppDraft


class LocalStorage:
    """Manage local storage of drafts and artifacts"""

    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = (
            storage_dir or os.getenv("STORAGE_PATH") or "careeragent_data"
        )
        self._ensure_directories()

    def _ensure_directories(self):
        """Create storage directories if they don't exist"""
        dirs = [
            self.storage_dir,
            os.path.join(self.storage_dir, "email_drafts"),
            os.path.join(self.storage_dir, "whatsapp_drafts"),
            os.path.join(self.storage_dir, "cv_profiles"),
            os.path.join(self.storage_dir, "job_postings"),
            os.path.join(self.storage_dir, "exports"),
        ]

        for dir_path in dirs:
            os.makedirs(dir_path, exist_ok=True)

    def _new_path(self, subdir: str, name: str, suffix: str) -> str:
        # Source/LLM-provided company names are labels, never path components.
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name).strip("._")[:80] or "artifact"
        descriptor, path = tempfile.mkstemp(
            dir=os.path.join(self.storage_dir, subdir),
            prefix=f"{safe_name}_",
            suffix=suffix,
        )
        os.close(descriptor)  # mkstemp gives each artifact a unique, mode-0600 file
        return path

    def _save_json(self, subdir: str, name: str, data: dict) -> str:
        payload = encrypt_payload(data)
        filepath = self._new_path(subdir, name, ".json")
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        return filepath

    def encrypt_legacy_artifacts(self) -> int:
        """Explicitly migrate plaintext JSON after the user backs up data/key.

        Each replacement is atomic and private. New-format files are verified
        and left intact, so an interrupted migration can be rerun safely.
        Readable exports are deliberately outside this migration.
        """
        changed = 0
        for subdir in (
            "email_drafts",
            "whatsapp_drafts",
            "cv_profiles",
            "job_postings",
        ):
            for path in Path(self.storage_dir, subdir).glob("*.json"):
                if path.is_symlink() or not path.is_file():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("format") == "careeragent.fernet.v1":
                    decrypt_payload(data)  # verify the key, without rewriting
                    continue
                payload = encrypt_payload(data)
                with tempfile.NamedTemporaryFile(
                    dir=path.parent,
                    mode="w",
                    encoding="utf-8",
                    suffix=".part",
                    delete=False,
                ) as file:
                    temporary = Path(file.name)
                    json.dump(payload, file)
                try:
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
                changed += 1
        return changed

    def save_email_draft(self, draft: EmailDraft) -> str:
        """Save an authenticated, encrypted JSON payload."""
        return self._save_json(
            "email_drafts", f"email_{draft.company}", draft.model_dump()
        )

    def save_whatsapp_draft(self, draft: WhatsAppDraft) -> str:
        """Save WhatsApp draft as JSON"""
        return self._save_json(
            "whatsapp_drafts", f"whatsapp_{draft.company}", draft.model_dump()
        )

    def save_cv_profile(self, profile: CVProfile) -> str:
        """Save CV profile as JSON"""
        return self._save_json("cv_profiles", "cv_profile", profile.model_dump())

    def save_job_posting(self, job: JobPosting) -> str:
        """Save job posting as JSON"""
        return self._save_json("job_postings", f"job_{job.company}", job.model_dump())

    def export_to_markdown(self, draft: EmailDraft) -> str:
        """Export email draft as markdown"""
        filepath = self._new_path("exports", f"email_{draft.company}", ".md")

        markdown = f"""# Email Draft for {draft.job_title} at {draft.company}

**Created:** {draft.created_at}
**Recipient:** {draft.recipient_name or "TBD"}
**To:** {draft.recipient_email or "TBD"}

---

## Subject

{draft.subject}

---

## Body

{draft.body}

---

## Metadata

- **Word Count:** {draft.word_count}
- **Job Title:** {draft.job_title}
- **Company:** {draft.company}
- **Gmail Draft ID:** {draft.gmail_draft_id or "Not created"}

---

## Personalization Plan

**Angle:** {draft.personalization_plan.angle if draft.personalization_plan else "N/A"}

**Technical Hook:** {draft.personalization_plan.technical_hook if draft.personalization_plan else "N/A"}

**Impact Hook:** {draft.personalization_plan.impact_hook if draft.personalization_plan else "N/A"}

**Company Hook:** {draft.personalization_plan.company_hook if draft.personalization_plan else "N/A"}

---

*Generated by CareerAgent - Local AI Career Agent*
"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)

        return filepath

    def create_export_zip(self, name: str = "careeragent_export") -> str:
        """Explicitly export readable content, including personal data."""
        zip_filepath = self._new_path("exports", name, ".zip")

        with ZipFile(zip_filepath, "w") as zipf:
            # Add all JSON files
            for root, dirs, files in os.walk(self.storage_dir):
                for file in files:
                    if file.endswith((".json", ".md")):
                        file_path = os.path.join(root, file)
                        if Path(file_path).is_symlink():
                            continue
                        arcname = os.path.relpath(file_path, self.storage_dir)
                        if file.endswith(".json"):
                            with open(file_path, encoding="utf-8") as source:
                                data = decrypt_payload(json.load(source))
                            zipf.writestr(arcname, json.dumps(data, indent=2))
                        else:
                            zipf.write(file_path, arcname)

        return zip_filepath

    def list_email_drafts(self) -> List[str]:
        """List all saved email drafts"""
        draft_dir = os.path.join(self.storage_dir, "email_drafts")
        return [f for f in os.listdir(draft_dir) if f.endswith(".json")]

    def load_email_draft(self, filename: str) -> EmailDraft:
        """Load email draft from JSON"""
        directory = Path(self.storage_dir, "email_drafts").resolve()
        filepath = (directory / filename).resolve()
        if (
            Path(filename).name != filename
            or "\\" in filename
            or filepath.parent != directory
        ):
            raise ValueError("Expected a draft filename inside email_drafts.")
        with open(filepath, "r", encoding="utf-8") as f:
            data = decrypt_payload(json.load(f))
        return EmailDraft(**data)
