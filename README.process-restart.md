# Processes and Restart (W1-W2)

This task owns the lifecycle of the four edge-node worker processes.

## Current behavior

- `src/edge/supervisor.py` starts `SensorGen`, `Processor`, `HealthMon`, and
  `API` as separate processes using the `spawn` start method.
- Each worker has a private control queue. The supervisor sends the `stop`
  message to every worker when it receives SIGTERM or SIGINT.
- The supervisor calls `join()` for every child. A child that does not stop
  within two seconds is terminated and joined, so it is reaped rather than left
  as a zombie.
- The worker bodies are lifecycle stubs until the corresponding components are
  connected by their owners.

## Run

```bash
python3.12 src/edge/supervisor.py
```

Press Ctrl+C to request a graceful shutdown. A service manager can send SIGTERM
to request the same shutdown.

## Scope

This branch covers W1-W2. Automatic restart after a worker is killed, SIGCHLD
handling, systemd configuration, and recovery during the offline demo are
scheduled for W5-W6. The current supervisor detects an unexpected worker exit,
stops and reaps the remaining workers, and exits with an error instead of
claiming that restart recovery is implemented.