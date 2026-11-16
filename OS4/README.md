# OS4 — IoT Edge Gateway (Techno-Strip Tower)

Node `EDGE_NODE_OS4_IOT_HUB` (37.3812 N, 126.6620 E). Mission: *"Make Songdo compute locally and reliably."*
Signature demo: *"Disconnect Internet → system continues operating."*

> 🎓 Educational simulation. All sensors are simulated, the mist cannon is a row in a database
> (no real pump), and the "Urban Data Platform" is a local mock receiver.

## What it does

Three simulated sensors on the tower (PM2.5, ambient noise, illumination) talk to one gateway over
Unix domain sockets. The gateway stores every reading, decides locally whether to switch the dust
suppression mist cannon, queues everything for the Urban Data Platform in a durable outbox, and keeps
working when the WAN is cut.

```
 PM25  (JSON, 2 s)   ┐
 NOISE (CSV,  1 s)   ├─ 3 Unix datagram sockets ─▶ Ingest ─▶ sensor_events ─▶ Processor ─▶ commands ─▶ Actuator
 LUX   (k=v,  5 s)   ┘     (SensorGen process)    (epoll)   (bounded queue)   │  (SQLite)  (bounded)   (relay + TTL)
                                                                              └─▶ outbox ─▶ SyncWorker ─▶ Receiver (mock platform)
 HealthMon (process_health)      API + dashboard (http://127.0.0.1:8000)      Supervisor (spawns, joins, no zombies)
```

## Run it (Linux or WSL2, Python 3.12+)

```bash
cd OS4
bash scripts/preflight.sh      # audit the host
bash scripts/setup.sh          # venv, dependencies, database in WAL mode
bash scripts/start_demo.sh     # starts the node; dashboard at http://127.0.0.1:8000
```

In the dashboard: *Simulate WAN Internet Cut* / *Restore*, and the demo switches (dust episode, very bad
dust, quiet night, PM2.5 sensor hangs / freezes, pause sensors). Ports can be moved with
`EDGE_API_PORT` and `EDGE_RECEIVER_PORT`.

Without the venv (only `psutil` and `PyYAML` are needed): `PYTHONPATH=src python3 -m edge.supervisor`.

## Scenarios

| Scenario | What it proves | Run |
|---|---|---|
| **OS4-1** Multi-stream ingestion | Three devices with different rates, units and wire formats are served by ONE process waiting in epoll (non-blocking I/O) | `python3 scenarios/os4_1_ingestion.py` |
| **OS4-2** Event time vs receipt time | `observed_at` and `received_at` are stored separately; late/out-of-order readings are ordered by event time; the 30 s TTL counts from event time | `python3 scenarios/os4_2_event_time.py` |
| **OS4-3** Mist cannon relay | PM2.5 > 50 → `MIST_CANNON_RELAY` ON with a 30 s TTL; OFF by itself 30 s after the last high reading | `python3 scenarios/os4_3_mist_relay.py` |
| **OS4-4** Backup | SQLite online backup, `flock` refuses an overlapping run, no stale lock after SIGKILL, retention, systemd timer | `python3 scenarios/os4_4_backup.py` |
| **OS4-5** WAN outage + AirKorea | 10-minute outage, backlog drain, idempotent receiver, 100 % acknowledgement, local-vs-station benchmark | `python3 scenarios/os4_5_offline_demo.py [--offline-seconds 60]` |
| **OS4-6** *(extra)* Sensor faults | Implausible values rejected; a hung or frozen PM2.5 sensor can never keep the pump running | `python3 scenarios/os4_6_sensor_faults.py` |
| **OS4-7** *(extra)* Quiet-night policy | Dark + quiet street: a "Bad" reading does not start the loud pump, a "Very Bad" one does | `python3 scenarios/os4_7_night_policy.py` |

All at once: `python3 scenarios/run_os4_scenarios.py` (`--quick` shortens OS4-5 to 60 s). Each scenario starts its
own node with throwaway databases and sockets, prints PASS/FAIL per check, and writes
`data/runs/<scenario>-<time>/report.json`. Official reports are kept in `document/results/`.

Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

## Supervision, scheduling, containers

* `systemd/songdo-edge@.service` — user service with restart policy, burst limit and cgroup limits.
  `bash scripts/install_service.sh --start`, then `systemctl --user status songdo-edge@OS4.service`.
* `systemd/songdo-backup@.{service,timer}` + `scripts/backup.sh` — backup every 15 minutes under `flock -n`.
* `container/Dockerfile`, `container/compose.yaml` — OCI image with healthcheck (`docker compose -f container/compose.yaml up --build`).

## Honest limits

* AirKorea station 131233: until the real hourly file is saved as `sources/airkorea_131233_pm25.csv`
  the benchmark uses a **synthetic sample** and says so on the dashboard and in every database row.
* The handbook's mist threshold is 50 µg/m³ (used here, configurable); the official Korean "Bad" band
  starts lower (see `document/defense-notes.md`).
* Dockerfile and systemd units were syntax-checked but not run on a real systemd/Docker host in development.
* Nothing here controls real equipment; a real pump would also need a hardware timer on the relay.

Technical report: [document/architecture.md](document/architecture.md) ·
Oral-defense preparation: [document/defense-notes.md](document/defense-notes.md)
