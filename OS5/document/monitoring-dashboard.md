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

The current implementation does not report CPU/RAM metrics or provide
WAN-disconnect controls.

## Original Development Plan
1. Create a basic HTTP server.
2. Build the HTML dashboard.
3. Add an API endpoint for monitoring data.
4. Connect the dashboard to live process information.
