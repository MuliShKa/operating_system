"""OS1-1: GeoJSON cache read through a file descriptor, building lookup, SQLite."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

OS1_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OS1_DIR / "src"))

from edge import inventory, storage  # noqa: E402
from edge.node_config import INVENTORY, LATITUDE, LONGITUDE  # noqa: E402

FIXTURE = OS1_DIR / INVENTORY["fixture"]


def open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


class TestInventory(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.original = storage.DATABASE_PATH
        storage.DATABASE_PATH = self.root / "node.db"
        storage.initialize_database()

    def tearDown(self):
        storage.DATABASE_PATH = self.original
        self.folder.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_fixture_is_labelled_as_not_vworld(self):
        metadata, buildings = inventory.parse_buildings(FIXTURE.read_bytes())
        self.assertIn("NOT downloaded from VWorld", metadata["source"])
        self.assertTrue(all(b["properties"]["fixture"] for b in buildings))

    def test_node_is_inside_convensia_not_a_neighbour(self):
        _, buildings = inventory.parse_buildings(FIXTURE.read_bytes())
        found = inventory.find_building(buildings, LATITUDE, LONGITUDE)
        self.assertEqual(found["building_id"], "FIXTURE-CONVENSIA")

    def test_point_outside_every_building(self):
        _, buildings = inventory.parse_buildings(FIXTURE.read_bytes())
        self.assertIsNone(inventory.find_building(buildings, LATITUDE - 0.01, LONGITUDE))

    def test_point_in_ring_square(self):
        square = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
        self.assertTrue(inventory.point_in_ring(1, 1, square))
        self.assertFalse(inventory.point_in_ring(3, 1, square))

    def test_read_with_fd_closes_the_descriptor(self):
        before = open_fds()
        data = inventory.read_file_with_fd(FIXTURE)
        self.assertEqual(data, FIXTURE.read_bytes())
        self.assertEqual(open_fds(), before)

    def test_fd_is_closed_even_when_parsing_fails(self):
        before = open_fds()
        result = inventory.load_inventory(self.write("bad.geojson", "{not json"), "test")
        self.assertFalse(result["ok"])
        self.assertIn("not valid JSON", result["error"])
        self.assertEqual(open_fds(), before)

    def test_missing_cache_does_not_raise(self):
        result = inventory.load_inventory(self.root / "missing.geojson", "test")
        self.assertFalse(result["ok"])
        self.assertIsNone(result["node_building"])

    def test_not_a_feature_collection(self):
        result = inventory.load_inventory(self.write("x.geojson", json.dumps({"type": "Feature"})), "test")
        self.assertIn("FeatureCollection", result["error"])

    def test_inventory_is_stored_in_sqlite(self):
        result = inventory.load_inventory(FIXTURE, "fixture")
        self.assertTrue(result["ok"])
        self.assertEqual(result["node_building"]["building_id"], "FIXTURE-CONVENSIA")
        with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
            rows = connection.execute("SELECT building_id, source FROM building_inventory").fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(source == "fixture" for _, source in rows))

    def test_handbook_views_exist(self):
        storage.save_event("e1", "INDOOR_CO2_PPM", "2026-11-13T00:00:00", {"value": 900})
        with closing(sqlite3.connect(storage.DATABASE_PATH)) as connection:
            self.assertEqual(connection.execute("SELECT sensor_id FROM sensor_events").fetchone()[0], "INDOOR_CO2_PPM")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_outbox").fetchone()[0], 1)


class TestVworldFetch(unittest.TestCase):
    def test_url_has_the_box_around_the_node_and_no_network_call(self):
        from edge import vworld_fetch
        url = vworld_fetch.build_url("KEY", "LAYER", 0.003, None)
        self.assertIn("request=GetFeature", url)
        self.assertIn("data=LAYER", url)
        self.assertIn(f"{LONGITUDE - 0.003:.6f}", url)


if __name__ == "__main__":
    unittest.main()
