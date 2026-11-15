"""Load config/node.yaml, falling back to safe defaults.

The node must still start if PyYAML is missing or the file is unreadable,
because the whole point of the project is to keep operating under failures.
"""

import os
from pathlib import Path
from typing import Any

# Local ports. The environment can move them when the defaults are taken by
# another program on the machine (OS1 hit exactly this on port 8001).
# The API listens on the loopback interface only; a container sets 0.0.0.0.
API_HOST = os.environ.get("EDGE_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("EDGE_API_PORT", "8000"))
RECEIVER_PORT = int(os.environ.get("EDGE_RECEIVER_PORT", "8001"))

PROJECT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_DIR / "config" / "node.yaml"

DEFAULTS: dict[str, Any] = {
    "node_id": "EDGE_NODE_OS3_MOBILITY",
    "queue_size": 500,
    "pedestrian_surge_threshold": 15,
    "speed_limit_normal_kmh": 50,
    "speed_limit_surge_kmh": 30,
    "command_ttl_seconds": 15.0,
    "latitude": 37.3820,
    "longitude": 126.6560,
    "bis_stops_csv": "sources/incheon_bis_stops.csv",
    "bis_sample_csv": "sources/bis_stops_SAMPLE_synthetic.csv",
    "bis_radius_m": 200,
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
