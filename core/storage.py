"""
Local storage for drafts and export to JSON/ZIP
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, List, Mapping
from zipfile import ZipFile

from .db.crypto import decrypt_payload, encrypt_payload
from .models import CVProfile, EmailDraft, JobPosting, WhatsAppDraft
from .normalize import compute_dedup_key


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
        """Save a job posting, one file per posting.

        Keyed on the same title/company/location fingerprint the DB dedups
        on, and replaced atomically, so re-selecting a posting (often with a
        different relevance score) updates its backup instead of minting a
        second file that the export would then carry twice.
        """
        path = self._job_posting_path(job.title, job.company, job.location)
        payload = encrypt_payload(job.model_dump())
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            mode="w",
            encoding="utf-8",
            suffix=".part",
            delete=False,
        ) as file:  # mode 0600, like mkstemp
            temporary = Path(file.name)
            json.dump(payload, file, indent=2)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return str(path)

    def _job_posting_path(self, title: str, company: str, location: str | None) -> Path:
        key = compute_dedup_key(title, company, location)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", company).strip("._")[:60] or "job"
        return Path(self.storage_dir, "job_postings", f"job_{safe}_{digest}.json")

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

    def create_export_zip(
        self,
        name: str = "careeragent_export",
        extra: Mapping[str, Any] | None = None,
    ) -> str:
        """Explicitly export readable content, including personal data.

        Local artifacts are decrypted into readable JSON. ``extra`` maps an
        archive path to JSON-serializable data the caller wants included
        (the facade passes the user's DB-held pipeline and CV profiles; this
        module stays independent of the DB). A ``README.txt`` lists every
        entry so the user can see what the bundle actually contains.
        """
        zip_filepath = self._new_path("exports", name, ".zip")
        entries: dict[str, str] = {}
        # Job postings saved before saves were idempotent can exist several
        # times on disk; export each posting once, keeping the newest copy.
        jobs: dict[str, tuple[float, str, str]] = {}

        for root, dirs, files in os.walk(self.storage_dir):
            dirs.sort()
            for file in sorted(files):
                if not file.endswith((".json", ".md")):
                    continue
                file_path = os.path.join(root, file)
                if Path(file_path).is_symlink():
                    continue
                arcname = os.path.relpath(file_path, self.storage_dir)
                arcname = arcname.replace(os.sep, "/")
                if file.endswith(".md"):
                    entries[arcname] = Path(file_path).read_text(encoding="utf-8")
                    continue
                with open(file_path, encoding="utf-8") as source:
                    data = decrypt_payload(json.load(source))
                text = json.dumps(data, indent=2)
                if arcname.startswith("job_postings/") and isinstance(data, dict):
                    key = compute_dedup_key(
                        str(data.get("title", "")),
                        str(data.get("company", "")),
                        data.get("location"),
                    )
                    mtime = os.path.getmtime(file_path)
                    if key not in jobs or mtime >= jobs[key][0]:
                        jobs[key] = (mtime, arcname, text)
                    continue
                entries[arcname] = text

        for _, arcname, text in jobs.values():
            entries[arcname] = text
        for arcname, data in (extra or {}).items():
            entries[arcname] = json.dumps(data, indent=2, default=str)

        manifest = [
            "CareerAgent data export",
            "",
            "This archive contains READABLE personal data (CV, applications,",
            "notes, drafts). Store and share it carefully.",
            "",
            "Contents:",
        ] + [f"  {arcname}" for arcname in sorted(entries)]

        with ZipFile(zip_filepath, "w") as zipf:
            zipf.writestr("README.txt", "\n".join(manifest) + "\n")
            for arcname in sorted(entries):
                zipf.writestr(arcname, entries[arcname])

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
