"""Minimal ingestion HTTP surface. The device path is MQTT-first (Section
6.3); this HTTP endpoint exists for (a) systems that push rather than
publish -- vending/billing/outage exports where the utility permits a
webhook rather than a broker connection (Section 11.2's "file-based
transfer supported where system integration is not initially permitted"
implies some ingestion paths will be request/response, not MQTT), and (b)
exercising the identical storage path as MQTT without needing a broker
running, which is what makes this testable without Docker.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from gridintel.db.session import make_engine, make_session_factory
from gridintel.ingestion.schemas import TelemetryPayload
from gridintel.ingestion.store import UnknownNetworkNode, store_reading

app = FastAPI(title="National Grid Intelligence Platform - Ingestion")

_engine = make_engine()
_SessionFactory = make_session_factory(_engine)


def get_session():
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/telemetry", status_code=201)
def post_telemetry(payload: TelemetryPayload, session: Session = Depends(get_session)) -> dict:
    try:
        reading = store_reading(session, payload)
    except UnknownNetworkNode as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": reading.id, "device_id": reading.device_id, "ts": reading.ts.isoformat()}
