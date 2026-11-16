# Monitoring Dashboard

The dashboard is implemented as part of the local demo. This document records
the feature scope and original development outline; for current run instructions
and behavior, see [the demo integration guide](demo-integration.md).

## Purpose
The monitoring dashboard provides a web interface for observing
the status of processes running on the OS project node.

## Dashboard Features
- Display worker status and process IDs (PIDs)
- Display the number of events waiting in the local outbox
- Show recent sensor readings and local decisions

The dashboard reports CPU/RAM metrics and provides controls for the simulated
WAN connection.

## OS5-1 liveness and readiness

The local API exposes:

- `GET /health/live` — confirms that the API process is responding.
- `GET /health/ready` — returns readiness only when the SQLite schema is
  available and every required worker has a fresh, running heartbeat.
- `GET /api/status` — includes the same liveness and readiness summary for the
  dashboard.

The HealthMon worker records each required process every five seconds.
Heartbeats older than 15 seconds are reported as stale. During startup, missing
heartbeats are reported as `starting`, not as healthy. The dashboard displays
the current liveness/readiness state and the checks preventing readiness.

## Original Development Plan
1. Create a basic HTTP server.
2. Build the HTML dashboard.
3. Add an API endpoint for monitoring data.
4. Connect the dashboard to live process information.
