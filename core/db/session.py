"""
Engine and session management.

``DATABASE_URL`` selects the backend. Defaults to a local SQLite file so the
app runs with zero setup; point it at Postgres (``postgresql+psycopg://...``)
in deployment. ``init_db`` creates tables directly (used by tests and first-run
dev); Alembic owns schema evolution in production.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Import tables so they register on SQLModel.metadata before create_all.
from . import tables  # noqa: F401

DEFAULT_URL = "sqlite:///careeragent.db"

_engine: Engine | None = None


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        url = get_database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, echo=False, connect_args=connect_args)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (tests use this to switch to a fresh DB)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db(engine: Engine | None = None) -> None:
    """Create all tables. Idempotent."""
    SQLModel.metadata.create_all(engine or get_engine())


@contextmanager
def get_session(engine: Engine | None = None) -> Iterator[Session]:
    """Session context manager that commits on success, rolls back on error."""
    session = Session(engine or get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
