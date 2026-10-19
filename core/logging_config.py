"""
One-place logging setup for CareerAgent entrypoints.

Modules in core/ only ever do ``logger = logging.getLogger(__name__)``;
configuring handlers is the entrypoint's job (app.py calls
``configure_logging()``), and only for the ``core`` logger. Stdlib only -- no logging framework.

Never log PII from core/: CV text, names, emails, phone numbers, message
bodies, OAuth tokens. Log sizes, ids, URLs of public job postings, and
exception types instead.
"""

import logging
import os
from typing import Optional
from urllib.parse import urlsplit

LOG_LEVEL_ENV = "CAREERAGENT_LOG_LEVEL"
DEFAULT_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: Optional[str] = None) -> int:
    """Send CareerAgent's own (``core.*``) log records to stderr.

    ``level`` overrides the ``CAREERAGENT_LOG_LEVEL`` env var; an unknown
    level name falls back to INFO. Returns the numeric level applied.

    Deliberately scoped to the ``core`` logger: a root ``basicConfig`` would
    lower the threshold for every library too, and httpx logs full request
    URLs at INFO -- including credentials some job APIs take as query
    parameters (Adzuna ``app_key``). Dependencies keep Python's default
    WARNING threshold. Safe to call on every Streamlit rerun: the handler is
    added once. Records still propagate, so test ``caplog`` sees them.
    """
    name = (level or os.getenv(LOG_LEVEL_ENV) or DEFAULT_LEVEL).strip().upper()
    numeric = logging.getLevelName(name)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    core_logger = logging.getLogger("core")
    core_logger.setLevel(numeric)
    if not any(getattr(h, "_careeragent", False) for h in core_logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler._careeragent = True  # type: ignore[attr-defined]
        core_logger.addHandler(handler)
    return numeric


def safe_url(url: Optional[str]) -> str:
    """A URL reduced to scheme, host[:port] and path, for log messages.

    Pasted links are user input: signed, referral and tracking links carry
    emails and tokens in the query, fragment or userinfo. Those parts never
    reach a log.
    """
    try:
        parts = urlsplit(url or "")
        host = parts.hostname
        if not parts.scheme or not host:
            return "<unparseable url>"
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<unparseable url>"
    return f"{parts.scheme}://{host}{port}{parts.path}"
