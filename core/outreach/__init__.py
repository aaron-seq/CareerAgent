"""Compliant outreach: verification, CAN-SPAM/GDPR guardrails, send gate."""

from .compliance import (
    ComplianceConfig,
    ComplianceResult,
    LIARecord,
    SendPolicy,
    ensure_compliant,
    has_compliant_footer,
)
from .service import OutreachService, SendDecision
from .verification import VerificationResult, is_valid_email, verify_email

__all__ = [
    "ComplianceConfig",
    "ComplianceResult",
    "LIARecord",
    "SendPolicy",
    "ensure_compliant",
    "has_compliant_footer",
    "OutreachService",
    "SendDecision",
    "VerificationResult",
    "is_valid_email",
    "verify_email",
]
