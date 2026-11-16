# Processes and Lifecycle

This task owns the lifecycle of the six edge-node worker processes.

## Current behavior

- `src/edge/supervisor.py` starts `SensorGen`, `Processor`, `HealthMon`, `API`,
  `Receiver`, and `SyncWorker` as separate processes using the `spawn` method.
- SensorGen sends readings through the shared bounded queue; Processor stores
  readings in SQLite and applies the water-level rule; HealthMon records
  heartbeats; API serves the local dashboard and status endpoint.
- If a worker exits unexpectedly, the supervisor records its exit code and
  restarts only that worker, reusing the existing IPC channels. It allows up to
  three restarts per worker in a 60-second window; exceeding the limit stops
  the node with an error.
- The dashboard exposes each worker's current PID, restart count, and last exit
  code. Restart attempts are also written to the process-health table.
- SIGTERM or SIGINT sets the shared stop event so workers can finish and exit.
- The supervisor calls `join()` for every child. A child that does not stop
  within three seconds is terminated, then killed if necessary, with bounded
  waits so it is reaped rather than left as a zombie.
- The dashboard reads live status from `/api/status` while the demo is running.

## Run

```bash
PYTHONPATH=src python3.12 -m edge.supervisor
```

Press Ctrl+C to request a graceful shutdown. A service manager can send SIGTERM
to request the same shutdown.

## Scope

SIGCHLD handlers and systemd configuration are not implemented. The supervisor
polls worker processes for exits and uses the bounded restart policy above.
Upstream outbox synchronization is implemented by the local mock receiver and
SyncWorker; it is not a production remote service.