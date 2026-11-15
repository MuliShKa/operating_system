"""Everything the node's processes share: two queues, two flags, and the worker list."""

from edge.core.bounded_queue import BoundedQueue
from edge.node_config import QUEUE_SIZE


class IpcChannels:
    """
    Created once by the supervisor and given to every worker, so they all use
    the same queues and flags.

    - Queue: a stream of messages in one direction.
    - Event: a shared on/off flag.
    """

    def __init__(self, context) -> None:
        # SensorGen -> Processor: sensor readings.
        self.sensor_events = BoundedQueue(QUEUE_SIZE, context)
        # Processor -> Actuator: damper commands (OS1-3).
        self.commands = BoundedQueue(100, context)
        # Set by the supervisor to ask every worker to stop.
        self.stop = context.Event()
        # Cleared by the dashboard's "cut internet" button, set again by "restore".
        # The internet is up at startup.
        self.wan_online = context.Event()
        self.wan_online.set()


def list_workers(state) -> dict[str, dict]:
    """Return {worker name: {"pid": ..., "status": ...}} from the shared state."""
    return {key[len("worker:"):]: value for key, value in dict(state).items() if key.startswith("worker:")}
