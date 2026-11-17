# 10 – Bonus: resource trends & historical comparison

Goal: the optional Phase 3 of the assessment, *"add historical comparisons and
resource trends; plotted metrics agree with exported manifests"*.
Kept as a **separate scenario**: OS1-1 … OS1-5 are unchanged.

## What was added

| File | Role |
|---|---|
| `src/edge/os1_bonus_trends/history.py` | Rates over time from `process_health`, previous vs last window, CSV export |
| `src/edge/core/api_server.py` | `GET /api/history` and `GET /api/history.csv` (same data) |
| `src/ui/static/index.html` | Card "Bonus – Resource Trends": chart, comparison table, Export CSV |
| `scenarios/os1_bonus_trends.py` | 30 s idle + 30 s load, compares the API data with the CSV, draws an SVG |
| `tests/test_os1_bonus_trends.py` | 5 tests (rates, PID change, comparison, CSV round trip) |

## Run (2026-11-17)

3/3 checks PASS, 232 points. Evidence in `document/results/os1_bonus_trends.{json,csv,svg}`.
Involuntary switches / s, idle → load: Processor 3.8 → 12.5, ProcSampler 7.1 → 19.4,
SyncWorker 3.5 → 10.3.
