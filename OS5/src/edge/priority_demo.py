import multiprocessing as mp
from multiprocessing.synchronize import Event

from edge.bounded_queue import STOP, BoundedQueue
from edge.priority_queue import PriorityQueue


class PriorityDemo:
    """
    Priority demo (OS3-2): pedestrian alarms hidden in a flood of background logs.

    A producer process puts 300 items: every 30th one is an urgent alarm.
    The consumer only starts once they are all queued (a backlog), then we look
    at the position at which each alarm comes out.

    - One FIFO queue: an alarm waits behind every log put before it.
    - PriorityQueue: alarms come out first, whatever the backlog.

    Run: PYTHONPATH=src python -m edge.priority_demo
    """

    def __init__(self, items: int = 300, alarm_every: int = 30) -> None:

        # The items is the total number of items the producer puts.
        self.items = items

        # The alarm_every means one item out of alarm_every is an alarm.
        self.alarm_every = alarm_every

    def run(self, use_priority: bool) -> list[int]:
        """
        Run the producer, then read everything.
        Return the positions (0 = handled first) at which the alarms came out.
        """

        queue: BoundedQueue | PriorityQueue
        if use_priority:
            queue = PriorityQueue()
        else:
            queue = BoundedQueue()

        # The all_queued flag is set by the producer once every item is in the queue.
        all_queued = mp.Event()

        producer = mp.Process(target=self.produce, args=(queue, all_queued))
        producer.start()
        all_queued.wait()

        handled: list = []
        while True:
            item = queue.get(timeout=1)
            if item is None or item == STOP:
                break
            handled.append(item)

        # Join only after reading: a process that still has items to push into
        # the pipe cannot exit, so joining first could hang forever.
        producer.join()

        alarm_positions = []
        for position in range(len(handled)):
            kind = handled[position][0]
            if kind == "alarm":
                alarm_positions.append(position)
        return alarm_positions

    def produce(self, queue: BoundedQueue | PriorityQueue, all_queued: Event) -> None:
        """
        Put the logs and the alarms, then STOP, then set the all_queued flag.
        """

        for number in range(1, self.items + 1):
            is_alarm = number % self.alarm_every == 0
            if is_alarm:
                item = ("alarm", number)
            else:
                item = ("log", number)

            if isinstance(queue, PriorityQueue):
                queue.put(item, urgent=is_alarm)
            else:
                queue.put(item)
        queue.put(STOP)
        all_queued.set()


if __name__ == "__main__":
    demo = PriorityDemo()
    print(f"One FIFO queue: alarms handled at positions {demo.run(use_priority=False)}")
    print(f"PriorityQueue:  alarms handled at positions {demo.run(use_priority=True)}")
