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
LATITUDE = float(CONFIG["latitude"])
LONGITUDE = float(CONFIG["longitude"])
INVENTORY = CONFIG["inventory"]
PROJECT_DIR = CONFIG_PATH.parents[1]
QUEUE_SIZE = int(CONFIG["queue_size"])

# Local ports. The environment can move them when the defaults are taken.
API_PORT = int(os.environ.get("EDGE_API_PORT", "8000"))
# Only the local machine by default; the container sets 0.0.0.0 so the
# published port reaches the API (compose still binds it to 127.0.0.1 on the host).
API_HOST = os.environ.get("EDGE_API_HOST", "127.0.0.1")
RECEIVER_PORT = int(os.environ.get("EDGE_RECEIVER_PORT", "8001"))
