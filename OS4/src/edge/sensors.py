"""The three sensor channels: names, units, sockets and WIRE FORMATS (scenario OS4-1).

Heterogeneous on purpose. The three (simulated) devices differ in:
  - rate     : PM2.5 every 2 s, noise every 1 s, illumination every 5 s
  - unit     : ug/m3, dB, lux
  - protocol : each device speaks its own text format, so the gateway needs one
               small parser per device (the real world is never uniform)

        PM25   JSON      {"id": "PM25", "value": 41.2, "observed_at": 1731760000.123}
        NOISE  CSV       NOISE,58.3,1731760000.123
        LUX    key=value lux=412.5;ts=1731760000.123

Each device sends one datagram per reading to its own Unix domain socket
(a file in SOCKET_DIR). The Ingest process owns the receiving ends.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from edge.config import SOCKET_DIR, load_config

SENSOR_IDS = ("PM25", "NOISE", "LUX")


class RejectedReading(ValueError):
    """The datagram was understood but the value is physically implausible."""


# --- encoders (used by the simulated devices and by the tests) --------------------

def encode_pm25(value: float, observed_at: float) -> bytes:
    return json.dumps({"id": "PM25", "value": value, "observed_at": observed_at}).encode("utf-8")


def encode_noise(value: float, observed_at: float) -> bytes:
    return f"NOISE,{value},{observed_at!r}".encode("ascii")


def encode_lux(value: float, observed_at: float) -> bytes:
    return f"lux={value};ts={observed_at!r}".encode("ascii")


# --- parsers: raw datagram -> (value, observed_at). Raise ValueError if malformed. ----

def parse_pm25(raw: bytes) -> tuple[float, float]:
    message = json.loads(raw.decode("utf-8"))
    if not isinstance(message, dict) or message.get("id") != "PM25":
        raise ValueError("not a PM25 JSON message")
    return float(message["value"]), float(message["observed_at"])


def parse_noise(raw: bytes) -> tuple[float, float]:
    kind, value, observed_at = raw.decode("ascii").strip().split(",")
    if kind != "NOISE":
        raise ValueError("not a NOISE CSV message")
    return float(value), float(observed_at)


def parse_lux(raw: bytes) -> tuple[float, float]:
    fields = dict(part.split("=", 1) for part in raw.decode("ascii").strip().split(";"))
    return float(fields["lux"]), float(fields["ts"])


@dataclass(frozen=True)
class SensorSpec:
    sensor_id: str
    unit: str
    period_s: float
    valid_min: float
    valid_max: float
    stale_after_s: float
    stuck_check: bool
    encode: Callable[[float, float], bytes]
    parse: Callable[[bytes], tuple[float, float]]

    @property
    def socket_path(self) -> Path:
        # "songdo" in the name: `ss -xlp | grep songdo` finds the sockets (handbook ladder).
        return SOCKET_DIR / f"songdo-os4-{self.sensor_id.lower()}.sock"

    def check_range(self, value: float) -> None:
        """Reject NaN, infinity and values outside the physical range."""
        if not math.isfinite(value) or not (self.valid_min <= value <= self.valid_max):
            raise RejectedReading(
                f"{self.sensor_id} value {value} outside [{self.valid_min}, {self.valid_max}]"
            )


_CODECS = {
    "PM25": (encode_pm25, parse_pm25),
    "NOISE": (encode_noise, parse_noise),
    "LUX": (encode_lux, parse_lux),
}


def load_specs() -> dict[str, SensorSpec]:
    """Build the three SensorSpec objects from config/node.yaml."""
    sensors = load_config()["sensors"]
    specs = {}
    for sensor_id in SENSOR_IDS:
        cfg = sensors[sensor_id]
        encode, parse = _CODECS[sensor_id]
        specs[sensor_id] = SensorSpec(
            sensor_id=sensor_id,
            unit=str(cfg["unit"]),
            period_s=float(cfg["period_s"]),
            valid_min=float(cfg["valid_min"]),
            valid_max=float(cfg["valid_max"]),
            stale_after_s=float(cfg["stale_after_s"]),
            stuck_check=bool(cfg["stuck_check"]),
            encode=encode,
            parse=parse,
        )
    return specs
