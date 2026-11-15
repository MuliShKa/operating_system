#!/usr/bin/env python3
"""OS3-3: overload experiment and drop-oldest policy verification.

Handbook: queue size stays capped at 500; the oldest items are discarded
cleanly without a crash.

Several producer PROCESSES flood one bounded queue much faster than a slow
consumer can read it. We sample the queue size the whole time and verify:
  - the size never exceeds 500 (no buffer bloat);
  - nothing disappears without being counted: put = received + dropped + left;
  - the items that survive are the NEWEST of each producer, in order;
  - every process exits cleanly (exit code 0, joined: no zombie).

Usage: python3 scenarios/os3_3_overload.py [--producers 4] [--items 5000]
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time

import common

sys.path.insert(0, str(common.SRC_DIR))

from edge.bounded_queue import BoundedQueue  # noqa: E402

MAXSIZE = 500


def produce(queue: BoundedQueue, producer_id: int, items: int) -> None:
    for number in range(items):
        queue.put((producer_id, number))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--producers", type=int, default=4)
    parser.add_argument("--items", type=int, default=5000, help="items per producer")
    args = parser.parse_args()
    total = args.producers * args.items

    queue = BoundedQueue(maxsize=MAXSIZE)
    producers = [mp.Process(target=produce, args=(queue, pid, args.items)) for pid in range(args.producers)]
    for process in producers:
        process.start()

    max_size_seen = 0
    received: list[tuple[int, int]] = []
    started = time.monotonic()
    # A deliberately SLOW consumer (about 2000 items/s) while the producers flood the queue.
    while any(p.is_alive() for p in producers) or queue.size():
        max_size_seen = max(max_size_seen, queue.size())
        item = queue.get(timeout=0.05)
        if item is not None:
            received.append(item)
        time.sleep(0.0005)
    for process in producers:
        process.join()
    elapsed = time.monotonic() - started

    put_count = queue.put_count.get_value()
    dropped = queue.dropped_count.get_value()

    # For each producer, the received items must be in increasing order (FIFO kept).
    # (With several producers the newest item of ONE producer may legitimately be pushed
    # out by another producer's newer items, so "newest survives" is checked below with
    # one deterministic producer and no consumer.)
    in_order = True
    for pid in range(args.producers):
        numbers = [n for p, n in received if p == pid]
        in_order = in_order and numbers == sorted(numbers)

    single = BoundedQueue(maxsize=MAXSIZE)
    flood = args.items
    for number in range(flood):
        single.put(number)
    kept = []
    while single.size():
        kept.append(single.get(timeout=0.05))
    newest_kept = kept == list(range(flood - MAXSIZE, flood))

    print(f"  {total} items put by {args.producers} producers in {elapsed:.1f} s")
    print(f"  received={len(received)} dropped={dropped} max queue size seen={max_size_seen}")

    checks = {
        f"queue size never exceeded {MAXSIZE}": max_size_seen <= MAXSIZE,
        "the flood really overloaded the queue (items were dropped)": dropped > 0,
        "every put was counted": put_count == total,
        "nothing lost without being counted (received + dropped = put)":
            len(received) + dropped == total,
        "items of each producer stay in order (FIFO)": in_order,
        f"single producer, no consumer: exactly the newest {MAXSIZE} items survive": newest_kept,
        "every producer exited cleanly (joined, exit code 0)":
            all(p.exitcode == 0 for p in producers),
    }
    passed = common.print_checks(checks)
    path = common.write_report("os3_3", {
        "scenario": "OS3-3", "producers": args.producers, "items_per_producer": args.items,
        "maxsize": MAXSIZE, "put": put_count, "received": len(received), "dropped": dropped,
        "max_queue_size_seen": max_size_seen, "elapsed_s": round(elapsed, 2), "checks": checks,
    })
    print(f"Report: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
