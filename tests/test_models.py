"""Tests for Pydantic data models"""
import pytest
from datetime import datetime
from core.models import (
    CVProfile,
    Experience,
    Project,
    JobPosting,
    ContactCandidate,
    EmailDraft,
    QualityCheck,
    SearchQuery,
)


class TestExperience:
    """Test suite for Experience model"""

    def test_experience_creation(self):
        """Test creating an Experience instance"""
        exp = Experience(
            title="Software Engineer",
            company="Tech Corp",
            duration="2020-2022",
            achievements=["Built API"],
            metrics=["Reduced latency by 40%"],
            technologies=["Python", "Docker"],
        )
        assert exp.title == "Software Engineer"
        assert exp.company == "Tech Corp"
        assert len(exp.achievements) == 1
        assert len(exp.technologies) == 2


class TestProject:
    """Test suite for Project model"""

    def test_project_creation(self):
        """Test creating a Project instance"""
        project = Project(
            name="ML Pipeline",
            description="Automated ML workflow",
            technologies=["Python", "Airflow"],
            github="https://github.com/user/repo",
        )
        assert project.name == "ML Pipeline"
        assert len(project.technologies) == 2
        assert project.github is not None


class TestCVProfile:
    """Test suite for CVProfile model"""

    def test_cv_profile_minimal(self):
        """Test creating minimal CV profile"""
        cv = CVProfile(raw_text="Sample CV text")
        assert cv.raw_text == "Sample CV text"
        assert cv.name is None
        assert len(cv.experiences) == 0
        assert len(cv.projects) == 0

    def test_cv_profile_complete(self):
        """Test creating complete CV profile"""
        exp = Experience(
            title="Engineer", company="Corp", duration="2020-2022"
        )
        proj = Project(name="App", description="Mobile app")

        cv = CVProfile(
            name="John Doe",
            email="john@example.com",
            experiences=[exp],
            projects=[proj],
            skills=["Python", "Docker"],
            raw_text="Full CV text",
        )

        assert cv.name == "John Doe"
        assert len(cv.experiences) == 1
        assert len(cv.projects) == 1
        assert len(cv.skills) == 2


class TestJobPosting:
    """Test suite for JobPosting model"""

    def test_job_posting_creation(self):
        """Test creating a JobPosting instance"""
        job = JobPosting(
            title="Senior Developer",
            company="StartupXYZ",
            location="Remote",
            description="Build scalable systems",
            tech_stack=["Python", "Kubernetes"],
        )
        assert job.title == "Senior Developer"
        assert job.location == "Remote"
        assert len(job.tech_stack) == 2


class TestContactCandidate:
    """Test suite for ContactCandidate model"""

    def test_contact_creation(self):
        """Test creating a ContactCandidate instance"""
        contact = ContactCandidate(
            name="Jane Smith",
            role="Engineering Manager",
            email="jane@company.com",
            email_confidence="confirmed",
            confidence_score=0.95,
        )
        assert contact.name == "Jane Smith"
        assert contact.email_confidence == "confirmed"
        assert contact.confidence_score == 0.95


class TestEmailDraft:
    """Test suite for EmailDraft model"""

    def test_email_draft_word_count(self):
        """Test automatic word count calculation"""
        draft = EmailDraft(
            subject="Application for Role",
            body="This is a test email with ten words in it.",
            job_title="Engineer",
            company="TechCo",
        )
        assert draft.word_count == 10

    def test_email_draft_created_at(self):
        """Test automatic timestamp generation"""
        draft = EmailDraft(
            subject="Test", body="Content", job_title="Role", company="Co"
        )
        assert isinstance(draft.created_at, datetime)


class TestQualityCheck:
    """Test suite for QualityCheck model"""

    def test_quality_check_score_calculation(self):
        """Test automatic quality score calculation"""
        quality = QualityCheck(
            has_metric=True,
            has_project_link=True,
            has_company_hook=True,
            has_clear_cta=True,
            under_word_limit=True,
            no_emojis=True,
            no_bullet_dashes=False,
        )
        # 6 out of 7 checks pass = ~85.7%
        assert quality.score > 85
        assert quality.score < 87

    def test_quality_check_passed(self):
        """Test passed threshold (>= 70%)"""
        quality = QualityCheck(
            has_metric=True,
            has_project_link=True,
            has_company_hook=True,
            has_clear_cta=True,
            under_word_limit=True,
            no_emojis=False,
            no_bullet_dashes=False,
        )
        # 5 out of 7 = 71.4%
        assert quality.passed is True

    def test_quality_check_failed(self):
        """Test failed threshold (< 70%)"""
        quality = QualityCheck(
            has_metric=True,
            has_project_link=False,
            has_company_hook=False,
            has_clear_cta=False,
            under_word_limit=False,
            no_emojis=False,
            no_bullet_dashes=False,
        )
        # 1 out of 7 = 14.3%
        assert quality.passed is False


class TestSearchQuery:
    """Test suite for SearchQuery model"""

    def test_search_query_defaults(self):
        """Test SearchQuery with default values"""
        query = SearchQuery(query="python developer")
        assert query.query == "python developer"
        assert query.remote is False
        assert query.last_n_days == 30
        assert query.max_results == 20

    def test_search_query_custom(self):
        """Test SearchQuery with custom values"""
        query = SearchQuery(
            query="ML engineer",
            location="Berlin",
            remote=True,
            last_n_days=7,
            max_results=10,
        )
        assert query.location == "Berlin"
        assert query.remote is True
        assert query.max_results == 10
