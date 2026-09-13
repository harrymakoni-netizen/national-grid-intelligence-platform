"""MQTT subscriber for device telemetry (Section 6.3, 11.2). Devices
publish to `gridintel/telemetry/<device_id>`; each message body is a
TelemetryPayload (schemas.py), stored via the exact same store_reading()
path the HTTP endpoint uses.

This cannot be exercised end-to-end on this development machine -- there is
no MQTT broker installed (no Docker) -- so it is unverified beyond local
unit tests of decode_and_store(). Run docker-compose up (Mosquitto service)
to test it live once Docker is available; see docker-compose.yml.
"""
from __future__ import annotations

import json
import logging
import os

import paho.mqtt.client as mqtt

from gridintel.db.session import make_engine, make_session_factory
from gridintel.ingestion.schemas import TelemetryPayload
from gridintel.ingestion.store import UnknownNetworkNode, store_reading

logger = logging.getLogger(__name__)

TOPIC_PREFIX = "gridintel/telemetry/"


def decode_and_store(session, raw_payload: bytes) -> None:
    """Pure function apart from the DB write -- exercised directly in
    tests without needing a running broker."""
    data = json.loads(raw_payload)
    payload = TelemetryPayload.model_validate(data)
    try:
        store_reading(session, payload)
        session.commit()
    except UnknownNetworkNode:
        session.rollback()
        logger.warning("telemetry from unknown network_node_id, dropped: %s", data.get("network_node_id"))
        raise


def run(broker_host: str | None = None, broker_port: int = 1883) -> None:
    broker_host = broker_host or os.environ.get("GRIDINTEL_MQTT_HOST", "localhost")
    engine = make_engine()
    session_factory = make_session_factory(engine)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        logger.info("connected to MQTT broker %s:%s, subscribing to %s#", broker_host, broker_port, TOPIC_PREFIX)
        client.subscribe(f"{TOPIC_PREFIX}#")

    def on_message(client, userdata, msg):
        with session_factory() as session:
            try:
                decode_and_store(session, msg.payload)
            except Exception:
                logger.exception("failed to process telemetry message on topic %s", msg.topic)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker_host, broker_port)
    client.loop_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
