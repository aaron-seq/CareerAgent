"""Alembic history: single head, and the latest step round-trips on SQLite."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


def _config(monkeypatch, db: Path) -> Config:
    # alembic/env.py reads DATABASE_URL at run time.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("path_separator", "os")
    return cfg


def _cv_columns(db: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db}")
    try:
        return {c["name"] for c in inspect(engine).get_columns("cv_profile")}
    finally:
        engine.dispose()


def test_history_has_a_single_head(monkeypatch, tmp_path):
    cfg = _config(monkeypatch, tmp_path / "m.db")
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1


def test_candidate_payload_migration_round_trips(monkeypatch, tmp_path):
    db = tmp_path / "m.db"
    cfg = _config(monkeypatch, db)

    command.upgrade(cfg, "head")
    assert "candidate_payload" in _cv_columns(db)

    command.downgrade(cfg, "cbb284f817e8")
    columns = _cv_columns(db)
    assert "candidate_payload" not in columns
    assert {"payload", "email", "phone"} <= columns  # nothing else dropped

    command.upgrade(cfg, "head")
    assert "candidate_payload" in _cv_columns(db)
