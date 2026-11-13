"""Load the OS2 node configuration from config/node.yaml."""

import os
from dataclasses import dataclass
from math import isfinite
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
    api_host: str
    api_port: int


def _project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_DIR / path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> NodeConfig:
    """Parse node.yaml; a missing key raises KeyError with its name."""
    with open(path, encoding="utf-8") as file:
        data = yaml.safe_load(file)

    control, ipc = data["control"], data["ipc"]
    offline, supervisor = data["offline"], data["supervisor"]
    api = data.get("api", {})
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
        api_host=os.environ.get("OS2_API_HOST", api.get("host", "127.0.0.1")),
        api_port=int(os.environ.get("OS2_API_PORT", api.get("port", 8000))),
    )
    if (
        not isfinite(config.period_s)
        or config.period_s <= 0
        or not isfinite(config.obstacle_threshold_m)
        or config.obstacle_threshold_m <= 0
        or not isfinite(config.command_ttl_s)
        or config.command_ttl_s <= 0
    ):
        raise ValueError("control timing and obstacle threshold must be positive and finite")
    if config.queue_size < 1 or config.sync_batch_size < 1:
        raise ValueError("queue and batch sizes must be positive")
    if (
        config.restart_burst < 1
        or not isfinite(config.restart_window_s)
        or config.restart_window_s <= 0
    ):
        raise ValueError("restart limit and window must be positive")
    if (
        not config.api_host
        or not isinstance(config.api_host, str)
        or not config.api_host.strip()
        or not 1 <= config.api_port <= 65535
    ):
        raise ValueError("API host and port must be valid")
    if (
        not config.safety_socket.is_absolute()
        or not config.upstream_socket.is_absolute()
        or config.safety_socket == config.upstream_socket
    ):
        raise ValueError("IPC socket paths must be distinct absolute paths")
    if config.database.resolve() == config.upstream_database.resolve():
        raise ValueError("local and upstream databases must use different paths")
    return config
