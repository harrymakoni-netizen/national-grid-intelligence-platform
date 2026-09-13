"""Single storage path for device telemetry, used identically by the HTTP
ingestion endpoint and the MQTT subscriber -- so a synthetic bench test
today and a real device tomorrow exercise exactly the same code (Section
11.2's ingestion requirement, and Section 12.3's bench-validation work).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from gridintel.db.models import NetworkNode, SensorReading
from gridintel.ingestion.schemas import TelemetryPayload


class UnknownNetworkNode(ValueError):
    pass


def store_reading(session: Session, payload: TelemetryPayload) -> SensorReading:
    if session.get(NetworkNode, payload.network_node_id) is None:
        raise UnknownNetworkNode(
            f"telemetry references unknown network_node_id={payload.network_node_id!r}"
        )
    reading = SensorReading(
        device_id=payload.device_id,
        network_node_id=payload.network_node_id,
        ts=payload.ts,
        measurement=payload.model_dump(mode="json", exclude={"device_id", "network_node_id", "ts"}),
    )
    session.add(reading)
    session.flush()
    return reading
