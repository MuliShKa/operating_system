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

Official run (2026-11-13, 600 s outage, receiver on port 8011): 1202 events queued in the
outbox, decisions kept being made offline, nothing sent while offline, backlog drained in
11.5 s after reconnect, 1202 expected / 0 lost / 0 duplicates, no worker crashed or changed
PID. 8/8 checks. Report: `document/results/os1_5_wan_outage.json`.
