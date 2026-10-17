"""Builder/scoring/export boundaries exercised through the public UI facade."""

import json
import zipfile

from core import facade
from core.candidate import CandidateProfile, WorkAuthorization
from core.db import get_session
from core.db.repository import ContactRepository, DraftRepository
from core.models import EmailDraft, JobPosting
from core.storage import LocalStorage


def test_built_cv_can_be_saved_restored_and_compared_without_a_model(temp_db):
    profile = facade.build_cv_profile(
        {
            "name": "Synthetic Candidate",
            "email": "candidate@example.test",
            "skills": "Python\nSQL",
            "projects": [{"name": "Parser", "description": "Built a Python parser"}],
        }
    )
    cv_id = facade.persist_cv(profile)
    restored = facade.load_cv(cv_id)
    report = facade.assess_resume(
        restored,
        JobPosting(title="Engineer", company="Example", tech_stack=["Python", "Rust"]),
    )
    assert report["readiness_score"] > 0
    assert "python" in [value.lower() for value in report["job_match"]["matched"]]
    assert "rust" in [value.lower() for value in report["job_match"]["missing"]]
    assert facade.assess_resume(restored)["job_match"] is None
    assert restored.skills == ["Python", "SQL"]


def test_explicit_all_data_export_contains_saved_candidate_answers(temp_db, tmp_path):
    cv_id = facade.persist_cv(
        facade.build_cv_profile({"name": "Synthetic", "skills": ["Python"]})
    )
    candidate = CandidateProfile(
        work_authorization=WorkAuthorization(
            country="GB", authorized=True, requires_sponsorship=False
        )
    )
    facade.save_candidate_profile(cv_id, candidate)
    output = facade.export_all_data(LocalStorage(str(tmp_path / "storage")))
    with zipfile.ZipFile(output) as archive:
        profile = json.loads(archive.read(f"cv_profiles/saved_cv_{cv_id}.json"))
        answers = json.loads(
            archive.read(f"candidate_profiles/saved_candidate_{cv_id}.json")
        )
        assert profile["name"] == "Synthetic"
        assert answers["work_authorization"]["country"] == "GB"
        assert answers["work_authorization"]["authorized"] is True
        assert "candidate_profiles/" in archive.read("README.txt").decode()


def test_all_data_export_keeps_database_only_contacts_and_drafts(temp_db, tmp_path):
    with get_session() as session:
        ContactRepository(session).save(
            "Synthetic Contact", email="contact@example.test"
        )
        DraftRepository(session).save(
            EmailDraft(
                subject="Synthetic",
                body="Review this draft",
                recipient_email="contact@example.test",
            )
        )
    output = facade.export_all_data(LocalStorage(str(tmp_path / "storage")))
    with zipfile.ZipFile(output) as archive:
        contacts = json.loads(archive.read("database/contacts.json"))
        drafts = json.loads(archive.read("database/gmail_drafts.json"))
        assert contacts[0]["email"] == "contact@example.test"
        assert drafts[0]["body"] == "Review this draft"
        assert drafts[0]["recipient_email"] == "contact@example.test"
