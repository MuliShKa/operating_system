# Processes and Lifecycle

This task owns the lifecycle of the four edge-node worker processes.

## Current behavior

- `src/edge/supervisor.py` starts `SensorGen`, `Processor`, `HealthMon`, and
  `API` as separate processes using the `spawn` start method.
- SensorGen sends readings through the shared bounded queue; Processor stores
  readings in SQLite and applies the water-level rule; HealthMon records
  heartbeats; API serves the local dashboard and status endpoint.
- SIGTERM or SIGINT sets the shared stop event so workers can finish and exit.
- The supervisor calls `join()` for every child. A child that does not stop
  within three seconds is terminated and joined, so it is reaped rather than left
  as a zombie.
- The dashboard reads live status from `/api/status` while the demo is running.

## Run

```bash
PYTHONPATH=src python3.12 -m edge.supervisor
```

Press Ctrl+C to request a graceful shutdown. A service manager can send SIGTERM
to request the same shutdown.

## Scope

Automatic restart after a worker is killed, SIGCHLD handling, systemd
configuration, and upstream outbox synchronization are not implemented yet.
The supervisor detects an unexpected worker exit, stops and reaps the remaining
workers, and exits with an error instead of claiming that restart recovery is
implemented.