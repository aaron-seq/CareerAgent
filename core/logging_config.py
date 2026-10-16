"""
One-place logging setup for CareerAgent entrypoints.

Modules in core/ only ever do ``logger = logging.getLogger(__name__)``;
configuring handlers is the entrypoint's job (app.py calls
``configure_logging()`` once). Stdlib only -- no logging framework.

Never log PII from core/: CV text, names, emails, phone numbers, message
bodies, OAuth tokens. Log sizes, ids, URLs of public job postings, and
exception types instead.
"""

import logging
import os
from typing import Optional

LOG_LEVEL_ENV = "CAREERAGENT_LOG_LEVEL"
DEFAULT_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: Optional[str] = None) -> int:
    """Configure root logging and the ``core`` logger level.

    ``level`` overrides the ``CAREERAGENT_LOG_LEVEL`` env var; an unknown
    level name falls back to INFO. Safe to call repeatedly (Streamlit reruns
    the script on every interaction): ``basicConfig`` only adds a handler
    the first time. Returns the numeric level applied.
    """
    name = (level or os.getenv(LOG_LEVEL_ENV) or DEFAULT_LEVEL).strip().upper()
    numeric = logging.getLevelName(name)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logging.basicConfig(level=numeric, format=LOG_FORMAT)
    # Set explicitly so the level applies even if something else configured
    # the root logger first.
    logging.getLogger("core").setLevel(numeric)
    return numeric
