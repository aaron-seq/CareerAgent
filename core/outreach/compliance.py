"""
Outreach compliance: CAN-SPAM / GDPR guardrails baked into the data model.

Every outreach email must carry sender identification, a physical postal
address, and a working opt-out. B2B sends under GDPR also need a documented
Legitimate Interest Assessment (LIA) per campaign. This module supplies:

* :class:`ComplianceConfig` -- the sender identity + address + opt-out,
* :func:`ensure_compliant` -- appends a compliant footer if missing (idempotent),
* :class:`LIARecord` -- a per-campaign legitimate-interest assessment,
* :class:`SendPolicy` -- conservative send caps with jitter.

None of this sends email; it gates what the sender is allowed to send.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..normalize import utc_now

_FOOTER_MARKER = "-- \nThis message was sent by"


@dataclass
class ComplianceConfig:
    sender_name: str
    sender_email: str
    postal_address: str
    unsubscribe: str  # a URL or "mailto:opt-out@..."

    def footer(self) -> str:
        return (
            f"{_FOOTER_MARKER} {self.sender_name} ({self.sender_email}).\n"
            f"Mailing address: {self.postal_address}\n"
            f"To opt out of further messages: {self.unsubscribe}"
        )

    def validate(self) -> list[str]:
        missing = []
        if not self.sender_name:
            missing.append("sender_name")
        if not self.sender_email:
            missing.append("sender_email")
        if not self.postal_address:
            missing.append("postal_address")
        if not self.unsubscribe:
            missing.append("unsubscribe")
        return missing


@dataclass
class ComplianceResult:
    body: str
    added_footer: bool
    additions: list[str] = field(default_factory=list)


def has_compliant_footer(body: str, config: ComplianceConfig) -> bool:
    return (
        _FOOTER_MARKER in body
        and config.postal_address in body
        and config.unsubscribe in body
    )


def ensure_compliant(body: str, config: ComplianceConfig) -> ComplianceResult:
    """Return the body with a compliant footer, appending one if absent."""
    problems = config.validate()
    if problems:
        raise ValueError(f"ComplianceConfig missing fields: {', '.join(problems)}")
    if has_compliant_footer(body, config):
        return ComplianceResult(body=body, added_footer=False)
    new_body = body.rstrip() + "\n\n" + config.footer() + "\n"
    return ComplianceResult(
        body=new_body,
        added_footer=True,
        additions=["identification", "postal_address", "opt_out"],
    )


@dataclass
class LIARecord:
    """GDPR Article 6(1)(f) Legitimate Interest Assessment for a campaign."""

    campaign: str
    purpose: str
    necessity: str
    balancing: str
    created_at: datetime = field(default_factory=utc_now)

    def is_complete(self) -> bool:
        return all([self.campaign, self.purpose, self.necessity, self.balancing])


@dataclass
class SendPolicy:
    """Conservative per-window send cap with jitter between sends."""

    max_per_window: int = 25
    window: timedelta = timedelta(days=1)
    min_gap_seconds: float = 30.0
    _sends: list[datetime] = field(default_factory=list, init=False)

    def _prune(self, now: datetime) -> None:
        cutoff = now - self.window
        self._sends = [t for t in self._sends if t >= cutoff]

    def can_send(self, now: datetime | None = None) -> bool:
        now = now or utc_now()
        self._prune(now)
        return len(self._sends) < self.max_per_window

    def record(self, now: datetime | None = None) -> None:
        now = now or utc_now()
        self._prune(now)
        self._sends.append(now)

    def remaining(self, now: datetime | None = None) -> int:
        now = now or utc_now()
        self._prune(now)
        return max(0, self.max_per_window - len(self._sends))
