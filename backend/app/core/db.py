"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# pool_pre_ping keeps the API alive across a PostgreSQL restart, which happens
# often enough in a development stack to be worth the extra round trip.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request."""
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for Celery tasks and scripts."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
