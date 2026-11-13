# 06 – Deployment: systemd, scheduled backup, container

Rubric item 4 "Supervision, Scheduling & Containerization" (15 points): systemd user service
with burst limits and resource constraints, flocked scheduled maintenance, OCI Dockerfile and
compose with healthcheck. All three folders were empty for every team (3/15 at the midterm).

## systemd (`systemd/`, `scripts/install_service.sh`)
- `songdo-edge@.service`: user unit template, instance = team (`songdo-edge@OS1.service`).
  `Restart=on-failure`, `RestartSec=2`, burst limit `StartLimitBurst=5` in
  `StartLimitIntervalSec=60`, `MemoryHigh=384M`, `MemoryMax=512M`, `CPUQuota=150%`,
  `TasksMax=128`, `KillSignal=SIGTERM`, `KillMode=mixed`, `ExecStartPre` = preflight.
- systemd needs absolute paths, so the files use `@PROJECT_DIR@` and the install script fills it in.
- The supervisor still exits with 1 when a worker dies (worker-level restart is OS5-2);
  systemd turns that into a node-level restart.
- Check: `systemd-analyze --user verify` passes. Test as a transient unit (`systemd-run --user`,
  same properties, nothing installed): `kill -9` of the Processor → restart counter 1 after 2 s,
  8/8 workers back; limits shown by `systemctl show` (MemoryMax 512 MiB, CPU 1.5 s/s, 128 tasks);
  memory used ~165 MB.

## Scheduled backup (`scripts/backup.sh`, `src/edge/backup.py`, `systemd/songdo-backup@.*`)
- `flock -n` on fd 9: a second run while one is active prints "Backup skipped" and exits.
  The kernel frees the lock if the process dies, so no stale lock.
- SQLite online backup API (`Connection.backup`, 256 pages per step): the node keeps writing.
  The copy goes to a `.partial` file, passes `PRAGMA integrity_check`, then is renamed
  (atomic). Only the newest 10 copies are kept (`EDGE_BACKUP_KEEP`).
- Timer: every 15 minutes, `Persistent=true`. No crontab on this machine, so systemd timer only.
- Check: overlap test (second run skipped), copy of the 10-minute outage DB has the same
  1224 events and `integrity_check = ok`, backup of a live node OK, retention OK.
  Tests: `tests/test_backup.py`.
- Overlap with OS4-4 (scheduled backup scenario): this is the OS1 node's own maintenance job.

## Container (`container/Dockerfile`, `container/compose.yaml`, `.dockerignore`)
- `python:3.12-slim`, non-root user `edge`, database in a volume, `STOPSIGNAL SIGTERM`.
- The API listens on `EDGE_API_HOST=0.0.0.0` inside the container; compose publishes it only
  on `127.0.0.1` of the host.
- Healthcheck: the API answers and every worker reports `running`.
- compose: `restart: on-failure:5`, `mem_limit: 512m`, `cpus: 1.5`, `pids_limit: 128`,
  `stop_grace_period: 20s`.
- `.dockerignore` keeps `project/` (grades, course files), `data/` and `.venv/` out of the image.
- Check: image builds, container `healthy`, `kill -9` of the Processor inside → Docker restart
  count 1, healthy again, events kept in the volume, `docker stop` → exit code 0 and
  "All workers stopped and reaped".
