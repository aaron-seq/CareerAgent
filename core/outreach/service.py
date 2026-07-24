"""
The pre-send gate.

``OutreachService.prepare_send`` is the single choke point every outreach email
must pass. It refuses to green-light a send unless, in order:

1. a complete per-campaign LIA is supplied,
2. the recipient address exists and is not on the suppression list,
3. the address verifies (syntax, and MX when checkable),
4. the send cap for the window has room,
5. the body carries the required compliance footer (appended if missing).

It never sends; it returns a decision. Actual delivery (Gmail draft/API) is a
separate step that must honor the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..db.repository import SuppressionRepository
from ..models import EmailDraft
from .compliance import ComplianceConfig, LIARecord, SendPolicy, ensure_compliant
from .verification import MxResolver, VerificationResult, verify_email


@dataclass
class SendDecision:
    allowed: bool
    reason: str
    body: Optional[str] = None
    verification: Optional[VerificationResult] = None


class OutreachService:
    def __init__(
        self,
        session,
        config: ComplianceConfig,
        policy: SendPolicy | None = None,
        resolver: MxResolver | None = None,
        require_mx: bool = True,
    ):
        self.suppression = SuppressionRepository(session)
        self.config = config
        self.policy = policy or SendPolicy()
        self.resolver = resolver
        self.require_mx = require_mx

    def prepare_send(
        self,
        draft: EmailDraft,
        lia: LIARecord,
        now: datetime | None = None,
    ) -> SendDecision:
        if lia is None or not lia.is_complete():
            return SendDecision(False, "missing or incomplete LIA (GDPR)")

        email = draft.recipient_email
        if not email:
            return SendDecision(False, "no recipient email")

        if self.suppression.is_suppressed(email):
            return SendDecision(False, "recipient is on the suppression list")

        vr = verify_email(email, resolver=self.resolver, require_mx=self.require_mx)
        if not vr.deliverable:
            return SendDecision(False, f"unverifiable email: {vr.reason}", None, vr)

        if not self.policy.can_send(now):
            return SendDecision(False, "send cap reached for this window", None, vr)

        result = ensure_compliant(draft.body, self.config)
        return SendDecision(True, "ok", result.body, vr)

    def record_sent(self, now: datetime | None = None) -> None:
        """Call after a successful send so the cap is enforced."""
        self.policy.record(now)

    def opt_out(self, email: str) -> None:
        """Add an address to the suppression list (honor an opt-out)."""
        self.suppression.add(email, reason="opt_out")
