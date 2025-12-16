"""
Email draft quality validation
Enforces no emojis, no bullets, must have links and metrics
"""

import re
from typing import List
from .models import EmailDraft, QualityCheck


class DraftValidator:
    """Validate email draft quality"""

    def __init__(self):
        # Emoji pattern (comprehensive)
        self.emoji_pattern = re.compile(
            "["
            "\U0001f600-\U0001f64f"  # emoticons
            "\U0001f300-\U0001f5ff"  # symbols & pictographs
            "\U0001f680-\U0001f6ff"  # transport & map symbols
            "\U0001f1e0-\U0001f1ff"  # flags
            "\U00002702-\U000027b0"
            "\U000024c2-\U0001f251"
            "\U0001f900-\U0001f9ff"  # supplemental symbols
            "]+",
            flags=re.UNICODE,
        )

        # Bullet dash patterns
        self.bullet_patterns = [
            r"^\s*[-•*→]\s+",  # Line starting with dash/bullet
            r"\n\s*[-•*→]\s+",  # Newline followed by dash/bullet
        ]

        # URL pattern
        self.url_pattern = re.compile(
            r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
        )

        # Metric patterns (numbers with %, K, M, or units)
        self.metric_patterns = [
            r"\d+%",  # Percentages
            r"\d+[KkMm]",  # 10K, 5M users
            r"\d+x",  # 3x improvement
            r"\d+\s*(?:users|customers|developers|engineers)",
            r"(?:increased|decreased|improved|reduced|grew|scaled)\s+(?:by\s+)?\d+",
        ]

        # CTA patterns
        self.cta_patterns = [
            r"(?:quick|brief|short)?\s*(?:call|chat|meeting|demo)",
            r"(?:available|free)\s+(?:this week|next week|to chat)",
            r"(?:discuss|talk|show|demo)",
            r"(?:7|10|15)[\s-]*(?:min|minute)",
        ]

    def validate_draft(self, draft: EmailDraft) -> QualityCheck:
        """Run all quality checks on email draft"""

        full_text = f"{draft.subject} {draft.body}"

        checks = QualityCheck(
            has_metric=self._check_has_metric(full_text),
            has_project_link=self._check_has_link(full_text),
            has_company_hook=self._check_company_hook(draft),
            has_clear_cta=self._check_has_cta(full_text),
            under_word_limit=self._check_word_limit(draft.body),
            no_emojis=self._check_no_emojis(full_text),
            no_bullet_dashes=self._check_no_bullets(draft.body),
        )

        # Calculate issues
        checks.issues = self._generate_issues(checks, draft)

        return checks

    def _check_has_metric(self, text: str) -> bool:
        """Check if text contains quantifiable metrics"""
        for pattern in self.metric_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _check_has_link(self, text: str) -> bool:
        """Check if text contains URLs"""
        matches = self.url_pattern.findall(text)
        return len(matches) > 0

    def _check_company_hook(self, draft: EmailDraft) -> bool:
        """Check if email references company or job specifically"""
        body_lower = draft.body.lower()

        # Check if company name is mentioned
        if draft.company and draft.company.lower() in body_lower:
            return True

        # Check if job title is referenced
        if draft.job_title:
            title_words = draft.job_title.lower().split()[:3]  # First 3 words
            if any(word in body_lower for word in title_words if len(word) > 3):
                return True

        return False

    def _check_has_cta(self, text: str) -> bool:
        """Check for clear call-to-action"""
        for pattern in self.cta_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def _check_word_limit(self, body: str, max_words: int = 180) -> bool:
        """Check if body is under word limit"""
        word_count = len(body.split())
        return word_count <= max_words

    def _check_no_emojis(self, text: str) -> bool:
        """Check that text contains no emojis"""
        return not self.emoji_pattern.search(text)

    def _check_no_bullets(self, body: str) -> bool:
        """Check that body contains no bullet point dashes"""
        for pattern in self.bullet_patterns:
            if re.search(pattern, body, re.MULTILINE):
                return False
        return True

    def _generate_issues(self, checks: QualityCheck, draft: EmailDraft) -> List[str]:
        """Generate list of specific issues"""
        issues = []

        if not checks.has_metric:
            issues.append(
                "❌ No concrete metrics found (e.g., '40% improvement', '10K users')"
            )

        if not checks.has_project_link:
            issues.append("❌ No project link found (GitHub, portfolio, demo)")

        if not checks.has_company_hook:
            issues.append(f"❌ No specific reference to {draft.company} or job role")

        if not checks.has_clear_cta:
            issues.append(
                "❌ No clear call-to-action (e.g., '10-minute call', 'quick demo')"
            )

        if not checks.under_word_limit:
            word_count = len(draft.body.split())
            issues.append(f"❌ Too long: {word_count} words (limit: 180)")

        if not checks.no_emojis:
            issues.append("❌ Contains emojis (remove all emojis)")

        if not checks.no_bullet_dashes:
            issues.append("❌ Contains bullet dashes (use paragraphs instead)")

        return issues
