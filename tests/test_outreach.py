"""Phase 7 -- outreach compliance: verification, footer, LIA, caps, gate."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.db.repository import SuppressionRepository
from core.models import EmailDraft
from core.outreach import (
    ComplianceConfig,
    LIARecord,
    OutreachService,
    SendPolicy,
    ensure_compliant,
    has_compliant_footer,
    verify_email,
)


def _config() -> ComplianceConfig:
    return ComplianceConfig(
        sender_name="Ada Lovelace",
        sender_email="ada@example.com",
        postal_address="1 Analytical Way, London, UK",
        unsubscribe="mailto:ada@example.com?subject=unsubscribe",
    )


def _lia() -> LIARecord:
    return LIARecord(
        campaign="swe-outreach",
        purpose="Relevant job application to a hiring manager (B2B).",
        necessity="Direct, low-volume, role-specific contact.",
        balancing="Business address, opt-out honored, no sensitive data.",
    )


def _draft(recipient="hm@corp.com") -> EmailDraft:
    return EmailDraft(
        subject="Application",
        body="Hello, I'd love to discuss the role.",
        recipient_email=recipient,
        company="Corp",
    )


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


def test_verify_email_syntax():
    assert verify_email("bad@@x", resolver=lambda d: ["mx"]).syntax_ok is False
    assert verify_email("good@example.com", resolver=lambda d: ["mx"]).syntax_ok


def test_verify_email_requires_mx():
    good = verify_email("a@example.com", resolver=lambda d: ["mx1.example.com"])
    assert good.has_mx is True and good.deliverable is True
    no_mx = verify_email("a@nodomain.com", resolver=lambda d: [])
    assert no_mx.has_mx is False and no_mx.deliverable is False


def test_verify_email_unknown_mx_not_blocked():
    r = verify_email("a@example.com", resolver=lambda d: None)
    assert r.has_mx is None and r.deliverable is True


# --------------------------------------------------------------------------- #
# Compliance footer
# --------------------------------------------------------------------------- #


def test_ensure_compliant_appends_footer():
    cfg = _config()
    result = ensure_compliant("Hi there.", cfg)
    assert result.added_footer is True
    assert cfg.postal_address in result.body
    assert cfg.unsubscribe in result.body
    assert has_compliant_footer(result.body, cfg)


def test_ensure_compliant_is_idempotent():
    cfg = _config()
    once = ensure_compliant("Hi.", cfg).body
    twice = ensure_compliant(once, cfg)
    assert twice.added_footer is False
    assert twice.body == once


def test_ensure_compliant_rejects_bad_config():
    bad = ComplianceConfig("", "", "", "")
    try:
        ensure_compliant("Hi", bad)
        raised = False
    except ValueError:
        raised = True
    assert raised


# --------------------------------------------------------------------------- #
# Send policy
# --------------------------------------------------------------------------- #


def test_send_policy_cap_and_window():
    now = datetime(2026, 1, 1, 12, 0, 0)
    policy = SendPolicy(max_per_window=2, window=timedelta(days=1))
    assert policy.can_send(now)
    policy.record(now)
    policy.record(now)
    assert policy.can_send(now) is False
    # A day later the window has rolled over.
    assert policy.can_send(now + timedelta(days=1, seconds=1)) is True


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


def test_gate_allows_verified_compliant_send(session):
    svc = OutreachService(session, _config(), resolver=lambda d: ["mx"])
    decision = svc.prepare_send(_draft(), _lia())
    assert decision.allowed is True
    assert has_compliant_footer(decision.body, _config())


def test_gate_blocks_incomplete_lia(session):
    svc = OutreachService(session, _config(), resolver=lambda d: ["mx"])
    incomplete = LIARecord(campaign="c", purpose="", necessity="", balancing="")
    decision = svc.prepare_send(_draft(), incomplete)
    assert decision.allowed is False
    assert "LIA" in decision.reason


def test_gate_blocks_suppressed_recipient(session):
    SuppressionRepository(session).add("hm@corp.com")
    session.commit()
    svc = OutreachService(session, _config(), resolver=lambda d: ["mx"])
    decision = svc.prepare_send(_draft("hm@corp.com"), _lia())
    assert decision.allowed is False
    assert "suppression" in decision.reason


def test_gate_blocks_unverifiable_email(session):
    svc = OutreachService(session, _config(), resolver=lambda d: [])  # no MX
    decision = svc.prepare_send(_draft("x@nomx.com"), _lia())
    assert decision.allowed is False
    assert "unverifiable" in decision.reason


def test_gate_enforces_send_cap(session):
    policy = SendPolicy(max_per_window=1)
    svc = OutreachService(session, _config(), policy=policy, resolver=lambda d: ["mx"])
    first = svc.prepare_send(_draft(), _lia())
    assert first.allowed
    svc.record_sent()
    second = svc.prepare_send(_draft(), _lia())
    assert second.allowed is False
    assert "cap" in second.reason


def test_opt_out_then_blocked(session):
    svc = OutreachService(session, _config(), resolver=lambda d: ["mx"])
    assert svc.prepare_send(_draft("hm@corp.com"), _lia()).allowed is True
    svc.opt_out("hm@corp.com")
    session.commit()
    assert svc.prepare_send(_draft("hm@corp.com"), _lia()).allowed is False
