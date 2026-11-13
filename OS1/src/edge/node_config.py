"""Load the node settings from config/node.yaml once, at import time."""

import os
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "node.yaml"

with CONFIG_PATH.open(encoding="utf-8") as file:
    CONFIG = yaml.safe_load(file)

NODE_NAME = CONFIG["name"]
SENSORS = CONFIG["sensors"]
RULE = CONFIG["rule"]
SAMPLE_PERIOD_S = float(CONFIG["sample_period_s"])
QUEUE_SIZE = int(CONFIG["queue_size"])

# Local ports. The environment can move them when the defaults are taken.
API_PORT = int(os.environ.get("EDGE_API_PORT", "8000"))
RECEIVER_PORT = int(os.environ.get("EDGE_RECEIVER_PORT", "8001"))
