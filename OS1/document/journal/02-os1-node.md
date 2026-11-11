# 02 – OS1 node from the OS5 base

Copied from `OS5/`: `.gitignore`, `.python-version`, `requirements.txt`, `sql/schema.sql`,
`scripts/*.sh`, `src/ui/static/index.html`, and in `src/edge/`: `bounded_queue`,
`shared_counter`, `ipc`, `models`, `storage`, `receiver`, `sync_worker`, `api_server`,
`supervisor`, `SensorGen`, `processor`, `decision`.

Not copied: `race_demo`, `deadlock_demo`, `priority_*`, `unix_socket` (other scenarios).

Adapted:
- `config/node.yaml` + `node_config.py`: the values come from the handbook §3.1 and are
  read at startup instead of being hard-coded.
- `SensorGen`: CO2 + temperature, each reading stamped with `time.monotonic()`.
- `ipc.py`: second bounded queue `commands` (Processor → Actuator); WAN starts online.
- `supervisor.py`: 8 workers (adds `Actuator` and `ProcSampler`).
- `api_server.py`: `/api/status` also returns the node, damper %, applied/expired counts
  and the last `/proc` samples.
- `receiver.py`: database next to the node database, so runs do not share data.
- Dashboard: CO2, temperature and damper cards.
- `scenarios/node_runner.py`: starts an isolated node per scenario run (own DB, log, report).
