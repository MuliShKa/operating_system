# 09 – Simplifying the source code

Goal: make the code easy to read and present, without changing what the node does.
Source code: about 1040 lines removed, 420 added (src, tests, scenarios).

## What changed

| File | Change |
|---|---|
| `models.py` | Plain classes → `@dataclass`. Removed the unused `ProcessHealth` and `EdgeDecision`. |
| `decision.py` | `make_decision()` returned `(decision, expires_at)`; now `make_command()` returns one `ActuatorCommand` (or None). `is_command_expired` → `is_expired`. |
| `actuator.py` | `handle_command` → `check_command`. |
| `bounded_queue.py` | 169 → 45 lines. Same drop-oldest policy; `get()` now blocks on the queue instead of polling every 10 ms. Removed the unused counters and `STOP` sentinel. |
| `ipc.py` | Removed the mention of Unix sockets (not used in OS1). Added `list_workers(state)`, used by the API and the sampler. |
| `storage.py` | `get_connection` + `_managed_connection` → one `connect()`. Shorter SQL. `get_pending_event_count` → `count_pending_events`, `mark_event_sent` → `mark_sent`, `mark_event_attempt` → `mark_failed_attempt`. |
| `SensorGen.py` | Renamed `sensors.py`, `run_sensor_gen` → `run_sensors`. The process is still called "SensorGen". |
| `supervisor.py` | One dict of workers instead of a name list + a dict. Worker state stored as one key per worker (`worker:<name>` → `{pid, status}`). |
| `api_server.py` | No more `psutil`: CPU % and memory come from ProcSampler's `/proc` readings. Status building moved to `build_status()`. |
| `proc_sampler.py` | Computes CPU % between two samples (for the dashboard). |
| `sync_worker.py` | One loop instead of three nested `continue` branches. |
| `shared_counter.py`, `occupancy.py` | `get_value()` → `.value`, `_turnstile_entry` → `turnstile`. |
| `requirements.txt` | `psutil` removed; only PyYAML is needed. |

## Checks

- 40 unit tests OK (one test for a `None` expiry was removed: that case cannot happen any more).
- Live run on spare ports: 8 workers with PID, CPU and memory on the dashboard,
  building tagged, damper applied, WAN cut → pending grows, restore → 0, Ctrl+C →
  "All workers stopped and reaped".

## OS1-4 re-run (official, 30 s idle + 30 s load)

The old report was measured with the 10 ms polling queue. New report in
`document/results/os1_4_contention.json`, all 3 checks PASS:

| Worker | Voluntary/s idle, before → after | Involuntary/s idle → load (after) |
|---|---|---|
| Processor | 130 → 37 | 2.4 → 13.7 |
| Actuator | 106 → 12 | 0.3 → 2.3 |

## Sub-folders in `src/edge/`

The modules were moved into one folder per scenario (`os1_1_ingestion/` …
`os1_5_wan_outage/`, same names as the scripts in `scenarios/`) and `core/` for
what every scenario shares. `supervisor.py` and `node_config.py` stay at the top,
so `python -m edge.supervisor` (start_demo.sh, systemd, Docker) is unchanged.
The backup module is now `edge.core.backup` (`scripts/backup.sh` updated).
The full tree is in `README.md` and `document/architecture.md`.

Checks: 40 tests OK; live run (8 workers, WAN cut and restore, clean stop); `scripts/backup.sh` OK.

## Final check (2026-11-15)

- 40 unit tests OK.
- `run_os1_scenarios.py --quick`: OS1-1 … OS1-5 all PASS (31 checks).
- Official OS1-4 re-run: PASS, report replaced.

## OS1-5 re-run (official, 10 min, code without decorators)

All 8 checks PASS. Report replaced in `document/results/os1_5_wan_outage.json`:
600 s outage, 1200 events in the backlog, 598 decisions made offline,
drained in 9.5 s (was 11.5 s), 1202 expected / 1220 received, 0 lost, 0 duplicates.
