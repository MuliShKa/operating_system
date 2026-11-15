#!/usr/bin/env python3
"""OS3-2: priority-aware bounded queue processing.

Handbook: prioritize pedestrian surge alarms over background sensor logging.
A bounded queue prevents buffer bloat and guarantees low-latency processing.

A producer process queues a backlog of background logs with an alarm every
30th item. We then look at the position at which each alarm is handled:
  - one FIFO queue: every alarm waits behind all the logs queued before it;
  - PriorityQueue (urgent lane first): alarms skip the whole backlog.
Each lane stays bounded at 500 items.

Usage: python3 scenarios/os3_2_priority.py [--items 300]
"""

from __future__ import annotations

import argparse
import sys

import common

sys.path.insert(0, str(common.SRC_DIR))

from edge.priority_demo import PriorityDemo  # noqa: E402
from edge.priority_queue import PriorityQueue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", type=int, default=300)
    parser.add_argument("--alarm-every", type=int, default=30)
    args = parser.parse_args()

    demo = PriorityDemo(items=args.items, alarm_every=args.alarm_every)
    fifo = demo.run(use_priority=False)
    priority = demo.run(use_priority=True)
    alarms = args.items // args.alarm_every
    print(f"  FIFO queue     : alarms handled at positions {fifo}")
    print(f"  PriorityQueue  : alarms handled at positions {priority}")

    # Lane bound: a flood in each lane keeps both at 500.
    queue = PriorityQueue(maxsize=500)
    for number in range(2000):
        queue.put(("log", number))
        queue.put(("alarm", number), urgent=True)
    stats = queue.stats()

    # The average wait of an alarm, measured as "items handled before it".
    fifo_wait = sum(fifo) / len(fifo) if fifo else 0
    priority_wait = sum(priority) / len(priority) if priority else 0
    print(f"  average items handled before an alarm: FIFO {fifo_wait:.0f}, priority {priority_wait:.1f}")

    checks = {
        "FIFO: every alarm waits behind the logs queued before it":
            fifo == list(range(args.alarm_every - 1, args.items, args.alarm_every)),
        "PriorityQueue: alarms are handled first (positions 0..n-1)":
            priority == list(range(alarms)),
        "every alarm is handled earlier with priority than with FIFO":
            all(p < f for p, f in zip(priority, fifo)),
        "urgent lane stays bounded at 500":
            stats["urgent"]["size"] == 500,
        "normal lane stays bounded at 500":
            stats["normal"]["size"] == 500,
        "overflow is counted, not silently lost (dropped = put - 500, per lane)":
            stats["urgent"]["dropped_count"] == 1500 and stats["normal"]["dropped_count"] == 1500,
    }
    passed = common.print_checks(checks)
    path = common.write_report("os3_2", {
        "scenario": "OS3-2", "items": args.items, "alarm_every": args.alarm_every,
        "fifo_positions": fifo, "priority_positions": priority,
        "average_wait_fifo": fifo_wait, "average_wait_priority": priority_wait,
        "lane_stats_after_flood": stats, "checks": checks,
        "known_cost": "starvation of normal items while alarms keep coming (fix: aging)",
    })
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
