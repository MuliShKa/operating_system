# 07 – OS1-1 sensor ingestion and cached VWorld inventory

Handbook: sensor acquisition of indoor CO2 (ppm) and room temperature (°C); file
descriptors, parsing cached VWorld building GeoJSON, populating SQLite `sensor_events`.

Design:
- Offline-first: the node reads a GeoJSON file on disk at startup, never VWorld itself.
  `edge.vworld_fetch` downloads it once, by hand, when the WAN is available.
- `inventory.read_file_with_fd`: `os.open` → `os.fstat` (size limit 20 MB) → `os.read` in
  64 KiB chunks until 0 bytes → `os.close` in `finally`. Tests check that the number of
  entries in `/proc/self/fd` is the same before and after, even when parsing fails.
- Parsing accepts Polygon and MultiPolygon features and skips the rest. The node building
  is found by ray casting (point in polygon) with the node coordinates from the handbook.
- Stored in `building_inventory`; every sensor payload gets `building_id`.
- A missing or broken cache never stops the node: `load_inventory` returns `ok: false`
  with the error, readings are still stored (with `building_id: null`).
- Handbook names added as views: `sensor_events` (over `events`) and `durable_outbox`
  (over `outbox`), so the team schema does not change.

Data:
- No VWorld key in the project, and the building layer ID could not be confirmed online
  (an earlier note said `LT_P_DGPRT`, never verified). So the cache is a **fixture**:
  3 hand-made boxes (Convensia around the node, two neighbours), labelled
  "NOT downloaded from VWorld" in the file and in `sources/source_registry.csv`.
- `vworld_fetch.py` builds the VWorld 2D data API request (GetFeature, BOX around the node,
  EPSG:4326, JSON). Not run against the live API yet.

Evidence (2026-11-13, 10 s): inventory 3 rows from the fixture, node inside
FIXTURE-CONVENSIA, 11 CO2 + 11 temperature readings all tagged, units and ranges right.
6/6 checks. The container also loads it. Report: `document/results/os1_1_ingestion.json`.
Tests: `tests/test_os1_1_inventory.py` (11 tests).
