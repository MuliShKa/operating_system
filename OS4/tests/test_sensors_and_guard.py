"""Unit tests: sensor wire formats, range checks, Ingest's make_event, channel guard.

Run: python tests/test_sensors_and_guard.py -v
"""

import math
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("EDGE_SOCKET_DIR", f"/tmp/songdo-os4-test-{os.getpid()}")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edge import guard, sensors  # noqa: E402
from edge.ingest import make_event  # noqa: E402

SPECS = sensors.load_specs()


class TestWireFormats(unittest.TestCase):
    def test_each_device_round_trips_in_its_own_format(self) -> None:
        for sid, spec in SPECS.items():
            raw = spec.encode(41.2, 1731760000.123)
            self.assertEqual(spec.parse(raw), (41.2, 1731760000.123), sid)
        # three genuinely different formats
        self.assertTrue(SPECS["PM25"].encode(1, 2).startswith(b"{"))
        self.assertTrue(SPECS["NOISE"].encode(1, 2).startswith(b"NOISE,"))
        self.assertTrue(SPECS["LUX"].encode(1, 2).startswith(b"lux="))

    def test_a_device_does_not_accept_another_devices_message(self) -> None:
        with self.assertRaises(ValueError):
            SPECS["PM25"].parse(SPECS["NOISE"].encode(40, 1))
        with self.assertRaises(ValueError):
            SPECS["NOISE"].parse(b"garbage")

    def test_periods_are_different(self) -> None:
        self.assertEqual(len({s.period_s for s in SPECS.values()}), 3)

    def test_range_check_rejects_nan_negative_and_huge(self) -> None:
        for bad in (math.nan, math.inf, -5.0, 5000.0):
            with self.assertRaises(sensors.RejectedReading):
                SPECS["PM25"].check_range(bad)
        SPECS["PM25"].check_range(0.0)
        SPECS["PM25"].check_range(999.0)


class TestMakeEvent(unittest.TestCase):
    def test_event_time_is_converted_once_to_monotonic(self) -> None:
        raw = SPECS["PM25"].encode(30.0, 1000.0)
        event = make_event(SPECS["PM25"], raw, received_at=1008.0, received_mono=500.0)
        self.assertEqual(event.observed_at, 1000.0)        # never overwritten
        self.assertEqual(event.received_at, 1008.0)
        self.assertEqual(event.lateness_s, 8.0)
        self.assertEqual(event.observed_mono, 492.0)       # 8 s older than its arrival

    def test_device_clock_ahead_is_clamped(self) -> None:
        raw = SPECS["NOISE"].encode(50.0, 2000.0)
        event = make_event(SPECS["NOISE"], raw, received_at=1990.0, received_mono=100.0)
        self.assertEqual(event.observed_mono, 100.0)
        self.assertEqual(event.lateness_s, 0.0)

    def test_rejects_implausible_and_malformed(self) -> None:
        with self.assertRaises(sensors.RejectedReading):
            make_event(SPECS["PM25"], SPECS["PM25"].encode(-1.0, 1.0), 2.0, 2.0)
        with self.assertRaises(ValueError):
            make_event(SPECS["LUX"], b"\xff\xfe", 2.0, 2.0)


class TestChannelGuard(unittest.TestCase):
    def test_no_data_then_ok_then_stale(self) -> None:
        g = guard.ChannelGuard(stale_after_s=10, stuck_check=False, stuck_repeat=6)
        self.assertEqual(g.status(0), guard.NO_DATA)
        g.heard(100.0)
        self.assertEqual(g.status(105.0), guard.OK)
        self.assertEqual(g.status(110.5), guard.STALE)
        g.heard(111.0)
        self.assertEqual(g.status(112.0), guard.OK)

    def test_late_datagram_never_moves_the_clock_backwards(self) -> None:
        g = guard.ChannelGuard(10, False, 6)
        g.heard(100.0)
        g.heard(90.0)
        self.assertEqual(g.last_heard_mono, 100.0)

    def test_stuck_after_n_identical_values_and_recovers(self) -> None:
        g = guard.ChannelGuard(10, True, 6)
        g.heard(1.0)
        for _ in range(5):
            g.value_seen(55.5)
        self.assertEqual(g.status(1.0), guard.OK)
        g.value_seen(55.5)
        self.assertEqual(g.status(1.0), guard.STUCK)
        g.value_seen(40.2)
        self.assertEqual(g.status(1.0), guard.OK)

    def test_stuck_check_can_be_disabled(self) -> None:
        g = guard.ChannelGuard(10, False, 2)
        g.heard(1.0)
        for _ in range(10):
            g.value_seen(0.0)
        self.assertEqual(g.status(1.0), guard.OK)


if __name__ == "__main__":
    unittest.main()
