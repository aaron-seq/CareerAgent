"""Regressions at persistence, verification, and generation boundaries."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from core.cv_parser import CVParser
from core.models import CVProfile, EmailDraft, Experience, JobPosting
from core.outreach import ComplianceConfig, ensure_compliant, verify_email
from core.resume import FabricationError
from core.resume.cover_letter import verify_grounded
from core.resume.tailor import assert_no_fabrication
from core.storage import LocalStorage


def test_empty_database_url_uses_the_local_default(monkeypatch):
    from core.db.session import DEFAULT_URL, get_database_url

    monkeypatch.setenv("DATABASE_URL", "")
    assert get_database_url() == DEFAULT_URL


def test_default_key_survives_process_restart(tmp_path):
    environment = os.environ.copy()
    environment.pop("CAREERAGENT_ENCRYPTION_KEY", None)
    environment.pop("CAREERAGENT_KEY_PATH", None)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    program = (
        "import json; from core.db.crypto import encrypt, deterministic_hash; "
        "print(json.dumps([encrypt('synthetic profile'), deterministic_hash('a@example.test')]))"
    )
    first = subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    ciphertext, digest = json.loads(first.stdout)
    program = (
        "import json, sys; from core.db.crypto import decrypt, deterministic_hash; "
        "print(json.dumps([decrypt(sys.argv[1]), deterministic_hash('a@example.test')]))"
    )
    second = subprocess.run(
        [sys.executable, "-c", program, ciphertext],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(second.stdout) == ["synthetic profile", digest]
    assert (tmp_path / ".careeragent_key").stat().st_mode & 0o777 == 0o600


def test_private_json_is_encrypted_but_export_remains_readable(tmp_path):
    storage = LocalStorage(str(tmp_path))
    draft = EmailDraft(
        subject="Private subject",
        body="Private career history",
        recipient_email="a@example.test",
    )
    path = Path(storage.save_email_draft(draft))
    assert b"Private career history" not in path.read_bytes()
    assert b"a@example.test" not in path.read_bytes()
    assert storage.load_email_draft(path.name).body == draft.body
    with ZipFile(storage.create_export_zip()) as archive:
        exported = json.loads(archive.read(f"email_drafts/{path.name}"))
    assert exported["body"] == draft.body
    assert exported["recipient_email"] == draft.recipient_email


def test_same_company_saves_do_not_overwrite_each_other(tmp_path):
    storage = LocalStorage(str(tmp_path))
    first = storage.save_email_draft(
        EmailDraft(subject="First", body="one", company="Example")
    )
    second = storage.save_email_draft(
        EmailDraft(subject="Second", body="two", company="Example")
    )
    assert first != second
    assert storage.load_email_draft(Path(first).name).subject == "First"


def test_storage_keeps_untrusted_names_inside_storage(tmp_path):
    storage = LocalStorage(str(tmp_path / "data"))
    path = Path(
        storage.save_email_draft(
            EmailDraft(subject="Subject", body="Body", company="../../outside/path")
        )
    )
    assert path.resolve().parent == (tmp_path / "data/email_drafts").resolve()


@pytest.mark.parametrize("filename", ["../outside.json", "../../outside.json"])
def test_load_rejects_paths_outside_draft_directory(tmp_path, filename):
    storage = LocalStorage(str(tmp_path / "data"))
    (tmp_path / "outside.json").write_text('{"subject":"Private","body":"outside"}')
    (tmp_path / "data/outside.json").write_text(
        '{"subject":"Private","body":"outside"}'
    )
    with pytest.raises(ValueError, match="filename"):
        storage.load_email_draft(filename)


def test_legacy_plaintext_drafts_are_still_readable(tmp_path):
    storage = LocalStorage(str(tmp_path))
    path = tmp_path / "email_drafts/legacy.json"
    path.write_text('{"subject":"Legacy","body":"old content"}')
    assert storage.load_email_draft(path.name).body == "old content"


def test_explicit_legacy_encryption_preserves_content_and_is_repeatable(tmp_path):
    storage = LocalStorage(str(tmp_path))
    path = tmp_path / "email_drafts/legacy.json"
    path.write_text('{"subject":"Legacy","body":"private legacy content"}')
    assert storage.encrypt_legacy_artifacts() == 1
    assert b"private legacy content" not in path.read_bytes()
    assert storage.load_email_draft(path.name).body == "private legacy content"
    assert path.stat().st_mode & 0o777 == 0o600
    assert storage.encrypt_legacy_artifacts() == 0


def test_encrypted_artifacts_can_be_imported_into_the_database(session, tmp_path):
    from core.db.repository import CVRepository, import_legacy_json

    storage = LocalStorage(str(tmp_path))
    storage.save_cv_profile(
        CVProfile(name="Synthetic Candidate", email="synthetic@example.test")
    )
    counts = import_legacy_json(session, str(tmp_path))
    assert counts["cv_profiles"] == 1
    assert CVRepository(session).get(1).email == "synthetic@example.test"


def test_parse_failure_does_not_return_an_empty_success_profile():
    llm = Mock()
    llm.generate_json.side_effect = RuntimeError("Model unavailable")
    with pytest.raises(ValueError, match="CV parsing failed"):
        CVParser(llm).parse_text("Synthetic candidate profile. " * 10)


def test_empty_model_response_is_not_a_success_profile():
    llm = Mock()
    llm.generate_json.return_value = {}
    with pytest.raises(ValueError, match="CV parsing failed"):
        CVParser(llm).parse_text("Synthetic candidate profile. " * 10)


def test_uploaded_cv_temporary_file_is_removed_after_failure(monkeypatch):
    parser = CVParser(Mock())
    paths = []

    def fail(path):
        paths.append(Path(path))
        assert Path(path).read_bytes() == b"synthetic PDF"
        assert Path(path).stat().st_mode & 0o777 == 0o600
        raise ValueError("Invalid PDF")

    monkeypatch.setattr(parser, "parse_pdf", fail)
    with pytest.raises(ValueError, match="Invalid PDF"):
        parser.parse_pdf_bytes(b"synthetic PDF")
    assert paths and not paths[0].exists()


def test_dns_timeout_is_unknown_and_null_mx_is_undeliverable(monkeypatch):
    import dns.exception

    def timeout(*args, **kwargs):
        raise dns.exception.Timeout()

    monkeypatch.setattr("dns.resolver.resolve", timeout)
    timed_out = verify_email("a@example.test")
    assert timed_out.has_mx is None
    assert not timed_out.deliverable
    assert not verify_email("a@example.test", resolver=lambda _: ["."]).deliverable


def test_send_policy_enforces_minimum_gap():
    from datetime import datetime, timedelta

    from core.outreach import SendPolicy

    now = datetime(2026, 1, 1)
    policy = SendPolicy(min_gap_seconds=30)
    policy.record(now)
    assert not policy.can_send(now + timedelta(seconds=29))
    assert policy.can_send(now + timedelta(seconds=30))


@pytest.mark.parametrize("claim", ["995%", "20%", "5%"])
def test_grounding_does_not_match_substrings_or_joined_digits(claim):
    cv = CVProfile(
        experiences=[
            Experience(
                title="Engineer",
                company="Example",
                duration="2020-2024",
                metrics=["Improved uptime to 99.5%."],
            )
        ]
    )
    job = JobPosting(title="Engineer", company="Target")
    assert verify_grounded(cv, job, f"I improved uptime by {claim}.")


def test_posting_metrics_cannot_be_claimed_as_candidate_achievements():
    cv = CVProfile(skills=["Python"])
    job = JobPosting(
        title="Engineer", company="Target", description="Our business grew by 70%."
    )
    assert verify_grounded(cv, job, "I increased revenue by 70%.")


def test_posting_text_the_model_never_saw_cannot_ground_output():
    job = JobPosting(
        title="Engineer",
        company="Target",
        description="x" * 3100 + " Our team has 40+ engineers.",
    )
    assert verify_grounded(CVProfile(), job, "Your team of 40+ engineers appeals.")


@pytest.mark.parametrize(
    "changed_field",
    ["achievements", "metrics", "duration", "education", "summary", "email"],
)
def test_resume_guard_rejects_changes_beyond_reordering(changed_field):
    cv = CVProfile(
        email="a@example.test",
        summary="Engineer",
        experiences=[
            Experience(title="Engineer", company="Example", duration="2020-2024")
        ],
    )
    tailored = cv.model_copy(deep=True)
    if changed_field in {"achievements", "metrics"}:
        setattr(tailored.experiences[0], changed_field, ["Invented achievement 500%"])
    elif changed_field == "duration":
        tailored.experiences[0].duration = "2000-2024"
    elif changed_field == "education":
        tailored.education.append("Invented PhD")
    else:
        setattr(tailored, changed_field, "invented")
    with pytest.raises(FabricationError):
        assert_no_fabrication(cv, tailored)


def test_unknown_mx_is_not_verified_when_mx_is_required():
    result = verify_email(
        "a@example.test", resolver=lambda domain: None, require_mx=True
    )
    assert not result.deliverable
    assert "unavailable" in result.reason
    assert verify_email(
        "a@example.test", resolver=lambda domain: None, require_mx=False
    ).deliverable


def test_footer_marker_and_address_do_not_replace_sender_identity():
    config = ComplianceConfig(
        "Ada", "ada@example.test", "1 Example Street", "mailto:ada@example.test"
    )
    spoof = "-- \nThis message was sent by somebody else.\n1 Example Street\nmailto:ada@example.test"
    result = ensure_compliant(spoof, config)
    assert config.footer() in result.body


@pytest.mark.parametrize(
    "unsubscribe", [" ", "javascript:alert(1)", "mailto:", "https://"]
)
def test_compliance_requires_a_usable_opt_out(unsubscribe):
    config = ComplianceConfig(
        "Ada", "ada@example.test", "1 Example Street", unsubscribe
    )
    with pytest.raises(ValueError, match="unsubscribe"):
        ensure_compliant("Hello", config)
