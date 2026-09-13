"""Engine/session helpers. The same models run against SQLite (default for
tests and local dev without Docker) or PostgreSQL/TimescaleDB (production;
set GRIDINTEL_DATABASE_URL). Hypertable creation is Postgres-only and is a
no-op on SQLite.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from gridintel.db.models import Base

DEFAULT_SQLITE_URL = "sqlite:///./gridintel.sqlite3"

# Tables that should become TimescaleDB hypertables in production, keyed by
# their time-dimension column.
HYPERTABLES = {
    "vending_event": "ts",
    "sensor_reading": "ts",
    "ground_truth_consumption": "ts",
    "ground_truth_technical_loss": "ts",
}


def get_database_url() -> str:
    return os.environ.get("GRIDINTEL_DATABASE_URL", DEFAULT_SQLITE_URL)


def make_engine(url: str | None = None):
    url = url or get_database_url()
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            # A single shared connection for the whole engine -- otherwise
            # each new connection from the pool gets its own empty
            # in-memory database, which silently breaks any code path
            # (e.g. FastAPI's TestClient) that checks out a connection from
            # a different thread than the one that created the tables.
            kwargs["poolclass"] = StaticPool
        return create_engine(url, future=True, **kwargs)
    return create_engine(url, future=True)


def make_session_factory(engine=None) -> sessionmaker[Session]:
    engine = engine or make_engine()
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine) -> None:
    """Create all tables and, on Postgres, promote time-series tables to
    hypertables. Idempotent."""
    Base.metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            for table, time_col in HYPERTABLES.items():
                conn.execute(
                    text(
                        "SELECT create_hypertable(:table, :time_col, "
                        "if_not_exists => TRUE, migrate_data => TRUE)"
                    ).bindparams(table=table, time_col=time_col)
                )
