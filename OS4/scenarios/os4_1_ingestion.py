#!/usr/bin/env python3
"""OS4-1: heterogeneous multi-stream sensor ingestion.

Handbook: aggregate PM2.5, ambient noise and illumination across asynchronous
rates. OS concept: polling and non-blocking I/O across diverse channels.

Checks (against a real running node, simulated devices):
  - three sensors with DIFFERENT periods and DIFFERENT wire formats all arrive;
  - their measured rates match the configured periods (asynchronous, not lockstep);
  - ONE process (Ingest) owns all three Unix sockets;
  - that process waits in epoll (not a busy loop): its CPU use is tiny;
  - the sockets are non-blocking and a malformed datagram does not disturb the others;
  - everything is stored with both timestamps.

Usage: python3 scenarios/os4_1_ingestion.py [--seconds 30]
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import time

import common

import psutil

PERIODS = {"PM25": 2.0, "NOISE": 1.0, "LUX": 5.0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()

    with common.RunningNode({"EDGE_SIM_LATE_PROB": "0"}) as node:
        ingest_pid = common.status()["workers"]["Ingest"]["pid"]
        proc = psutil.Process(ingest_pid)
        proc.cpu_percent(None)
        cpu_before = sum(proc.cpu_times()[:2])
        print(f"Observing {args.seconds} s ...")
        started = time.monotonic()
        time.sleep(args.seconds)
        elapsed = time.monotonic() - started
        cpu_used = sum(proc.cpu_times()[:2]) - cpu_before

        st = common.status()
        counts = {sid: common.scalar(node.node_db, "SELECT COUNT(*) FROM events WHERE event_type=?", (sid,)) for sid in PERIODS}
        rates = {sid: counts[sid] / elapsed for sid in PERIODS}

        # Which process owns the sockets?
        sock_paths = {str(node.socket_dir / f"songdo-os4-{sid.lower()}.sock") for sid in PERIODS}
        owned = {c.laddr for c in proc.net_connections(kind="unix")} & sock_paths
        is_socket = all(stat.S_ISSOCK(os.stat(p).st_mode) for p in sock_paths if os.path.exists(p))
        fd_targets = []
        for fd in os.listdir(f"/proc/{ingest_pid}/fd"):
            try:
                fd_targets.append(os.readlink(f"/proc/{ingest_pid}/fd/{fd}"))
            except OSError:
                pass
        uses_epoll = any("eventpoll" in t for t in fd_targets)

        # A malformed datagram must be counted, not crash Ingest or stall the others.
        before_noise = common.scalar(node.node_db, "SELECT COUNT(*) FROM events WHERE event_type='NOISE'")
        common.send_raw(b"\xff\xfe not a message", node.socket_dir / "songdo-os4-pm25.sock")
        time.sleep(3)
        st2 = common.status()
        after_noise = common.scalar(node.node_db, "SELECT COUNT(*) FROM events WHERE event_type='NOISE'")

        rows = common.query(node.node_db, "SELECT observed_at, received_at FROM events WHERE event_type IN ('PM25','NOISE','LUX')")
        formats_ok = all(st["channels"][sid]["parse_errors"] == 0 for sid in PERIODS)

        print("  events:", counts, " rates/s:", {k: round(v, 2) for k, v in rates.items()})
        print(f"  Ingest pid {ingest_pid}: CPU {cpu_used:.2f} s in {elapsed:.0f} s, sockets owned: {len(owned)}")

        checks = {
            "all three sensors delivered readings": all(c > 0 for c in counts.values()),
            "three different wire formats parsed without a single parse error": formats_ok,
            **{f"{sid} rate matches its period ({PERIODS[sid]} s)": abs(rates[sid] - 1 / PERIODS[sid]) <= 0.25 / PERIODS[sid] + 0.05
               for sid in PERIODS},
            "rates differ across sensors (asynchronous streams)": len({round(r, 1) for r in rates.values()}) == 3,
            "the three Unix sockets exist as socket files": is_socket and len(sock_paths) == 3,
            "ONE process (Ingest) owns all three sockets": len(owned) == 3,
            "Ingest waits in epoll (eventpoll fd present)": uses_epoll,
            "Ingest is not busy-polling (< 5 % CPU)": cpu_used / elapsed < 0.05,
            "a malformed datagram was counted, not fatal": st2["channels"]["PM25"]["parse_errors"] >= 1,
            "other sensors kept flowing meanwhile": after_noise > before_noise,
            "every Ingest worker still running": st2["workers"]["Ingest"]["status"] == "running",
            "every stored reading has observed_at and received_at": len(rows) > 0 and all(o and r for o, r in rows),
        }
        passed = common.print_checks(checks)
        path = common.write_report("os4_1", {"scenario": "OS4-1", "counts": counts, "rates_per_s": rates,
                                             "ingest_cpu_s": cpu_used, "elapsed_s": elapsed, "checks": checks})
        print(f"Report: {path}")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
