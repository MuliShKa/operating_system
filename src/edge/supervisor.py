"""Start and shut down the edge node's worker processes."""

from __future__ import annotations

import multiprocessing
import signal
import time
from multiprocessing.queues import Queue

PROCESS_NAMES = ("SensorGen", "Processor", "HealthMon", "API")
STOP_MESSAGE = "stop"
SHUTDOWN_TIMEOUT_SECONDS = 2.0

_shutdown_requested = False


def _worker_main(process_name: str, control_queue: Queue) -> None:
	"""Wait for this worker's stop message until its real worker is connected."""
	while control_queue.get() != STOP_MESSAGE:
		pass


def _request_shutdown(_signum: int, _frame: object) -> None:
	global _shutdown_requested
	_shutdown_requested = True


def start_processes() -> dict[str, tuple[multiprocessing.Process, Queue]]:
	context = multiprocessing.get_context("spawn")
	workers = {}

	for process_name in PROCESS_NAMES:
		control_queue = context.Queue()
		process = context.Process(
			name=process_name,
			target=_worker_main,
			args=(process_name, control_queue),
		)
		process.start()
		workers[process_name] = (process, control_queue)

	return workers


def stop_processes(
	workers: dict[str, tuple[multiprocessing.Process, Queue]],
	timeout: float = SHUTDOWN_TIMEOUT_SECONDS,
) -> None:
	for _process, control_queue in workers.values():
		control_queue.put(STOP_MESSAGE)

	for process, _control_queue in workers.values():
		process.join(timeout)
		if process.is_alive():
			process.terminate()
			process.join()

	for _process, control_queue in workers.values():
		control_queue.close()
		control_queue.join_thread()


def main() -> int:
	global _shutdown_requested
	_shutdown_requested = False
	signal.signal(signal.SIGTERM, _request_shutdown)
	signal.signal(signal.SIGINT, _request_shutdown)

	workers = start_processes()
	print(f"Started workers: {', '.join(workers)}", flush=True)

	try:
		while not _shutdown_requested:
			exited = [name for name, (process, _queue) in workers.items() if not process.is_alive()]
			if exited:
				print(f"Worker exited before shutdown: {', '.join(exited)}", flush=True)
				return 1
			time.sleep(0.2)
	finally:
		stop_processes(workers)

	print("All workers stopped and reaped.", flush=True)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
