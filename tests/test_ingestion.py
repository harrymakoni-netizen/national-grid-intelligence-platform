from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from gridintel.hierarchy.aggregate import add_node
from gridintel.db.models import NodeType
from gridintel.ingestion import api as api_module
from gridintel.ingestion.mqtt_service import decode_and_store


@pytest.fixture()
def client(session):
    add_node(session, id="NAT", node_type=NodeType.NATIONAL, name="Zimbabwe", parent_id=None)
    add_node(session, id="REG1", node_type=NodeType.REGION, name="Region", parent_id="NAT")
    add_node(session, id="PS1", node_type=NodeType.PRIMARY_SUBSTATION, name="PS1", parent_id="REG1")
    add_node(session, id="DS1", node_type=NodeType.DISTRIBUTION_SUBSTATION, name="DS1", parent_id="PS1")
    add_node(session, id="T1", node_type=NodeType.TRANSFORMER, name="T1", parent_id="DS1")
    session.commit()

    def override_get_session():
        yield session

    api_module.app.dependency_overrides[api_module.get_session] = override_get_session
    yield TestClient(api_module.app)
    api_module.app.dependency_overrides.clear()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_telemetry_stores_reading(client, session):
    body = {
        "device_id": "DEV-001",
        "network_node_id": "T1",
        "ts": "2026-01-05T12:00:00Z",
        "voltage_v": {"a": 231.2, "b": 229.8, "c": 230.5},
        "current_a": {"a": 12.1, "b": 11.8, "c": 12.4},
        "power_factor": 0.97,
        "tank_temperature_c": 54.3,
    }
    resp = client.post("/telemetry", json=body)
    assert resp.status_code == 201, resp.text

    from gridintel.db.models import SensorReading
    from sqlalchemy import select

    rows = session.execute(select(SensorReading)).scalars().all()
    assert len(rows) == 1
    assert rows[0].device_id == "DEV-001"
    assert rows[0].measurement["voltage_v"]["a"] == pytest.approx(231.2)


def test_post_telemetry_rejects_unknown_node(client):
    body = {
        "device_id": "DEV-001",
        "network_node_id": "DOES-NOT-EXIST",
        "ts": "2026-01-05T12:00:00Z",
    }
    resp = client.post("/telemetry", json=body)
    assert resp.status_code == 422


def test_mqtt_decode_and_store_uses_same_path(session):
    add_node_chain_present = True  # nodes added by outer fixture in other tests; add fresh here
    import json

    add_node(session, id="NAT2", node_type=NodeType.NATIONAL, name="Zimbabwe", parent_id=None)
    add_node(session, id="REG2", node_type=NodeType.REGION, name="R", parent_id="NAT2")
    add_node(session, id="PS2", node_type=NodeType.PRIMARY_SUBSTATION, name="PS", parent_id="REG2")
    add_node(session, id="DS2", node_type=NodeType.DISTRIBUTION_SUBSTATION, name="DS", parent_id="PS2")
    add_node(session, id="T2", node_type=NodeType.TRANSFORMER, name="T2", parent_id="DS2")
    session.commit()

    raw = json.dumps(
        {
            "device_id": "DEV-BENCH-01",
            "network_node_id": "T2",
            "ts": "2026-01-05T12:00:00Z",
            "message_type": "supply_lost",
            "supply_present": False,
        }
    ).encode()
    decode_and_store(session, raw)

    from gridintel.db.models import SensorReading
    from sqlalchemy import select

    rows = session.execute(select(SensorReading).where(SensorReading.device_id == "DEV-BENCH-01")).scalars().all()
    assert len(rows) == 1
    assert rows[0].measurement["message_type"] == "supply_lost"
