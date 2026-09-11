"""Shared pytest fixtures.

A fixed encryption key is set at import time (before any crypto runs) so
encrypted columns are deterministic across the suite. Each test gets an
isolated in-memory SQLite database.
"""

from __future__ import annotations

import os

# Must be set before core.db.crypto caches the cipher.
os.environ.setdefault(
    "CAREERAGENT_ENCRYPTION_KEY", "FfZAVTPVTyMg6K_aTleTbukKgiOIjfhoWMcANeCTA28="
)

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from core.db import init_db, reset_engine


@pytest.fixture
def engine():
    """Fresh in-memory SQLite engine per test (shared connection)."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the *global* engine at a throwaway SQLite file.

    For code that opens its own sessions (``core.facade``) rather than taking
    one, so it cannot use the in-memory ``session`` fixture above.
    """
    db = tmp_path / "careeragent.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    reset_engine()
    from core import facade

    facade.init_persistence()
    yield
    reset_engine()
