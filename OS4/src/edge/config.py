"""Load config/node.yaml, falling back to safe defaults.

The node must still start if PyYAML is missing or the file is unreadable,
because the whole point of the project is to keep operating under failures.
"""

import os
from pathlib import Path
from typing import Any

# Local ports. The environment can move them when the defaults are taken by
# another program on the machine. The API listens on loopback only; a container
# sets 0.0.0.0.
API_HOST = os.environ.get("EDGE_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("EDGE_API_PORT", "8000"))
RECEIVER_PORT = int(os.environ.get("EDGE_RECEIVER_PORT", "8001"))

# Where the sensors' Unix domain sockets live (OS4-1). A short path on purpose:
# a socket path is limited to about 107 bytes, and a deep project path can exceed it.
SOCKET_DIR = Path(os.environ.get("EDGE_SOCKET_DIR", "/tmp/songdo-os4"))

PROJECT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_DIR / "config" / "node.yaml"

DEFAULTS: dict[str, Any] = {
    "node_id": "EDGE_NODE_OS4_IOT_HUB",
    "latitude": 37.3812,
    "longitude": 126.6620,
    "queue_size": 500,
    "sensors": {
        "PM25": {"unit": "ug/m3", "period_s": 2.0, "valid_min": 0, "valid_max": 1000,
                 "stale_after_s": 10.0, "stuck_check": True},
        "NOISE": {"unit": "dB", "period_s": 1.0, "valid_min": 20, "valid_max": 140,
                  "stale_after_s": 5.0, "stuck_check": False},
        "LUX": {"unit": "lux", "period_s": 5.0, "valid_min": 0, "valid_max": 120000,
                "stale_after_s": 20.0, "stuck_check": False},
    },
    "pm25_bad_threshold": 50,
    "mist_command_ttl_seconds": 30.0,
    "stuck_repeat_count": 6,
    "pm25_very_bad_threshold": 75,
    "quiet_night_lux": 10,
    "quiet_night_noise_db": 45,
    "context_max_age_s": 30,
    "airkorea_station": "131233",
    "airkorea_csv": "sources/airkorea_131233_pm25.csv",
    "airkorea_sample_csv": "sources/airkorea_131233_SAMPLE_synthetic.csv",
    "baseline_window_s": 60,
    "baseline_min_readings": 5,
    "baseline_check_every_s": 20,
    "baseline_tolerance_ugm3": 15,
}


def load_config() -> dict[str, Any]:
    """Return the defaults updated with the values found in node.yaml."""
    config = dict(DEFAULTS)
    try:
        import yaml

        with open(CONFIG_PATH, encoding="utf-8") as config_file:
            loaded = yaml.safe_load(config_file) or {}
        if isinstance(loaded, dict):
            config.update(loaded)
    except (ImportError, OSError, ValueError):
        # Missing PyYAML, missing file or invalid YAML: keep the defaults.
        pass
    return config
