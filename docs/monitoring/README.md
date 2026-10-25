# Monitoring Dashboard

## 1. Overview

The monitoring dashboard provides a local web interface for observing the
Songdo Edge Intelligence node. It combines worker-process information,
recent sensor readings, edge decisions, and WAN connectivity simulation
in one place.

The dashboard is intended for local development and demonstration.

## 2. Features

### Process monitoring
- Displays the status of worker processes.
- Shows process IDs (PIDs) when available.
- Displays CPU usage and resident memory usage for running processes.
- Includes the API server, sensor generator, processor, health monitor,
  receiver, and synchronization worker.

CPU usage is obtained through `psutil`. Its first reading may be zero or
incomplete because CPU utilization is measured over time.

### Sensor and decision monitoring
- Shows recent sensor readings.
- Displays recent edge decisions.
- Shows the number of events waiting to be synchronized.

### WAN connectivity simulation
The dashboard provides controls to simulate WAN connectivity changes.
These controls change the shared WAN connectivity flag used by the
application.

- **Offline:** simulates loss of WAN connectivity.
- **Online:** restores simulated WAN connectivity.

This is an application-level simulation; it does not disconnect the
computer from the actual network.

## 3. Architecture

The dashboard consists of three main components:

1. **Web interface:** `src/ui/static/index.html`
2. **HTTP API server:** `src/edge/api_server.py`
3. **Shared application state:** maintained by the supervisor and shared
   with worker processes through the IPC layer.

The supervisor starts the workers and passes the shared state and
communication channels to the API server. The server reads the current
state and returns JSON data to the dashboard.

Process metrics are collected with `psutil`.

## 4. API Endpoints

The API server listens on `127.0.0.1:8000`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/` | Serves the monitoring dashboard |
| GET | `/api/status` | Returns worker status, process metrics, recent readings, recent decisions, pending events, and WAN state |
| POST | `/api/wan/offline` | Disables the simulated WAN connectivity flag |
| POST | `/api/wan/online` | Enables the simulated WAN connectivity flag |

Example status request:

```bash
curl http://127.0.0.1:8000/api/status
