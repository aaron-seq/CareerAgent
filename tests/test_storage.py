"""Tests for local storage module"""

import pytest
import os
import json
import tempfile
import shutil
from core.storage import LocalStorage
from core.models import EmailDraft, CVProfile, JobPosting


class TestLocalStorage:
    """Test suite for LocalStorage"""

    @pytest.fixture
    def temp_storage(self):
        """Create a temporary storage directory for testing"""
        temp_dir = tempfile.mkdtemp()
        storage = LocalStorage(storage_dir=temp_dir)
        yield storage
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_initialization(self, temp_storage):
        """Test storage initialization creates directories"""
        assert os.path.exists(temp_storage.storage_dir)
        assert os.path.exists(os.path.join(temp_storage.storage_dir, "email_drafts"))
        assert os.path.exists(os.path.join(temp_storage.storage_dir, "cv_profiles"))
        assert os.path.exists(os.path.join(temp_storage.storage_dir, "job_postings"))

    def test_save_email_draft(self, temp_storage):
        """Test saving email draft"""
        draft = EmailDraft(
            subject="Test Subject",
            body="Test body content",
            job_title="Engineer",
            company="TestCorp",
        )
        filepath = temp_storage.save_email_draft(draft)

        assert os.path.exists(filepath)
        assert filepath.endswith(".json")
        assert "TestCorp" in filepath

        # Verify contents
        with open(filepath, "r") as f:
            data = json.load(f)
        assert data["subject"] == "Test Subject"

    def test_save_cv_profile(self, temp_storage):
        """Test saving CV profile"""
        profile = CVProfile(
            name="John Doe",
            email="john@example.com",
            skills=["Python", "Docker"],
            raw_text="CV content",
        )
        filepath = temp_storage.save_cv_profile(profile)

        assert os.path.exists(filepath)
        assert "cv_profile" in filepath

    def test_save_job_posting(self, temp_storage):
        """Test saving job posting"""
        job = JobPosting(
            title="Senior Engineer",
            company="TechCorp",
            description="Build scalable systems",
        )
        filepath = temp_storage.save_job_posting(job)

        assert os.path.exists(filepath)
        assert "TechCorp" in filepath

    def test_list_email_drafts(self, temp_storage):
        """Test listing saved email drafts"""
        # Initially empty
        drafts = temp_storage.list_email_drafts()
        assert len(drafts) == 0

        # Save a draft
        draft = EmailDraft(
            subject="Test",
            body="Body",
            job_title="Role",
            company="Co",
        )
        temp_storage.save_email_draft(draft)

        # Should have one draft now
        drafts = temp_storage.list_email_drafts()
        assert len(drafts) == 1
        assert drafts[0].endswith(".json")

    def test_load_email_draft(self, temp_storage):
        """Test loading email draft from file"""
        draft = EmailDraft(
            subject="Load Test",
            body="Body for loading test",
            job_title="Developer",
            company="LoadCorp",
        )
        filepath = temp_storage.save_email_draft(draft)
        filename = os.path.basename(filepath)

        loaded_draft = temp_storage.load_email_draft(filename)
        assert loaded_draft.subject == "Load Test"
        assert loaded_draft.company == "LoadCorp"

    def test_export_to_markdown(self, temp_storage):
        """Test exporting draft to markdown"""
        draft = EmailDraft(
            subject="Markdown Test",
            body="This is the email body",
            job_title="ML Engineer",
            company="MdCorp",
            recipient_name="Jane Doe",
        )
        filepath = temp_storage.export_to_markdown(draft)

        assert os.path.exists(filepath)
        assert filepath.endswith(".md")

        with open(filepath, "r") as f:
            content = f.read()
        assert "ML Engineer" in content
        assert "MdCorp" in content
        assert "Markdown Test" in content

    def test_create_export_zip(self, temp_storage):
        """Test creating ZIP export of all artifacts"""
        # Save some data first
        draft = EmailDraft(
            subject="Zip Test",
            body="Body",
            job_title="Role",
            company="ZipCorp",
        )
        temp_storage.save_email_draft(draft)

        zip_path = temp_storage.create_export_zip()

        assert os.path.exists(zip_path)
        assert zip_path.endswith(".zip")
