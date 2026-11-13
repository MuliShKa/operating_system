# 03 – OS1-3 ventilation rule and damper TTL

Handbook: CO2 > 1000 ppm → `HVAC_DAMPER_PCT = 100 %`, TTL 15.0 s, monotonic clock.

Design:
- The expiry is `reading monotonic time + 15 s`. In OS5 the TTL started at decision time
  and was checked immediately, which the professor flagged ("TTL checks immediately and
  no actuator consumer").
- The Processor only issues the command (`HVAC_DAMPER_PCT` row) and puts it in the
  `commands` queue. The new `Actuator` worker checks the expiry with its own
  `time.monotonic()` right before acting and records `DAMPER_APPLIED` or `COMMAND_EXPIRED`.
- Comparing monotonic times between processes is valid on Linux: `CLOCK_MONOTONIC` is
  system-wide.
- `EDGE_ACTUATOR_DELAY_S` slows the actuator down to demonstrate expiry on a live node.

Evidence (short run, `--seconds 8`): boundary 6/6; live run 5 high readings → 5 commands →
5 applied, 0 expired; actuator delayed 16 s → 1 command checked, rejected, damper stayed 0 %.
11/11 checks passed. Unit tests: `tests/test_os1_3_ventilation.py`, `tests/test_demo_integration.py`.

Official run (2026-11-13, 15 s): 7 readings above 1000 ppm → 7 commands → 7 applied, 0 expired;
actuator delayed 16 s → the command it reached was rejected, damper stayed at 0 %. 11/11 checks.
Report: `document/results/os1_3_ventilation.json`.
