"""Scenario OS3-1: cached Incheon BIS bus stop context.

The node never calls the internet to learn where the bus stops are: it reads a
CSV file cached on local disk, so this context also works during a WAN outage.

Real open data (data.go.kr, Incheon), two CSV files used together:
  - 15074309 "시내버스 정류소 현황": stop name/number/ID and 위도/경도 (coordinates).
    Some rows have no location and show 0: they are skipped and counted.
  - 15048265 "버스노선별 정류장 현황" (the dataset named in the handbook): which
    route stops where (노선번호 per 정류소아이디), but NO coordinates. It is used
    only to attach route numbers to the stops of the first file.
Headers are compared ignoring case and ALL whitespace ("정류소 명" == "정류소명").
COLUMN_ALIASES also accepts English names, so a hand-made CSV works too.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

# Accepted header names for each field (compared case-insensitively, trimmed).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "stop_id": ("stop_id", "bstopid", "station_id", "정류소id", "정류소아이디", "정류장id",
                "정류소번호", "정류장번호"),
    "stop_name": ("stop_name", "bstopnm", "station_name", "정류소명", "정류장명"),
    "latitude": ("latitude", "lat", "위도"),
    "longitude": ("longitude", "lon", "lng", "경도"),
    "routes": ("routes", "route_ids", "노선", "노선번호"),
}

# Korean open-data CSV files are often CP949 (EUC-KR), not UTF-8.
ENCODINGS = ("utf-8-sig", "cp949")

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class BusStop:
    stop_id: str
    name: str
    latitude: float
    longitude: float
    routes: tuple[str, ...] = ()


@dataclass
class BusContext:
    """What the node knows about the bus stops around its intersection."""

    source: str = "none"          # path of the CSV that was loaded, or "none"
    is_sample: bool = False       # True when the synthetic sample file was used
    total_stops: int = 0          # valid stops found in the file
    skipped_rows: int = 0         # rows ignored because they were invalid
    radius_m: float = 0.0
    routes_source: str = "none"   # stops-by-route file merged in, or "none"
    stops_with_routes: int = 0    # nearby stops that got at least one route number
    nearby: list[tuple[BusStop, float]] = field(default_factory=list)  # (stop, distance m)

    def describe(self) -> str:
        """One short sentence for decision reasons, or '' when there is no context."""
        if not self.nearby:
            return ""
        stop, distance = self.nearby[0]
        routes = f", routes {'/'.join(stop.routes[:4])}" if stop.routes else ""
        return f"nearest bus stop: {stop.name} ({distance:.0f} m{routes})"

    def to_dict(self) -> dict:
        """JSON-serializable summary for the dashboard."""
        return {
            "source": Path(self.source).name if self.source != "none" else "none",
            "is_sample": self.is_sample,
            "total_stops": self.total_stops,
            "skipped_rows": self.skipped_rows,
            "radius_m": self.radius_m,
            "routes_source": Path(self.routes_source).name if self.routes_source != "none" else "none",
            "stops_with_routes": self.stops_with_routes,
            "nearby_count": len(self.nearby),
            "nearby": [
                {
                    "stop_id": stop.stop_id,
                    "name": stop.name,
                    "distance_m": round(distance, 1),
                    "routes": list(stop.routes),
                }
                for stop, distance in self.nearby[:5]
            ],
        }


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two latitude/longitude points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _read_text(path: Path) -> str:
    """Read the file trying each encoding in turn."""
    raw = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name}: could not decode as UTF-8 or CP949")


def _normalize(name: str) -> str:
    """Lower-case a header and remove every space: '정류소 ID' -> '정류소id'."""
    return "".join((name or "").split()).lower()


def _column_map(header: list[str]) -> dict[str, str]:
    """Map each wanted field to the real header name found in the file."""
    lookup = {_normalize(name): name for name in header}
    mapping = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[field_name] = lookup[alias]
                break
    return mapping


def load_bus_stops(path: str | Path) -> tuple[list[BusStop], int]:
    """
    Load bus stops from a cached CSV file.

    Returns (stops, skipped_rows). Rows with a missing id or coordinates that
    are not valid numbers inside the Earth range are skipped and counted.
    Raises FileNotFoundError / ValueError if the file is missing or has no
    usable id and coordinate columns.
    """
    path = Path(path)
    text = _read_text(path)
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValueError(f"{path.name}: empty file")

    mapping = _column_map(list(reader.fieldnames))
    missing = [name for name in ("stop_id", "latitude", "longitude") if name not in mapping]
    if missing:
        raise ValueError(f"{path.name}: no column found for {', '.join(missing)}")

    stops: list[BusStop] = []
    skipped = 0
    for row in reader:
        try:
            stop_id = (row[mapping["stop_id"]] or "").strip()
            latitude = float(row[mapping["latitude"]])
            longitude = float(row[mapping["longitude"]])
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not stop_id or not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            skipped += 1
            continue
        if latitude == 0 and longitude == 0:
            skipped += 1   # the open data writes 0 where a stop has no location
            continue

        name = (row.get(mapping.get("stop_name", ""), "") or stop_id).strip()
        routes_text = row.get(mapping.get("routes", ""), "") or ""
        routes = tuple(part.strip() for part in routes_text.replace(",", ";").split(";") if part.strip())
        stops.append(BusStop(stop_id, name, latitude, longitude, routes))

    return stops, skipped


def load_route_index(path: str | Path) -> dict[str, tuple[str, ...]]:
    """
    Read the stops-by-route file (dataset 15048265): {stop id: route numbers}.

    One row is one (route, stop) pair, so a stop's routes are collected across
    rows. Raises FileNotFoundError / ValueError if the file has no stop id or
    route column.
    """
    path = Path(path)
    reader = csv.DictReader(_read_text(path).splitlines())
    if not reader.fieldnames:
        raise ValueError(f"{path.name}: empty file")
    mapping = _column_map(list(reader.fieldnames))
    if "stop_id" not in mapping or "routes" not in mapping:
        raise ValueError(f"{path.name}: needs a stop id column and a route column")

    routes: dict[str, list[str]] = {}
    for row in reader:
        stop_id = (row[mapping["stop_id"]] or "").strip()
        route = (row[mapping["routes"]] or "").strip()
        if stop_id and route and route not in routes.setdefault(stop_id, []):
            routes[stop_id].append(route)
    return {stop_id: tuple(items) for stop_id, items in routes.items()}


def stops_near(
    stops: list[BusStop], latitude: float, longitude: float, radius_m: float
) -> list[tuple[BusStop, float]]:
    """Return (stop, distance_m) pairs within radius_m, nearest first."""
    found = []
    for stop in stops:
        distance = haversine_m(latitude, longitude, stop.latitude, stop.longitude)
        if distance <= radius_m:
            found.append((stop, distance))
    found.sort(key=lambda pair: pair[1])
    return found


def build_context(
    latitude: float,
    longitude: float,
    radius_m: float,
    primary_csv: str | Path,
    fallback_csv: str | Path | None = None,
    routes_csv: str | Path | None = None,
) -> BusContext:
    """
    Build the bus context for the node, never raising.

    Tries the real cached file first, then the synthetic sample (flagged with
    is_sample=True so nobody mistakes it for real data). If neither can be
    read, the node simply runs without bus context.
    """
    for candidate, is_sample in ((primary_csv, False), (fallback_csv, True)):
        if candidate is None:
            continue
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            stops, skipped = load_bus_stops(path)
        except (OSError, ValueError):
            continue
        nearby = stops_near(stops, latitude, longitude, radius_m)
        routes_source = "none"
        if routes_csv is not None and not is_sample and Path(routes_csv).is_file():
            try:
                index = load_route_index(routes_csv)
                routes_source = str(routes_csv)
                nearby = [
                    (BusStop(stop.stop_id, stop.name, stop.latitude, stop.longitude,
                             stop.routes or index.get(stop.stop_id, ())), distance)
                    for stop, distance in nearby
                ]
            except (OSError, ValueError):
                pass   # routes are extra context: the stops still work without them
        return BusContext(
            source=str(path),
            is_sample=is_sample,
            total_stops=len(stops),
            skipped_rows=skipped,
            radius_m=radius_m,
            routes_source=routes_source,
            stops_with_routes=sum(1 for stop, _ in nearby if stop.routes),
            nearby=nearby,
        )
    return BusContext(radius_m=radius_m)
