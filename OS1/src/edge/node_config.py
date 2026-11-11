"""Load the node settings from config/node.yaml once, at import time."""

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
