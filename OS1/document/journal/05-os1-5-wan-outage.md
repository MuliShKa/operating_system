# 05 – OS1-5 WAN outage and outbox

Handbook: disconnect the mock WAN for 10 minutes, events accumulate in the durable outbox,
reconnect, complete drain without duplicates.

Design:
- WAN = `wan_online` flag; the API buttons and the scenario use `/api/wan/offline|online`.
- `SyncWorker` (from OS5) sends one event at a time and marks it sent only when the
  receiver answers `accepted` with the same `event_id`.
- The receiver stores each `event_id` once (`INSERT OR IGNORE`).
- The scenario takes the last outbox ID at reconnect as the boundary; every event up to it
  must be received exactly once.

Evidence (short run, 0.5 min): backlog 60 events, drained in 2.5 s, 62 expected, 0 lost,
0 duplicates, no worker restarted, API answered while offline. 8/8 checks passed.
The official 10-minute run is still to do.
