"""Standalone database session for the dashboard.

Builds its own SQLAlchemy engine from config/settings.py so that the dashboard
never imports from the 'data/' package (which conflicts with Python's namespace
resolution when Streamlit is the entry point).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _get_url() -> str:
    """Load DATABASE_URL from config/settings.py (reads .env automatically)."""
    from config.settings import settings  # config/ has no data/ dependency
    return settings.database_url


# Lazy-initialised engine — created once on first use.
_engine = None
_SessionLocal = None


def _session_factory() -> sessionmaker:
    global _engine, _SessionLocal
    if _SessionLocal is None:
        _engine = create_engine(_get_url(), pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    factory = _session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
