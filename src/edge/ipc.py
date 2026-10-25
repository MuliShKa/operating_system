import multiprocessing as mp

from edge.bounded_queue import BoundedQueue


class IpcChannels:
    """
    All the communication channels between the processes of the node.

    The supervisor creates ONE IpcChannels object at startup, before starting
    the workers, and gives it to every worker it starts or restarts.
    That way every process uses the same queue and the same flags.

    Which tool for which job:
    - BoundedQueue: a stream of data in one direction (sensor events).
    - Event: a shared on/off flag (stop everything, internet up or down).
    - UnixSocketServer/Client: ask a question, get an answer (API asks for status).
    """

    def __init__(self, context: mp.context.BaseContext | None = None) -> None:
        context = context or mp.get_context()

        # The sensor_events queue: SensorGen puts readings here, Processor takes them out.
        self.sensor_events = BoundedQueue(maxsize=500, context=context)

        # The stop flag is set by the supervisor to ask every worker to stop cleanly.
        self.stop = context.Event()

        # The WAN starts online. The dashboard can clear this flag
        # to simulate an outage and set it again to restore connectivity.
        self.wan_online = context.Event()
        self.wan_online.set()