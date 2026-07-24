"""
Email verification before any send.

Syntax validation plus an optional MX-record check. The DNS resolver is
injected so this is unit-testable without network; the default tries dnspython
if installed and otherwise reports MX as "unknown" (never a false positive).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

# Pragmatic RFC-5321-ish address syntax (not a full grammar, but rejects the
# common invalid shapes).
_EMAIL_RE = re.compile(
    r"^(?=.{3,254}$)[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)

# resolver(domain) -> list of MX hostnames (empty/None means "no MX").
MxResolver = Callable[[str], Optional[list[str]]]


@dataclass
class VerificationResult:
    email: str
    syntax_ok: bool
    has_mx: Optional[bool]  # None = not checked / unknown
    deliverable: bool

    @property
    def reason(self) -> str:
        if not self.syntax_ok:
            return "invalid syntax"
        if self.has_mx is False:
            return "no MX record for domain"
        return "ok"


def _default_resolver(domain: str) -> Optional[list[str]]:
    try:
        import dns.resolver  # optional dependency
    except ImportError:
        return None  # unknown; don't guess
    try:
        answers = dns.resolver.resolve(domain, "MX")
        return [str(r.exchange).rstrip(".") for r in answers]
    except Exception:
        return []


def verify_email(
    email: str, resolver: MxResolver | None = None, require_mx: bool = True
) -> VerificationResult:
    """Verify an address. ``deliverable`` requires syntax and (if checkable) MX."""
    syntax_ok = bool(_EMAIL_RE.match(email or ""))
    if not syntax_ok:
        return VerificationResult(email, False, None, False)

    resolver = resolver or _default_resolver
    domain = email.rsplit("@", 1)[1]
    mx = resolver(domain)
    if mx is None:
        # Unknown (no resolver / offline). We can't confirm MX, so we don't
        # block on it -- syntax passed and that's all we can verify here.
        return VerificationResult(email, True, None, True)
    has_mx = len(mx) > 0
    deliverable = has_mx if require_mx else True
    return VerificationResult(email, True, has_mx, deliverable)
