"""Load config/node.yaml, falling back to safe defaults.

The node must still start if PyYAML is missing or the file is unreadable,
because the whole point of the project is to keep operating under failures.
"""

from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_DIR / "config" / "node.yaml"

DEFAULTS: dict[str, Any] = {
    "node_id": "EDGE_NODE_OS3_MOBILITY",
    "queue_size": 500,
    "pedestrian_surge_threshold": 15,
    "speed_limit_normal_kmh": 50,
    "speed_limit_surge_kmh": 30,
    "command_ttl_seconds": 15.0,
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
