"""Start and shut down the edge node's worker processes."""

from __future__ import annotations

import multiprocessing
import signal
import time
from multiprocessing.queues import Queue

PROCESS_NAMES = ("SensorGen", "Processor", "HealthMon", "API")
# Every worker gets this message when the program should stop.
STOP_MESSAGE = "stop"
# Workers have some time to stop before we force them to exit.
SHUTDOWN_TIMEOUT_SECONDS = 2.0

_shutdown_requested = False


def _worker_main(process_name: str, control_queue: Queue) -> None:
	"""Wait for stop while the real worker function is not connected yet."""
	# This is a small placeholder for the real work of each process.
	while control_queue.get() != STOP_MESSAGE:
		pass


def _request_shutdown(_signum: int, _frame: object) -> None:
	global _shutdown_requested
	# The main loop will stop after this flag changes.
	_shutdown_requested = True


def start_processes() -> dict[str, tuple[multiprocessing.Process, Queue]]:
	# Spawn starts each worker as a new process with separate memory.
	context = multiprocessing.get_context("spawn")
	workers = {}

	for process_name in PROCESS_NAMES:
		# The queue lets the supervisor tell this worker to stop.
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
	# Send stop to every worker before waiting for them.
	for _process, control_queue in workers.values():
		control_queue.put(STOP_MESSAGE)

	# Join waits for the child, so it does not stay as a zombie.
	for process, _control_queue in workers.values():
		process.join(timeout)
		if process.is_alive():
			# Stop a worker that did not finish in time.
			process.terminate()
			process.join()

	# Close queue resources after all workers have stopped.
	for _process, control_queue in workers.values():
		control_queue.close()
		control_queue.join_thread()


def main() -> int:
	global _shutdown_requested
	_shutdown_requested = False
	# Both Ctrl+C and a service stop ask for a clean shutdown.
	signal.signal(signal.SIGTERM, _request_shutdown)
	signal.signal(signal.SIGINT, _request_shutdown)

	workers = start_processes()
	print(f"Started workers: {', '.join(workers)}", flush=True)

	try:
		while not _shutdown_requested:
			# Stop if a worker exits before we ask it to stop.
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
