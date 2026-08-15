"""Phase 1 -- data layer: encryption, CRUD, upsert, and JSON import."""

from __future__ import annotations

import importlib
import json
import os

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import core.db.tables as tables_module
from core.db.crypto import decrypt, deterministic_hash, encrypt
from core.db.repository import (
    ApplicationRepository,
    CVRepository,
    DraftRepository,
    JobRepository,
    SuppressionRepository,
    import_legacy_json,
    job_to_row,
    row_to_job,
)
from core.db.tables import ApplicationStatus, CVProfileRow, JobPostingRow
from core.models import CVProfile, EmailDraft, Experience, JobPosting

# --------------------------------------------------------------------------- #
# Encryption
# --------------------------------------------------------------------------- #


def test_encrypt_roundtrip():
    token = encrypt("secret@example.com")
    assert token != "secret@example.com"  # actually encrypted
    assert decrypt(token) == "secret@example.com"


def test_encrypt_none_passthrough():
    assert encrypt(None) is None
    assert decrypt(None) is None


def test_deterministic_hash_is_stable_and_case_insensitive():
    assert deterministic_hash("Foo@Bar.com") == deterministic_hash("foo@bar.com")
    assert deterministic_hash("a@b.com") != deterministic_hash("c@d.com")


def test_encrypted_column_is_ciphertext_on_disk(session, engine):
    """The stored value must not be plaintext; the ORM decrypts on read."""
    row = CVProfileRow(name="Jane", email="jane@example.com")
    session.add(row)
    session.commit()
    cv_id = row.id

    # Raw SQL bypasses the TypeDecorator -> should see ciphertext.
    raw = (
        engine.connect()
        .exec_driver_sql("SELECT email FROM cv_profile WHERE id = ?", (cv_id,))
        .scalar()
    )
    assert raw is not None
    assert raw != "jane@example.com"
    assert decrypt(raw) == "jane@example.com"


# --------------------------------------------------------------------------- #
# Converters
# --------------------------------------------------------------------------- #


def test_job_converter_roundtrip():
    job = JobPosting(
        title="Senior ML Engineer",
        company="Acme Inc.",
        location="Remote",
        url="https://acme.example/jobs/1",
        description="Build models.",
        tech_stack=["python", "pytorch"],
    )
    row = job_to_row(job, source="greenhouse", source_id="1")
    assert row.dedup_key  # computed
    back = row_to_job(row)
    assert back.title == job.title
    assert back.tech_stack == ["python", "pytorch"]


# --------------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------------- #


def test_job_upsert_is_idempotent(session):
    repo = JobRepository(session)
    job = JobPosting(title="Backend Engineer", company="Globex", location="Berlin")
    r1 = repo.upsert(job, source="lever", source_id="abc")
    r2 = repo.upsert(job, source="lever", source_id="abc")
    session.commit()
    assert r1.id == r2.id
    assert repo.count() == 1


def test_job_upsert_updates_fields(session):
    repo = JobRepository(session)
    repo.upsert(
        JobPosting(title="Eng", company="Globex", description="old"),
        source="lever",
        source_id="x",
    )
    repo.upsert(
        JobPosting(title="Eng", company="Globex", description="new"),
        source="lever",
        source_id="x",
    )
    session.commit()
    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].description == "new"


def test_cv_repository_encrypts_and_roundtrips(session):
    profile = CVProfile(
        name="Ada Lovelace",
        email="ada@example.com",
        phone="+1-555-0100",
        experiences=[Experience(title="Analyst", company="AE", duration="2y")],
        raw_text="Full resume text with PII.",
    )
    repo = CVRepository(session)
    row = repo.save(profile)
    session.commit()
    loaded = repo.get(row.id)
    assert loaded is not None
    assert loaded.name == "Ada Lovelace"
    assert loaded.email == "ada@example.com"
    assert loaded.experiences[0].company == "AE"


def test_suppression_list(session):
    repo = SuppressionRepository(session)
    assert repo.is_suppressed("noreply@corp.com") is False
    repo.add("noreply@corp.com", reason="opt_out")
    session.commit()
    assert repo.is_suppressed("NoReply@Corp.com") is True  # case-insensitive
    # Idempotent add.
    repo.add("noreply@corp.com")
    session.commit()


def test_application_dedup_lookup(session):
    jobs = JobRepository(session)
    job_row = jobs.upsert(
        JobPosting(title="SRE", company="Initech", location="NYC"),
        source="ashby",
        source_id="9",
    )
    session.commit()
    apps = ApplicationRepository(session)
    created = apps.create(job_row, cv_profile_id=None, status=ApplicationStatus.APPLIED)
    session.commit()
    found = apps.get_by_dedup(job_row.dedup_key, None)
    assert found is not None
    assert found.id == created.id
    assert found.status == ApplicationStatus.APPLIED


def test_draft_repository_encrypts_body(session, engine):
    draft = EmailDraft(
        subject="Hello",
        body="Sensitive outreach body.",
        recipient_email="hm@corp.com",
        company="Corp",
    )
    repo = DraftRepository(session)
    row = repo.save(draft)
    session.commit()
    raw = (
        engine.connect()
        .exec_driver_sql("SELECT body FROM email_draft WHERE id = ?", (row.id,))
        .scalar()
    )
    assert raw != "Sensitive outreach body."


# --------------------------------------------------------------------------- #
# Legacy JSON import
# --------------------------------------------------------------------------- #


def test_import_legacy_json(session, tmp_path):
    data_dir = tmp_path / "careeragent_data"
    (data_dir / "job_postings").mkdir(parents=True)
    (data_dir / "cv_profiles").mkdir(parents=True)
    job = {"title": "Data Scientist", "company": "Hooli", "description": "ML"}
    (data_dir / "job_postings" / "job1.json").write_text(json.dumps(job))
    cv = {"name": "Grace", "email": "grace@example.com", "raw_text": "resume"}
    (data_dir / "cv_profiles" / "cv1.json").write_text(json.dumps(cv))

    counts = import_legacy_json(session, str(data_dir))
    session.commit()
    assert counts["job_postings"] == 1
    assert counts["cv_profiles"] == 1
    assert JobRepository(session).count() == 1


def test_import_legacy_json_missing_dir_is_safe(session, tmp_path):
    counts = import_legacy_json(session, str(tmp_path / "nope"))
    assert counts == {"job_postings": 0, "cv_profiles": 0, "email_drafts": 0}


# --------------------------------------------------------------------------- #
# Hot-reload safety
# --------------------------------------------------------------------------- #


def test_tables_module_survives_reload():
    """Streamlit's dev server re-execs a changed module's whole import chain
    on every save, which re-runs core.db.tables' class bodies against the
    same shared SQLModel.metadata. Naively silencing the resulting
    InvalidRequestError with extend_existing=True merges into the existing
    Table instead of replacing it, which duplicates auto-created indexes on
    every reload and then breaks create_all() against a fresh database.
    Reload twice (to catch accumulation, not just the first re-registration)
    and build a real database from the result to catch both failure modes.
    """
    importlib.reload(tables_module)
    importlib.reload(tables_module)

    company = tables_module.SQLModel.metadata.tables["company"]
    index_names = [ix.name for ix in company.indexes]
    assert len(index_names) == len(set(index_names)), (
        f"duplicate indexes after reload: {index_names}"
    )

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    try:
        tables_module.SQLModel.metadata.create_all(engine)  # must not raise
    finally:
        engine.dispose()
