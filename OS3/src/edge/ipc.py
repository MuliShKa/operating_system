import multiprocessing as mp

from edge.bounded_queue import BoundedQueue
from edge.priority_queue import PriorityQueue


class IpcChannels:
    """
    All the communication channels between the processes of the node.

    The supervisor creates ONE IpcChannels object at startup, before starting
    the workers, and gives it to every worker it starts or restarts.
    That way every process uses the same queue and the same flags.

    - sensor_events: PriorityQueue (urgent lane + normal lane, 500 items each).
      SensorGen puts pedestrian surge alarms in the urgent lane and everything
      else in the normal lane. Processor takes items out, urgent first.
    - commands: BoundedQueue of ActuatorCommand. Processor issues speed sign
      commands, the Actuator worker checks their expiry and applies them.
    - stop: set by the supervisor to ask every worker to stop cleanly.
    - wan_online: cleared by the "cut internet" button, set again by "restore".
    """

    def __init__(self, context: mp.context.BaseContext | None = None) -> None:
        context = context or mp.get_context()

        self.sensor_events = PriorityQueue(maxsize=500, context=context)

        # Processor -> Actuator. Small: only a handful of commands per surge.
        self.commands = BoundedQueue(maxsize=100, context=context)

        self.stop = context.Event()

        # The internet is up at startup, so the flag starts SET.
        # (The OS5 version cleared it here, which made the node start offline.)
        self.wan_online = context.Event()
        self.wan_online.set()
