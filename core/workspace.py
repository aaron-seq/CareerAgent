"""Bounded, encrypted recovery of one trusted local user's deliberate workspace.

This is not a session serializer: tokens, clients, generated drafts and approval
state are deliberately outside this schema. Source jobs and CVs stay in the DB.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .db.crypto import decrypt_payload, encrypt_payload
from .models import ContactCandidate, JobPosting
from .storage import LocalStorage

MAX_WORKSPACE_BYTES = 2 * 1024 * 1024
PositiveId = Annotated[int, Field(strict=True, gt=0)]
ShortText = Annotated[str, StringConstraints(strict=True, max_length=500)]
Industry = Literal[
    "Tech/Software", "AI/ML", "Finance", "Healthcare", "E-commerce", "Other"
]
Page = Literal["onboarding", "discovery", "pipeline", "contacts", "draft", "export"]


class WorkspacePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_roles: list[ShortText] = Field(default_factory=list, max_length=50)
    target_locations: list[ShortText] = Field(default_factory=list, max_length=50)
    industries: list[Industry] = Field(default_factory=list, max_length=6)
    seniority: Literal["Any", "Junior", "Mid-level", "Senior", "Staff", "Principal"] = (
        "Any"
    )


class WorkspaceContact(ContactCandidate):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: ShortText
    role: ShortText | None = None
    email: ShortText | None = None
    email_confidence: Literal["confirmed", "guessed", "unknown"] = "unknown"
    linkedin: ShortText | None = None
    source: ShortText = ""
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)


class WorkspaceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    cv_id: PositiveId | None = None
    selected_job_ids: list[PositiveId] = Field(default_factory=list, max_length=200)
    found_contacts: dict[ShortText, list[WorkspaceContact]] = Field(
        default_factory=dict
    )
    preferences: WorkspacePreferences | None = None
    page: Page = "onboarding"

    @field_validator("version", mode="before")
    @classmethod
    def validate_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Workspace version must be an integer.")
        return value

    @model_validator(mode="after")
    def validate_bounds(self) -> WorkspaceSnapshot:
        if len(set(self.selected_job_ids)) != len(self.selected_job_ids):
            raise ValueError("Workspace job references must be unique.")
        if len(self.found_contacts) > 200 or any(
            len(contacts) > 100 for contacts in self.found_contacts.values()
        ):
            raise ValueError("Too many saved companies or contacts.")
        if sum(map(len, self.found_contacts.values())) > 500:
            raise ValueError("Too many saved contacts.")
        return self


def job_reference_key(job: JobPosting) -> str:
    """Identify an in-session job value without changing its public domain schema."""
    return hashlib.sha256(job.model_dump_json().encode()).hexdigest()


def _path(storage: LocalStorage) -> Path:
    return Path(storage.storage_dir, "workspace.json")


def load_workspace(storage: LocalStorage) -> WorkspaceSnapshot | None:
    """Require authenticated ciphertext; never accept legacy plaintext state."""
    path = _path(storage)
    if path.is_symlink():
        raise ValueError("Workspace must be a regular local file.")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Workspace must be a regular local file.")
    with path.open("rb") as source:
        raw = source.read(MAX_WORKSPACE_BYTES + 1)
    if len(raw) > MAX_WORKSPACE_BYTES:
        raise ValueError("Saved workspace exceeds the recovery size limit.")
    envelope = json.loads(raw)
    if not isinstance(envelope, dict) or set(envelope) != {"format", "ciphertext"}:
        raise ValueError("Saved workspace has an invalid encrypted envelope.")
    if envelope["format"] != "careeragent.fernet.v1" or not isinstance(
        envelope["ciphertext"], str
    ):
        raise ValueError("Saved workspace must be encrypted.")
    data = decrypt_payload(envelope)
    if not isinstance(data, dict) or "version" not in data:
        raise ValueError("Saved workspace is missing its schema version.")
    return WorkspaceSnapshot.model_validate(data)


def save_workspace(storage: LocalStorage, snapshot: WorkspaceSnapshot) -> None:
    """Atomically replace a validated workspace without overwriting unreadable data."""
    snapshot = WorkspaceSnapshot.model_validate(snapshot.model_dump())
    load_workspace(storage)  # wrong-key/corrupt prior data must never be overwritten
    payload = json.dumps(encrypt_payload(snapshot.model_dump(mode="json"))).encode()
    if len(payload) > MAX_WORKSPACE_BYTES:
        raise ValueError("Workspace exceeds the recovery size limit.")
    path = _path(storage)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".workspace-", suffix=".part", delete=False
    ) as temporary:
        temp_path = Path(temporary.name)
        try:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def reset_workspace(storage: LocalStorage) -> str | None:
    """Explicit recovery action: retain unreadable ciphertext as a private backup."""
    path = _path(storage)
    if path.is_symlink():
        raise ValueError("Workspace must be a regular local file.")
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Workspace must be a regular local file.")
    descriptor, backup = tempfile.mkstemp(
        dir=path.parent, prefix="workspace-unreadable-", suffix=".bak"
    )
    try:
        with os.fdopen(descriptor, "wb") as target, path.open("rb") as source:
            # Preserve even an oversized/corrupt file without loading it in memory.
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        path.unlink()
    except BaseException:
        Path(backup).unlink(missing_ok=True)
        raise
    return Path(backup).name
