"""
OS1-1: cached VWorld building inventory.

The node never calls VWorld at runtime: it reads a GeoJSON file cached on
disk (offline-first), finds the building that contains the node, and stores
the inventory in SQLite. Sensor events are then tagged with that building.

The file is read through a raw file descriptor (os.open / os.read / os.close)
to show what Python's open() does underneath: the kernel gives the process a
small integer (the fd) that indexes its open-file table, read() copies bytes
from the kernel into user memory, and close() frees the slot. The fd is
closed in `finally`, so a parse error never leaks it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from edge import storage
from edge.node_config import INVENTORY, LATITUDE, LONGITUDE, PROJECT_DIR

READ_CHUNK = 64 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024


class InventoryError(ValueError):
    """The cached file is missing, too big, or not a usable GeoJSON."""


def read_file_with_fd(path: Path) -> bytes:
    """Read a whole file through a raw file descriptor."""
    fd = os.open(path, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        if size > MAX_FILE_BYTES:
            raise InventoryError(f"{path} is {size} bytes, limit is {MAX_FILE_BYTES}")
        chunks = []
        while True:
            chunk = os.read(fd, READ_CHUNK)
            if not chunk:  # 0 bytes: end of file
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _outer_rings(geometry: dict) -> list[list[list[float]]]:
    if geometry.get("type") == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry.get("type") == "MultiPolygon":
        return [polygon[0] for polygon in geometry["coordinates"]]
    return []


def parse_buildings(raw: bytes) -> tuple[dict, list[dict]]:
    """Return (metadata, buildings) from GeoJSON bytes. Skip features without a polygon."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InventoryError(f"not valid JSON: {error}") from error
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise InventoryError("not a GeoJSON FeatureCollection")

    buildings = []
    for index, feature in enumerate(document.get("features") or []):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        rings = _outer_rings(geometry)
        if not rings:
            continue
        properties = feature.get("properties") or {}
        building_id = str(
            properties.get("bldg_id") or feature.get("id") or properties.get("id") or f"feature-{index}"
        )
        buildings.append({
            "building_id": building_id,
            "name": properties.get("name") or properties.get("buld_nm") or building_id,
            "properties": properties,
            "geometry": geometry,
            "rings": rings,
        })
    if not buildings:
        raise InventoryError("no polygon building in the file")
    return document.get("metadata") or {}, buildings


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray casting: count how many edges a ray going east from the point crosses."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def find_building(buildings: list[dict], lat: float, lon: float) -> dict | None:
    for building in buildings:
        if any(point_in_ring(lon, lat, [p[:2] for p in ring]) for ring in building["rings"]):
            return building
    return None


def cache_path() -> tuple[Path, str]:
    """The real VWorld cache if it was fetched, otherwise the labelled fixture."""
    cache = PROJECT_DIR / INVENTORY["cache"]
    if cache.exists():
        return cache, "vworld-cache"
    return PROJECT_DIR / INVENTORY["fixture"], "fixture"


def save_inventory(buildings: list[dict], source: str) -> None:
    with storage._managed_connection() as connection:
        connection.execute("DELETE FROM building_inventory")
        connection.executemany(
            """
            INSERT INTO building_inventory (building_id, name, properties, geometry, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    b["building_id"], b["name"],
                    json.dumps(b["properties"], ensure_ascii=False),
                    json.dumps(b["geometry"]), source,
                )
                for b in buildings
            ],
        )


def load_inventory(path: Path | None = None, source: str | None = None) -> dict:
    """
    Read the cache, store it in SQLite and return what the node needs.
    Never raises: a missing or broken cache must not stop the sensors.
    """
    if path is None:
        path, source = cache_path()
    try:
        metadata, buildings = parse_buildings(read_file_with_fd(path))
    except (OSError, InventoryError) as error:
        return {"ok": False, "source": source, "path": str(path), "error": str(error),
                "buildings": 0, "node_building": None}

    save_inventory(buildings, source)
    node_building = find_building(buildings, LATITUDE, LONGITUDE)
    return {
        "ok": True,
        "source": source,
        "path": str(path),
        "fixture_note": metadata.get("source"),
        "buildings": len(buildings),
        "node_building": None if node_building is None else {
            "building_id": node_building["building_id"],
            "name": node_building["name"],
        },
    }
