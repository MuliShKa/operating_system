"""Load the OS2 node configuration from config/node.yaml."""

from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config" / "node.yaml"


@dataclass(frozen=True, slots=True)
class NodeConfig:
    name: str
    period_s: float
    obstacle_threshold_m: float
    command_ttl_s: float
    queue_size: int
    safety_socket: Path
    upstream_socket: Path
    database: Path
    upstream_database: Path
    sync_batch_size: int
    restart_burst: int
    restart_window_s: float


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_DIR / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> NodeConfig:
    """Parse node.yaml; a missing key raises KeyError with its name."""
    with open(path, encoding="utf-8") as file:
        data = yaml.safe_load(file)

    control, ipc = data["control"], data["ipc"]
    offline, supervisor = data["offline"], data["supervisor"]
    config = NodeConfig(
        name=data["name"],
        period_s=control["period_ms"] / 1000,
        obstacle_threshold_m=float(control["obstacle_threshold_m"]),
        command_ttl_s=control["command_ttl_ms"] / 1000,
        queue_size=int(ipc["bounded_queue_size"]),
        safety_socket=Path(ipc["unix_socket_path"]),
        upstream_socket=Path(ipc["upstream_socket_path"]),
        database=_project_path(offline["database_path"]),
        upstream_database=_project_path(offline["upstream_database_path"]),
        sync_batch_size=int(offline["sync_batch_size"]),
        restart_burst=int(supervisor["restart_burst"]),
        restart_window_s=float(supervisor["restart_window_s"]),
    )
    if config.period_s <= 0 or config.command_ttl_s <= 0:
        raise ValueError("period_ms and command_ttl_ms must be positive")
    if config.queue_size < 1 or config.sync_batch_size < 1:
        raise ValueError("queue and batch sizes must be positive")
    return config
