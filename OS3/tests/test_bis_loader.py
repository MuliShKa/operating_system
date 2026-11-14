"""Tests for scenario OS3-1: cached bus stop context.

Run: python3 tests/test_bis_loader.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from edge import bis_loader  # noqa: E402

SAMPLE_CSV = PROJECT_DIR / "sources" / "bis_stops_SAMPLE_synthetic.csv"
NODE_LAT, NODE_LON = 37.3820, 126.6560


class TestDistance(unittest.TestCase):
    def test_same_point_is_zero(self) -> None:
        self.assertAlmostEqual(bis_loader.haversine_m(NODE_LAT, NODE_LON, NODE_LAT, NODE_LON), 0.0)

    def test_one_millidegree_of_latitude_is_about_111_m(self) -> None:
        distance = bis_loader.haversine_m(37.0, 126.0, 37.001, 126.0)
        self.assertAlmostEqual(distance, 111.2, delta=1.0)


class TestLoader(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_sample_file_loads(self) -> None:
        stops, skipped = bis_loader.load_bus_stops(SAMPLE_CSV)
        self.assertEqual(len(stops), 3)
        self.assertEqual(skipped, 0)
        self.assertEqual(stops[0].routes, ("SAMPLE-R1", "SAMPLE-R2"))

    def test_nearby_stops_are_sorted_and_filtered_by_radius(self) -> None:
        stops, _ = bis_loader.load_bus_stops(SAMPLE_CSV)
        nearby = bis_loader.stops_near(stops, NODE_LAT, NODE_LON, radius_m=200)
        names = [stop.stop_id for stop, _ in nearby]
        self.assertEqual(names, ["SAMPLE-001", "SAMPLE-002"])  # SAMPLE-003 is ~400 m away
        distances = [distance for _, distance in nearby]
        self.assertEqual(distances, sorted(distances))

    def test_invalid_rows_are_skipped_and_counted(self) -> None:
        path = self.dir / "stops.csv"
        path.write_text(
            "stop_id,stop_name,latitude,longitude\n"
            "A1,Good,37.38,126.65\n"
            ",No id,37.38,126.65\n"
            "A3,Bad latitude,abc,126.65\n"
            "A4,Out of range,999,126.65\n",
            encoding="utf-8",
        )
        stops, skipped = bis_loader.load_bus_stops(path)
        self.assertEqual([stop.stop_id for stop in stops], ["A1"])
        self.assertEqual(skipped, 3)

    def test_korean_headers_and_cp949_encoding(self) -> None:
        path = self.dir / "korean.csv"
        path.write_bytes(
            "정류소ID,정류소명,위도,경도\n1001,송도테스트,37.382,126.656\n".encode("cp949")
        )
        stops, skipped = bis_loader.load_bus_stops(path)
        self.assertEqual((len(stops), skipped), (1, 0))
        self.assertEqual(stops[0].name, "송도테스트")

    def test_missing_required_column_raises(self) -> None:
        path = self.dir / "bad.csv"
        path.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            bis_loader.load_bus_stops(path)


class TestBuildContext(unittest.TestCase):
    def test_falls_back_to_sample_and_flags_it(self) -> None:
        context = bis_loader.build_context(
            NODE_LAT, NODE_LON, 200, "does/not/exist.csv", SAMPLE_CSV
        )
        self.assertTrue(context.is_sample)
        self.assertEqual(len(context.nearby), 2)
        self.assertIn("nearest bus stop", context.describe())

    def test_no_files_never_raises(self) -> None:
        context = bis_loader.build_context(NODE_LAT, NODE_LON, 200, "nope.csv", "nope2.csv")
        self.assertEqual(context.source, "none")
        self.assertEqual(context.describe(), "")
        self.assertEqual(context.to_dict()["nearby_count"], 0)


if __name__ == "__main__":
    unittest.main()
