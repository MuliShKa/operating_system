"""AirKorea baseline benchmark (scenario OS4-5): compare local PM2.5 with a nearby station.

Songdo station 131233 publishes hourly PM2.5. The node keeps a CACHED copy of it
on local disk (sources/airkorea_131233_pm25.csv) so the benchmark still works
while the WAN is down; the dashboard shows "SAMPLE DATA" when only the synthetic
sample is present.

A low-cost sensor on a tower and a regulatory station a few hundred metres away
will never agree exactly, so the check reports the BIAS (local - station) and
whether it stays inside a tolerance, plus whether both fall in the same Korean
air-quality grade.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Korea has no daylight saving time, so a fixed UTC+9 offset is exact (and does
# not depend on the tz database being installed, e.g. in a slim container).
KST = timezone(timedelta(hours=9))

# Korean PM2.5 grades (as we recall them; verify before quoting): Good 0-15,
# Normal 16-35, Bad 36-75, Very Bad 76+. The handbook uses 50 as its "Bad"
# threshold for the mist cannon; that is a separate, configurable number.
GRADE_BOUNDS = ((15, "GOOD"), (35, "NORMAL"), (75, "BAD"))


def pm25_grade(value: float) -> str:
    for upper, name in GRADE_BOUNDS:
        if value <= upper:
            return name
    return "VERY_BAD"


def _parse_kst(text: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM'. AirKorea writes midnight as '24:00' of the previous day."""
    text = text.strip()
    date_part, time_part = text.split(" ")
    hour_text, minute_text = time_part.split(":")[:2]
    hour, minute = int(hour_text), int(minute_text)
    day = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=KST)
    if hour == 24:
        return day + timedelta(days=1, minutes=minute)
    return day.replace(hour=hour, minute=minute)


@dataclass
class Baseline:
    station: str
    source: str                      # file name actually used ("" = none)
    is_sample: bool
    by_hour: dict[str, float] = field(default_factory=dict)       # "YYYY-MM-DD HH" -> pm25
    hour_of_day: dict[int, float] = field(default_factory=dict)   # 0..23 -> mean pm25
    rows_read: int = 0
    rows_skipped: int = 0

    @property
    def available(self) -> bool:
        return bool(self.by_hour)

    def lookup(self, epoch: float) -> tuple[float, str] | None:
        """Station value for the hour containing `epoch` (UTC seconds).

        Returns (value, 'exact-hour') when the file has that very hour, else
        (value, 'hour-of-day') using the mean of that hour over the file (a
        typical-day profile), else None if the file is empty.
        """
        local = datetime.fromtimestamp(epoch, KST)
        key = local.strftime("%Y-%m-%d %H")
        if key in self.by_hour:
            return self.by_hour[key], "exact-hour"
        if local.hour in self.hour_of_day:
            return self.hour_of_day[local.hour], "hour-of-day"
        return None

    def to_dict(self) -> dict:
        return {
            "station": self.station,
            "source": self.source or "none",
            "is_sample": self.is_sample,
            "hours": len(self.by_hour),
            "rows_read": self.rows_read,
            "rows_skipped": self.rows_skipped,
        }


def _read_csv(path: Path, baseline: Baseline) -> None:
    sums: dict[int, list[float]] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            baseline.rows_read += 1
            try:
                moment = _parse_kst(row["datetime"])
                value = float(row["pm25"])
            except (KeyError, ValueError, TypeError):
                baseline.rows_skipped += 1     # empty, "-" or malformed: counted, never silent
                continue
            baseline.by_hour[moment.strftime("%Y-%m-%d %H")] = value
            sums.setdefault(moment.hour, []).append(value)
    baseline.hour_of_day = {hour: statistics.fmean(values) for hour, values in sums.items()}


def load_baseline(station: str, primary_csv: Path, fallback_csv: Path) -> Baseline:
    """Load the real cached file if present, else the synthetic sample, else an empty baseline."""
    for path, is_sample in ((primary_csv, False), (fallback_csv, True)):
        if path.exists():
            baseline = Baseline(station=station, source=path.name, is_sample=is_sample)
            _read_csv(path, baseline)
            if baseline.available:
                return baseline
    return Baseline(station=station, source="", is_sample=False)


def compare(local_median: float, baseline_value: float, tolerance: float) -> dict:
    """Bias and agreement between the local median and the station value."""
    bias = local_median - baseline_value
    return {
        "bias": round(bias, 2),
        "local_grade": pm25_grade(local_median),
        "baseline_grade": pm25_grade(baseline_value),
        "status": "AGREE" if abs(bias) <= tolerance else "DEVIATES",
    }
