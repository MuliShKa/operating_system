import multiprocessing as mp

from edge.bounded_queue import BoundedQueue
from edge.config import load_config

# Simulation switches, flipped from the dashboard / API (POST /api/sim/<name>/<on|off>).
# They only steer the SIMULATED sensors; the node code itself never reads them.
SIM_FLAGS = (
    "episode",      # a dust episode: PM2.5 rises above the Bad threshold
    "extreme",      # make the episode Very Bad (> 75)
    "night",        # dark and quiet street (OS4-7)
    "mute_pm25",    # the PM2.5 device hangs and sends nothing (OS4-6)
    "stuck_pm25",   # the PM2.5 device freezes on its last value (OS4-6)
    "pause",        # all devices silent (lets a scenario wait for an empty outbox)
)


class IpcChannels:
    """
    All the communication channels between the processes of the node.

    The supervisor creates ONE IpcChannels object at startup, before starting
    the workers, and gives it to every worker. That way every process uses the
    same queues and the same flags.

    Sensor data does NOT travel through this object: the devices talk to the
    Ingest process through Unix domain sockets (files on disk), so the Ingest
    process could be restarted or replaced without the devices noticing.

    - sensor_events: BoundedQueue (500, drop-oldest). Ingest -> Processor.
    - commands: BoundedQueue of ActuatorCommand. Processor -> Actuator.
    - stop: set by the supervisor to ask every worker to stop cleanly.
    - ingest_done: set by Ingest after its last datagram was queued, so the
      Processor knows nothing more can arrive and can drain and exit.
    - wan_online: cleared by the "cut internet" button, set again by "restore".
    - sim: the simulation switches above.
    """

    def __init__(self, context: mp.context.BaseContext | None = None) -> None:
        context = context or mp.get_context()
        queue_size = int(load_config()["queue_size"])

        self.sensor_events = BoundedQueue(maxsize=queue_size, context=context)

        # Processor -> Actuator. Small: only a handful of commands per episode.
        self.commands = BoundedQueue(maxsize=100, context=context)

        self.stop = context.Event()
        self.ingest_done = context.Event()

        # The internet is up at startup, so the flag starts SET.
        self.wan_online = context.Event()
        self.wan_online.set()

        self.sim = {name: context.Event() for name in SIM_FLAGS}
