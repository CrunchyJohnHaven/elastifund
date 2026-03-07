"""Engine and session helpers — synchronous SQLite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .schema import Base

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "quant.db"

_engine = None
_SessionLocal = None


def _get_db_url() -> str:
    url = os.environ.get("QUANT_DB_URL")
    if url:
        return url
    return f"sqlite:///{DEFAULT_DB_PATH}"


def get_engine(url: str | None = None):
    global _engine
    if _engine is None:
        url = url or _get_db_url()
        _engine = create_engine(url, echo=False)
        # Enable WAL mode and foreign keys for SQLite
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _rec):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return _engine


def get_session_factory(engine=None) -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        engine = engine or get_engine()
        _SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionLocal


def get_session() -> Session:
    """Return a new session.  Caller must close it."""
    factory = get_session_factory()
    return factory()


def init_db(engine=None):
    """Create all tables from metadata (idempotent)."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)


def reset_engine():
    """Tear down cached engine/session (for tests)."""
    global _engine, _SessionLocal
    if _engine:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def db_status(engine=None) -> dict:
    """Return summary statistics about the database."""
    engine = engine or get_engine()
    info: dict = {"url": str(engine.url), "tables": {}}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table.name}")  # noqa: S608
            ).scalar()
            info["tables"][table.name] = count
        # SQLite specific stats
        if str(engine.url).startswith("sqlite"):
            page_count = conn.execute(text("PRAGMA page_count")).scalar()
            page_size = conn.execute(text("PRAGMA page_size")).scalar()
            info["size_bytes"] = page_count * page_size
    return info


def vacuum(engine=None):
    """Run VACUUM on the database."""
    engine = engine or get_engine()
    with engine.connect() as conn:
        conn.execute(text("VACUUM"))
        conn.commit()
