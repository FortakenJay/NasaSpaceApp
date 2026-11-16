"""Engine and session factory. Default database: data/marswalk.db (git-ignored); tests pass "sqlite://"."""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from marswalk.config import PROJECT_ROOT
from marswalk.db.models import Base


def default_db_url() -> str:
    """Same writable root as the rasters (see sources.fetch.data_root).

    On Vercel, and on any checkout that cannot be written, that root is /tmp/marswalk.
    Creating data/marswalk.db under /var/task raises EROFS and the function never starts.
    """
    override = os.environ.get("MARSWALK_DATA")
    if override:
        root = Path(override)
    elif os.environ.get("VERCEL") or not os.access(PROJECT_ROOT, os.W_OK):
        root = Path("/tmp/marswalk")
    else:
        root = PROJECT_ROOT / "data"
    return f"sqlite:///{(root / 'marswalk.db').as_posix()}"


DEFAULT_URL = default_db_url()


def make_engine(url: str = DEFAULT_URL) -> Engine:
    if url in ("sqlite://", "sqlite:///:memory:"):
        # One shared in-memory DB across threads (FastAPI runs sync routes in a threadpool).
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless asked
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
