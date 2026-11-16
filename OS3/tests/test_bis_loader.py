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




class TestRealFormat(unittest.TestCase):
    """Files laid out like the real data.go.kr downloads (headers copied from the
    dataset pages; the rows themselves are made-up test data)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.stops = self.dir / "stops.csv"
        self.stops.write_text(
            "기준 일자,정류소 명,정류소 번호,정류소 ID,권역,행정동 명,X 좌표,위도,Y 좌표,경도\n"
            "2026-02-28,테스트정류장A,11001,222000001,송도,송도동,0,37.3823,0,126.6563\n"
            "2026-02-28,테스트정류장B,11002,222000002,송도,송도동,0,0,0,0\n"
            "2026-02-28,테스트정류장C,11003,222000003,송도,송도동,0,37.5000,0,126.9000\n",
            encoding="utf-8",
        )
        self.routes = self.dir / "routes.csv"
        self.routes.write_text(
            "기준일자,회사명,회사아이디,노선번호,노선아이디,순번,정류소명,정류소번호,정류소아이디,"
            "아이에스씨아이디,정류소구간거리,정류소간누적거리,주요경유지여부,상_하행\n"
            "2026-06-30,x,1,9,100,1,테스트정류장A,11001,222000001,0,,,N,1\n"
            "2026-06-30,x,1,16,101,4,테스트정류장A,11001,222000001,0,120,300,N,1\n"
            "2026-06-30,x,1,9,100,2,테스트정류장A,11001,222000001,0,120,300,N,2\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_headers_with_spaces_are_understood(self) -> None:
        stops, _ = bis_loader.load_bus_stops(self.stops)
        self.assertEqual(stops[0].name, "테스트정류장A")
        self.assertEqual(stops[0].stop_id, "222000001")

    def test_rows_without_location_are_skipped_and_counted(self) -> None:
        stops, skipped = bis_loader.load_bus_stops(self.stops)
        self.assertEqual(len(stops), 2)
        self.assertEqual(skipped, 1)

    def test_route_index_collects_routes_once(self) -> None:
        index = bis_loader.load_route_index(self.routes)
        self.assertEqual(index["222000001"], ("9", "16"))

    def test_routes_are_merged_into_nearby_stops(self) -> None:
        context = bis_loader.build_context(NODE_LAT, NODE_LON, 200, self.stops, routes_csv=self.routes)
        self.assertEqual(context.nearby_count if hasattr(context, "nearby_count") else len(context.nearby), 1)
        self.assertEqual(context.nearby[0][0].routes, ("9", "16"))
        self.assertEqual(context.stops_with_routes, 1)
        self.assertIn("routes 9/16", context.describe())
        self.assertEqual(context.skipped_rows, 1)

    def test_missing_routes_file_keeps_the_stops(self) -> None:
        context = bis_loader.build_context(NODE_LAT, NODE_LON, 200, self.stops,
                                           routes_csv=self.dir / "nope.csv")
        self.assertEqual(len(context.nearby), 1)
        self.assertEqual(context.routes_source, "none")


class TestSwappedCoordinates(unittest.TestCase):
    """The real 15074309 file has 위도/경도 swapped (위도 = 126.x, 경도 = 37.x)."""

    def test_swapped_columns_are_read_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stops.csv"
            path.write_text(
                "기준 일자,정류소 명,정류소 번호,정류소 ID,권역,행정동 명,X 좌표,위도,Y 좌표,경도\n"
                "20260228,테스트A,1,100,x,x,0,126.6563,0,37.3823\n"      # swapped like the real file
                "20260228,테스트B,2,101,x,x,0,37.3812,0,126.6548\n",       # normal order
                encoding="utf-8",
            )
            context = bis_loader.build_context(NODE_LAT, NODE_LON, 200, path)
            self.assertEqual(context.total_stops, 2)
            self.assertEqual(context.swapped_rows, 1)
            self.assertEqual(context.skipped_rows, 0)
            self.assertEqual(len(context.nearby), 2)


if __name__ == "__main__":
    unittest.main()
