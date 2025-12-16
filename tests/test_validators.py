"""Tests for draft validation logic"""
import pytest
from core.validators import DraftValidator
from core.models import EmailDraft


class TestDraftValidator:
    """Test suite for DraftValidator"""

    def test_validator_initialization(self):
        """Test DraftValidator initialization"""
        validator = DraftValidator()
        assert validator.max_words == 180
        assert validator.min_quality_score == 70

    def test_has_metric_detection_true(self):
        """Test metric detection - should pass"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="I reduced latency by 40% and increased throughput by 2x.",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.has_metric is True

    def test_has_metric_detection_false(self):
        """Test metric detection - should fail"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="I worked on performance improvements and made things faster.",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.has_metric is False

    def test_has_project_link_true(self):
        """Test project link detection - should pass"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="Check out my work at github.com/user/project",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.has_project_link is True

    def test_has_project_link_false(self):
        """Test project link detection - should fail"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="I have built many projects in my career.",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.has_project_link is False

    def test_under_word_limit_true(self):
        """Test word limit - should pass"""
        validator = DraftValidator()
        # Create a draft with exactly 100 words (well under 180)
        body = " ".join(["word"] * 100)
        draft = EmailDraft(
            subject="Test", body=body, job_title="Engineer", company="TechCo"
        )
        quality = validator.validate_draft(draft)
        assert quality.under_word_limit is True

    def test_under_word_limit_false(self):
        """Test word limit - should fail"""
        validator = DraftValidator()
        # Create a draft with 200 words (over 180 limit)
        body = " ".join(["word"] * 200)
        draft = EmailDraft(
            subject="Test", body=body, job_title="Engineer", company="TechCo"
        )
        quality = validator.validate_draft(draft)
        assert quality.under_word_limit is False

    def test_no_emojis_true(self):
        """Test emoji detection - should pass (no emojis)"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="Professional email without emojis.",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.no_emojis is True

    def test_no_emojis_false(self):
        """Test emoji detection - should fail (contains emojis)"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="I'm excited to apply! 🚀 Let's connect! 💼",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.no_emojis is False

    def test_no_bullet_dashes_true(self):
        """Test bullet point detection - should pass (no bullets)"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="I have experience with Python and Docker.",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.no_bullet_dashes is True

    def test_no_bullet_dashes_false(self):
        """Test bullet point detection - should fail (has bullets)"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="My skills:\n- Python\n- Docker\n- Kubernetes",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.no_bullet_dashes is False

    def test_has_clear_cta_true(self):
        """Test CTA detection - should pass"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="Would you be available for a quick call next week?",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.has_clear_cta is True

    def test_has_clear_cta_false(self):
        """Test CTA detection - should fail"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Test",
            body="I think I would be a great fit for your company.",
            job_title="Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)
        assert quality.has_clear_cta is False

    def test_comprehensive_validation(self):
        """Test comprehensive validation with all checks"""
        validator = DraftValidator()
        draft = EmailDraft(
            subject="Application: Senior ML Engineer",
            body="""I reduced model inference latency by 45% at my current role.
            
            My recent project (github.com/user/ml-optimizer) demonstrates my expertise 
            in TechCo's tech stack. I noticed your focus on scalable ML systems.
            
            Would you have 15 minutes next week to discuss how I can contribute?""",
            job_title="ML Engineer",
            company="TechCo",
        )
        quality = validator.validate_draft(draft)

        # Should pass all checks
        assert quality.has_metric is True
        assert quality.has_project_link is True
        assert quality.has_company_hook is True
        assert quality.has_clear_cta is True
        assert quality.under_word_limit is True
        assert quality.no_emojis is True
        assert quality.no_bullet_dashes is True
        assert quality.score == 100.0
        assert quality.passed is True
