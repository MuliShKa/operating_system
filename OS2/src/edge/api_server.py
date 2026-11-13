"""Built-in HTTP API and local dashboard server."""

import json
import logging
import multiprocessing as mp
import signal
import sqlite3
import threading
from multiprocessing.synchronize import Event
from time import monotonic
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import psutil

from edge import storage
from edge.bounded_queue import BoundedSensorQueue
from edge.config import NodeConfig, load_config
from edge.models import SensorReading
from edge.unix_socket import UnixMessageClient

REQUEST_TIMEOUT_S = 0.5
MAX_REQUEST_BYTES = 4096
DASHBOARD_PATH = Path(__file__).resolve().parents[2] / "src" / "ui" / "static" / "index.html"
PATHWAYS_PATH = (
    Path(__file__).resolve().parents[2]
    / "sources"
    / "songdo_central_park_pathways.geojson"
)

log = logging.getLogger(__name__)
_PROCESS_CACHE: dict[int, psutil.Process] = {}
_PROCESS_CACHE_LOCK = threading.Lock()


def _process_metrics(processes: list[dict]) -> list[dict]:
    result = []
    for item in processes:
        process = {**item, "alive": False, "cpu_percent": None, "rss_bytes": None}
        pid = item["pid"]
        if pid is not None:
            try:
                with _PROCESS_CACHE_LOCK:
                    running = _PROCESS_CACHE.get(pid)
                    if running is None:
                        running = psutil.Process(pid)
                        _PROCESS_CACHE[pid] = running
                    process["alive"] = running.is_running()
                    process["cpu_percent"] = running.cpu_percent(interval=None)
                    process["rss_bytes"] = running.memory_info().rss
            except psutil.NoSuchProcess:
                with _PROCESS_CACHE_LOCK:
                    _PROCESS_CACHE.pop(pid, None)
                process["metrics_error"] = "process no longer exists"
            except psutil.AccessDenied as error:
                process["metrics_error"] = str(error)
        result.append(process)
    return result


def _wan_status(config: NodeConfig) -> dict[str, object]:
    try:
        status = UnixMessageClient(
            config.upstream_socket, timeout=REQUEST_TIMEOUT_S
        ).request({"cmd": "status"})
        return {
            "receiver_reachable": True,
            "online": status.get("wan_online") is True,
            "received_events": status.get("received"),
        }
    except (OSError, ValueError) as error:
        return {
            "receiver_reachable": False,
            "online": False,
            "error": str(error),
        }


def _dashboard_status(config: NodeConfig) -> dict[str, object]:
    states = storage.load_states(
        config.database,
        ["LIDAR_PROXIMITY_M", "IMU_YAW_RATE", "estop_latched"],
    )
    readings = {}
    for sensor in ("LIDAR_PROXIMITY_M", "IMU_YAW_RATE"):
        encoded = states.get(sensor)
        if encoded is not None:
            readings[sensor] = json.loads(encoded)
    latch = states.get("estop_latched") == "1"
    safety: dict[str, object] = {
        "available": False,
        "latched": latch,
        "motor_vel": 0.0,
    }
    try:
        safety.update(
            UnixMessageClient(
                config.safety_socket, timeout=REQUEST_TIMEOUT_S
            ).request({"cmd": "status"})
        )
        safety["available"] = True
    except (OSError, ValueError) as error:
        safety["error"] = str(error)

    return {
        "node": config.name,
        "processes": _process_metrics(storage.latest_process_health(config.database)),
        "outbox": storage.outbox_counts(config.database),
        "sensors": readings,
        "safety": safety,
        "wan": _wan_status(config),
    }


def _handler(
    config: NodeConfig, sensor_queue: BoundedSensorQueue | None
) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            log.info("dashboard %s - %s", self.address_string(), format % args)

        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/status":
                try:
                    self._send_json(200, _dashboard_status(config))
                except (sqlite3.Error, ValueError) as error:
                    log.exception("failed to build dashboard status")
                    self._send_json(500, {"error": str(error)})
                return
            if path == "/api/events":
                try:
                    self._send_json(200, storage.recent_events(config.database))
                except (sqlite3.Error, ValueError) as error:
                    log.exception("failed to load local events")
                    self._send_json(500, {"error": str(error)})
                return
            if path == "/api/map":
                try:
                    body = PATHWAYS_PATH.read_bytes()
                except OSError as error:
                    log.exception("failed to read pathway geometry")
                    self._send_json(500, {"error": str(error)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/geo+json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path not in ("/", "/index.html"):
                self._send_json(404, {"error": "not found"})
                return
            try:
                body = DASHBOARD_PATH.read_bytes()
            except OSError as error:
                log.exception("failed to read dashboard")
                self._send_json(500, {"error": str(error)})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path not in ("/api/network", "/api/sensor"):
                self._send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > MAX_REQUEST_BYTES:
                    raise ValueError("request body size is invalid")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
                if path == "/api/sensor":
                    if sensor_queue is None:
                        self._send_json(
                            503, {"error": "sensor injection is unavailable"}
                        )
                        return
                    sensor_id = payload.get("sensor_id")
                    value = payload.get("value")
                    if sensor_id == "LIDAR_PROXIMITY_M":
                        unit, minimum, maximum = "m", 0.2, 3.0
                    elif sensor_id == "IMU_YAW_RATE":
                        unit, minimum, maximum = "rad/s", -1.5, 1.5
                    else:
                        raise ValueError("unsupported sensor_id")
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not minimum <= value <= maximum
                    ):
                        raise ValueError(
                            f"value must be between {minimum} and {maximum}"
                        )
                    reading = SensorReading(
                        sensor_id, float(value), unit, monotonic()
                    )
                    sensor_queue.put(reading)
                    self._send_json(
                        202,
                        {"queued": True, "sensor_id": sensor_id, "value": value},
                    )
                    return
                if not isinstance(payload.get("online"), bool):
                    raise ValueError("online must be a boolean")
                response = UnixMessageClient(
                    config.upstream_socket, timeout=REQUEST_TIMEOUT_S
                ).request({"cmd": "network", "online": payload["online"]})
            except (OSError, ValueError) as error:
                self._send_json(503, {"error": str(error)})
                return
            if "error" in response:
                self._send_json(503, {"error": response["error"]})
                return
            self._send_json(200, response)

    return DashboardHandler


def run_api_server(
    stop_event: Event,
    config: NodeConfig,
    sensor_queue: BoundedSensorQueue | None = None,
) -> None:
    """Serve the dashboard only on loopback until the shared stop event is set."""
    storage.init_db(config.database)
    server = ThreadingHTTPServer(
        (config.api_host, config.api_port), _handler(config, sensor_queue)
    )
    server.daemon_threads = True
    server.timeout = REQUEST_TIMEOUT_S
    log.info(
        "OS2 dashboard listening at http://%s:%d",
        config.api_host,
        config.api_port,
    )
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    stop_event = mp.get_context("spawn").Event()
    previous_handlers = {
        signum: signal.signal(signum, lambda _signum, _frame: stop_event.set())
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        run_api_server(stop_event, load_config())
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
