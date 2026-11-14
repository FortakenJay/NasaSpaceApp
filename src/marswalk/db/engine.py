"""Engine and session factory. Default database: data/marswalk.db (git-ignored); tests pass "sqlite://"."""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from marswalk.config import PROJECT_ROOT
from marswalk.db.models import Base

DEFAULT_URL = f"sqlite:///{(PROJECT_ROOT / 'data' / 'marswalk.db').as_posix()}"


def make_engine(url: str = DEFAULT_URL) -> Engine:
    if url in ("sqlite://", "sqlite:///:memory:"):
        # One shared in-memory DB across threads (FastAPI runs sync routes in a threadpool).
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        if url.startswith("sqlite:///"):
            from pathlib import Path
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
