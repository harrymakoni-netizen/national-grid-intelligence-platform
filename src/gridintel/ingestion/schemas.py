"""Device telemetry payload shape, matching Section 6.1's measurement
requirements. Optional fields reflect that not every message carries every
measurement -- a routine 15-minute report carries energy/power-quality
data, while a tamper or supply-loss event is a separate, sparser message
type using the same envelope.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    PERIODIC_READING = "periodic_reading"
    SUPPLY_LOST = "supply_lost"
    SUPPLY_RESTORED = "supply_restored"
    TAMPER_EVENT = "tamper_event"
    DISTURBANCE_EVENT = "disturbance_event"


class PhaseValues(BaseModel):
    a: float | None = None
    b: float | None = None
    c: float | None = None


class TelemetryPayload(BaseModel):
    device_id: str
    network_node_id: str
    ts: datetime
    message_type: MessageType = MessageType.PERIODIC_READING

    voltage_v: PhaseValues | None = None
    current_a: PhaseValues | None = None
    real_energy_kwh: PhaseValues | None = None
    apparent_energy_kvah: PhaseValues | None = None
    power_factor: float | None = None
    phase_imbalance_pct: float | None = None
    thd_pct: float | None = None

    tank_temperature_c: float | None = None
    ambient_temperature_c: float | None = None

    supply_present: bool | None = None
    tamper_detected: bool | None = None
    disturbance_detected: bool | None = None

    signature: str | None = Field(
        default=None,
        description="Source-side signature so a reading used as evidence "
        "(Section 6.3, 10.3) can be shown not to have been altered in "
        "transit. Verification is not implemented in Milestone 1 -- no "
        "device keys exist yet -- but the field is carried through "
        "end-to-end so it is never silently dropped once they do.",
    )
