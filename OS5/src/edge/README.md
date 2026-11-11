# Edge IPC: how the node's processes talk to each other

> **In one sentence:** the edge node is split into separate Linux processes.
> This folder gives them safe ways to **send data**, **share flags** and
> **ask each other questions**, and proves with demos and tests that they do
> not lose data, corrupt counters or freeze.

Python 3.12 · Linux · standard library only · 19 automated tests

---

## What's in this folder

A small **IPC library**: reusable classes the rest of the node imports, plus
demos and tests that prove each one works.

**Building blocks (used by the node)**

- **`IpcChannels`** (`ipc.py`)
  - groups every channel of the node in one object
  - created once by the supervisor, given to every worker (also after a restart)
  - holds `sensor_events` (queue of 500), `stop` and `wan_online` (flags)
- **`BoundedQueue`** (`bounded_queue.py`)
  - FIFO queue shared between processes, capped at 500
  - when full: drops the **oldest** item, the producer never blocks
  - lock around "drop + add" so two producers never drop two items for one slot
  - `get()` waits without holding the lock → survives a consumer killed by SIGKILL
  - counts what was put and dropped (`stats()`), `STOP` sentinel for a clean exit
- **`PriorityQueue`** (`priority_queue.py`)
  - two `BoundedQueue` lanes: urgent and normal
  - `get()` always serves the urgent lane first
  - `stats()` per lane
- **`SharedCounter`** (`shared_counter.py`)
  - an integer in shared memory, visible to every process
  - `increment()` with a lock (safe), `unsafe_increment()` without (to show the race)
  - used inside `BoundedQueue` for its counters
- **`UnixSocketServer` / `UnixSocketClient`** (`unix_socket.py`)
  - question / answer between processes, one JSON line each way
  - server answers in a background thread
  - creates the missing folder, removes a stale `.sock` file, drops silent clients after 0.5 s
  - a crashing handler returns `{"error": ...}` instead of killing the server

**Demos (prove a scenario, not used by the node)**

- **`RaceDemo`** (`race_demo.py`, OS1-2): 80 processes on one counter → 1 without lock, 80 with lock
- **`DeadlockDemo`** (`deadlock_demo.py`, OS5-3): opposite lock order → stuck; 0.2 s timeout → both finish
- **`PriorityDemo`** (`priority_demo.py`, OS3-2): alarms in a backlog → FIFO vs priority positions

**Tests:** `tests/test_os_fundamentals.py` (see [§11](#11-what-the-tests-prove)).

---

## Contents

1. [The problem](#1-the-problem)
2. [The big picture](#2-the-big-picture) · [the classes](#who-talks-to-whom-the-classes)
3. [BoundedQueue: never run out of memory](#3-boundedqueue-never-run-out-of-memory)
4. [PriorityQueue: alarms first](#4-priorityqueue-alarms-first)
5. [Stopping cleanly: no zombies](#5-stopping-cleanly-no-zombies)
6. [Surviving a SIGKILL](#6-surviving-a-sigkill)
7. [Unix socket: question and answer](#7-unix-socket-question-and-answer)
8. [Race condition: 80 processes, one counter](#8-race-condition-80-processes-one-counter)
9. [Deadlock: two locks, two processes](#9-deadlock-two-locks-two-processes)
10. [Live demo](#10-live-demo)
11. [What the tests prove](#11-what-the-tests-prove)
12. [OS concepts cheat sheet](#12-os-concepts-cheat-sheet)
13. [For teammates: how to use it](#13-for-teammates-how-to-use-it)

---

## 1. The problem

The node runs as **several processes**: SensorGen, Processor, HealthMon, API.
Separate processes are good: if one crashes, the others keep running and the
supervisor restarts it.

But each process has its **own virtual memory**. A Python variable in
SensorGen does not exist in Processor. So we need **IPC** (Inter-Process
Communication): channels that the operating system provides to move data
between processes.

```
 ┌────────────┐                   ┌────────────┐
 │ SensorGen  │   x = 1050 ppm    │ Processor  │
 │ memory A   │ ───── ??? ──────► │ memory B   │   B cannot read A's memory
 └────────────┘                   └────────────┘
```

---

## 2. The big picture

Three tools, each picked for **one job**:

| Need | Tool | Example in the node |
|---|---|---|
| A **stream** of data, one direction | `BoundedQueue` / `PriorityQueue` | SensorGen → Processor |
| A shared **on/off flag** | `multiprocessing.Event` | "stop everything", "internet is down" |
| **Ask** a question, get an **answer** | Unix socket | the web page asks the Processor for its status |

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Supervisor: creates these channels ONCE, gives the same ones to              │
│ every process, restarts crashed workers, stop.set() stops them all           │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       v
┌─────────────┐   put()   ┌──────────────────────────┐   get()   ┌─────────────┐
│  SensorGen  │ ────────> │      sensor_events       │ ────────> │  Processor  │
└─────────────┘           │  BoundedQueue (max 500)  │           └──────┬──────┘
                          └──────────────────────────┘                  │ Unix socket
                                                                        │ question <-> answer
                          ┌──────────────────────────┐           ┌──────┴──────┐
                          │     wan_online flag      │ <──────── │  API / web  │
                          │  cleared = internet cut  │  Cut /    │    page     │
                          └──────────────────────────┘  Restore  └─────────────┘

   every worker loop checks the stop flag:  while not ipc.stop.is_set(): ...
```

**Scenarios covered:** OS1-2 (race), OS3-2 (priority), OS3-3 (overload),
OS5-3 (deadlock), and the queue side of OS2-4 / OS5-2 (worker killed and restarted).

### Who talks to whom: the classes

How the classes fit together. Read it from top to bottom: the rest of the node
only sees the two top boxes, everything below is built inside them.

```text
        Supervisor · SensorGen · Processor · HealthMon · API   (the rest of the node)
                │                                                  │
                │ share ONE object                                 │ ask each other
                v                                                  v
┌──────────────────────────────┐                    ┌──────────────────────────────┐
│ IpcChannels                  │                    │ UnixSocketServer / Client    │
│                       ipc.py │                    │               unix_socket.py │
├──────────────────────────────┤                    ├──────────────────────────────┤
│ sensor_events: BoundedQueue  │                    │ ask(question) -> answer      │
│ stop:          Event         │                    │ JSON over a socket file      │
│ wan_online:    Event         │                    │ 1 question = 1 answer        │
└──────────────────────────────┘                    └──────────────────────────────┘
                │ contains
                v
┌──────────────────────────────┐                    ┌──────────────────────────────┐
│ BoundedQueue                 │                    │ PriorityQueue                │
│             bounded_queue.py │                    │            priority_queue.py │
├──────────────────────────────┤                    ├──────────────────────────────┤
│ put(item)                    │ <── contains 2 ──  │ put(item, urgent)            │
│ get(timeout) -> item | None  │  urgent + normal   │ get(timeout) -> item | None  │
│ max 500, drops the oldest    │                    │ urgent lane always first     │
│ STOP = 'no more items'       │                    └──────────────────────────────┘
└──────────────────────────────┘
                │ contains 2: put_count, dropped_count
                v
┌──────────────────────────────┐
│ SharedCounter                │
│            shared_counter.py │
├──────────────────────────────┤
│ increment()        with lock │
│ unsafe_increment() no lock   │
│ get_value() -> int           │
└──────────────────────────────┘

 Items in the queues: any Python object, e.g. SensorEvent (models.py)

 DEMOS: each one proves a scenario    run: PYTHONPATH=src python -m edge.<file>
 ┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
 │ RaceDemo           OS1-2 │  │ DeadlockDemo       OS5-3 │  │ PriorityDemo       OS3-2 │
 │ 80 processes             │  │ 2 processes, 2 Locks     │  │ 300 items, 10 alarms     │
 │ uses 1 SharedCounter     │  │ uses 2 SharedCounter     │  │ uses PriorityQueue       │
 │ result: 1 vs 80          │  │ result: stuck vs done    │  │ vs one BoundedQueue      │
 └──────────────────────────┘  └──────────────────────────┘  └──────────────────────────┘
```

- **contains** = the class keeps the other one as an attribute
  (`BoundedQueue` has `self.put_count = SharedCounter()`).
- **IpcChannels** is the only object the supervisor creates: one object, given
  to every process, so they all use the **same** queue and flags.
- **Unix socket** is separate: it is for questions ("what is your status?"),
  not for the data stream.
- **The demos** are not used by the node: they exist to prove that the
  building blocks work (and to show it live).

---

## 3. BoundedQueue: never run out of memory

**Problem.** If the Processor is slower than SensorGen, a normal queue grows
forever → memory (RSS) grows → the Linux **OOM killer** kills the process.

**Idea.** Cap the queue at **500 items**. When it is full, throw away the
**oldest** item ("drop oldest"). The producer never blocks, and we always keep
the freshest data: for a flood alarm, the water level *now* matters more than
the level 10 minutes ago.

```text
 Queue full (500 items), SensorGen calls put(e501):

   before   [ e1 | e2 | e3 | ... | e499 | e500 ]          <── put(e501)
               │
               └──> dropped (oldest), dropped_count + 1

   after    [ e2 | e3 | ... | e499 | e500 | e501 ]        still 500 items

   oldest ──────────────────────────────────> newest
   (get() takes from this side)
```

**Proof.**

| Experiment | Result |
|---|---|
| Put 1000 items in a queue of 500 | 500 kept (the **newest**: 500 → 999), 500 dropped |
| 4 producers × 1000 items, 1 consumer | **received + dropped = 4000** → nothing disappears without being counted |

> **Why a lock around `put()`?** Two producers that find the queue full at the
> same time would each drop one item: two lost to make room for one. The lock
> makes "drop + add" happen for one producer at a time.

---

## 4. PriorityQueue: alarms first

**Problem (OS3-2).** A pedestrian surge alarm must not wait behind hundreds of
background logs.

**Idea.** Two lanes, each a `BoundedQueue` of 500: **urgent** and **normal**.
`get()` always empties the urgent lane first.

```
 put(alarm, urgent=True)  ──►  [ urgent lane ]  ─┐
                                                 ├──►  get()  (urgent first)
 put(log)                 ──►  [ normal lane ]  ─┘
```

**Proof.** 300 items are queued, every 30th is an alarm. At which position is
each alarm handled? (0 = first)

| Version | Alarm positions |
|---|---|
| One FIFO queue | `29, 59, 89, … 299` → each alarm waits behind the logs |
| **PriorityQueue** | `0, 1, 2, … 9` → **alarms skip the whole backlog** |

> ⚠️ **The cost: starvation.** While alarms keep coming, logs wait. It is the
> same problem as priority CPU scheduling, with the same known fix (**aging**:
> raise the priority of what waited too long). We accept it: alarms are rare,
> and a late log matters less than a late alarm.

---

## 5. Stopping cleanly: no zombies

**Problem.** A worker that is just killed can lose the items it was about to
handle, and a finished child that nobody waits for becomes a **zombie**
(state `Z` in `ps`).

**Two ways to stop, for two situations:**

| Signal | Meaning | Who uses it |
|---|---|---|
| `ipc.stop.set()` | "everybody stop now" | the supervisor, at shutdown |
| `queue.put(STOP)` | "I have nothing more to send" | a producer, as its last message |

With `STOP`, the consumer handles **every item sent before it**, then leaves
its loop and exits on its own. The parent calls `join()` (a `waitpid()`), so
the child is collected: **no zombie**.

**Proof.** A producer sends 200 items then `STOP` → the consumer counts
**200** and exits with **code 0**.

---

## 6. Surviving a SIGKILL

This is a real bug we found by testing, and fixed.

**Problem.** The supervisor kills a frozen Processor with `SIGKILL`, then
starts a new one (scenarios OS2-4, OS5-2). Python's `mp.Queue.get()` holds an
**internal lock for the whole time it waits**, and an idle Processor is
almost always waiting. `SIGKILL` cannot be caught, so the dying process never
gives the lock back.

```text
 BEFORE the fix: mp.Queue.get() holds the lock the whole time it waits

   1. Processor (old)   get() takes the queue lock, waits for data   lock: held by old
   2. Supervisor        SIGKILL ──> old dies at once, no cleanup     lock: held by a DEAD process
   3. Supervisor        starts Processor (new)
   4. Processor (new)   get() waits for the lock... forever          reads nothing
   5. SensorGen         queue full, put() must drop the oldest,
                        needs the lock too ──> loops forever

 Where a SIGKILL is dangerous:

   old get():  [ take lock ....... wait for data ....... read ][ release ]
                 └──────────── almost all the time ────────────┘

   new get():  wait, no lock ... size > 0? ... [ take lock, read, release ]
                                                 └─── a few µs only ────┘
```

| Before the fix | After the fix |
|---|---|
| new Processor reads **0** of 10 items | reads **10** of 10 |
| producer **stuck** once the queue is full | producer finishes, 100 oldest dropped |

**Fix.** Our `get()` waits **without any lock** (it checks the size every
10 ms) and only takes the lock once an item is there, for a few microseconds.

> **Important.** This shrinks the risk a lot, but does not make it zero: a SIGKILL during
> those few microseconds would still block the queue. The real OS answer is a
> **robust mutex**, which the kernel hands to the next process when its owner
> dies. Python does not offer one.

---

## 7. Unix socket: question and answer

**Idea.** A Unix socket is a **file** (`/tmp/songdo/processor.sock`) that two
local processes connect through. It is two-way: one question, one answer, in
JSON. `ss -xlp | grep songdo` lists them.

```
 API ── {"cmd": "status"} ──►  processor.sock  ──► Processor
 API ◄── {"status": "ok"} ───                  ◄──
```

**Made robust against real failures:**

| Failure | What happens |
|---|---|
| The question makes the handler crash | the server answers `{"error": ...}` and keeps running |
| A crashed run left the `.sock` file behind | it is removed at start |
| The folder `/tmp/songdo/` does not exist | it is created |
| A client connects and sends nothing | it is dropped after 0.5 s, others are not blocked |

---

## 8. Race condition: 80 processes, one counter

**Problem (OS1-2).** `counter = counter + 1` looks like one step, but the CPU
does three: **read → add → write**. If a context switch happens in the middle,
two processes read the same value and one update is lost.

```text
   Process 1                  counter                  Process 2
   ─────────                  ───────                  ─────────
   read: gets 5   <────────      5
                                 5      ────────>   read: gets 5
   write 5+1      ────────>      6
                                 6      <────────   write 5+1

   two increments, but the counter says 6 instead of 7: one update is lost
```

**Fix.** A **mutex** (`multiprocessing.Lock`) turns read-add-write into a
**critical section**: one process at a time.

**Proof.** 80 processes, released at the same instant by a barrier:

| Version | Counter (expected 80) |
|---|---|
| Without lock | **1**: almost every update lost |
| With lock | **80** ✔ |

---

## 9. Deadlock: two locks, two processes

**Problem (OS5-3).** Process 1 takes lock A then wants B. Process 2 takes B
then wants A. Each waits for the other **forever**.

```text
              held by                  wants
   Lock A ─────────────> Process 1 ─────────────> Lock B
     ^                                              │
     │ wants                                held by │
     │                                              v
     └─────────────────── Process 2 <───────────────┘

   P1 holds A and waits for B, P2 holds B and waits for A:
   a cycle, so nobody can ever move
```

A deadlock needs **all four Coffman conditions**. Break one and it cannot happen:

| Condition | Meaning | Broken by |
|---|---|---|
| Mutual exclusion | one owner per lock | (needed, we keep it) |
| **Hold and wait** | keep A while waiting for B | ✅ **our fix**: give A back after 0.2 s |
| No preemption | nobody can take a lock away | – |
| Circular wait | P1 → P2 → P1 | other fix: always take A before B |

**Fix.** Wait **at most 0.2 s** for the second lock. If it fails: release the
first lock, pause a **random** time (so both do not retry in lockstep forever:
a *livelock*), try again.

**Proof.**

| Version | Result |
|---|---|
| Opposite lock order | **deadlocked**, 0 of 2 finished, killed after 1 s (then `join()` → no zombie) |
| 0.2 s timeout | **2 of 2 finished** in about 0.3–0.4 s |

---

## 10. Live demo

From the repository root:

```bash
source .venv/bin/activate

PYTHONPATH=src python -m edge.race_demo
# 80 processes, without lock: counter = 1
# 80 processes, with lock:    counter = 80

PYTHONPATH=src python -m edge.deadlock_demo
# Opposite lock order:        {'deadlocked': True, 'finished_workers': 0, 'retries': 0, 'elapsed_s': 1.004}
# With 0.2 s acquire timeout: {'deadlocked': False, 'finished_workers': 2, 'retries': 1, 'elapsed_s': 0.399}

PYTHONPATH=src python -m edge.priority_demo
# One FIFO queue: alarms handled at positions [29, 59, 89, ..., 299]
# PriorityQueue:  alarms handled at positions [0, 1, 2, ..., 9]

python tests/test_os_fundamentals.py -v
# Ran 19 tests ... OK
```

---

## 11. What the tests prove

| Test group | It proves that… |
|---|---|
| `TestBoundedQueue` | the queue keeps the 500 newest of 1000; with 4 producers, received + dropped = sent |
| `TestConsumerKilled` | after a SIGKILL, a new consumer still reads, and a producer does not hang |
| `TestShutdownSentinel` | a consumer handles all 200 items before `STOP`, then exits with code 0 |
| `TestPriorityQueue` | alarms come out first, each lane stays capped, `STOP` waits for alarms |
| `TestRaceCondition` | without lock < 80, with lock = 80 |
| `TestDeadlock` | the naive version deadlocks, the timeout version always finishes |
| `TestUnixSocket` | answers across processes, survives a bad question, a silent client, a missing folder and an old socket file |
| `TestIpcChannels` | the channels start in the right state (queue of 500, not stopped, WAN online) |

---

## 12. OS concepts cheat sheet

| What we built | OS concept behind it |
|---|---|
| Separate worker processes | process, private **virtual address space**, PID |
| `BoundedQueue` | **producer–consumer** / bounded buffer, pipe, OOM killer |
| `PriorityQueue` | priority scheduling, **starvation**, aging |
| `SharedCounter` | **shared memory** (no kernel call per access) |
| Lock in `SharedCounter` | **critical section**, mutex, mutual exclusion |
| Deadlock demo | **Coffman conditions**, prevention, livelock |
| `STOP` + `join()` | clean termination, **zombie** process, `waitpid()` |
| SIGKILL fix | **signals** (SIGTERM can be caught, SIGKILL cannot), robust mutex |
| Unix socket | socket file, **file descriptors**, client–server |

---

## 13. For teammates: how to use it

**Supervisor.** Create the channels **once, before** starting the workers, and
give the same object to every worker, also to a restarted one. A queue created
inside a worker would be shared with nobody.

```python
from edge.ipc import IpcChannels

ipc = IpcChannels()
mp.Process(target=run_sensor, args=(ipc,)).start()
mp.Process(target=run_processor, args=(ipc,)).start()
...
ipc.stop.set()                         # ask every worker to stop
```

**Producer (SensorGen).**

```python
def run_sensor(ipc):
    while not ipc.stop.is_set():
        ipc.sensor_events.put(read_sensor())
        time.sleep(1)
```

**Consumer (Processor).** `get()` returns `None` after the timeout, so the
loop can still check `stop`.

```python
from edge.bounded_queue import STOP

def run_processor(ipc):
    while not ipc.stop.is_set():
        event = ipc.sensor_events.get(timeout=0.2)
        if event == STOP:
            break
        if event is not None:
            handle(event)
```

**Priority queue.**

```python
from edge.priority_queue import PriorityQueue

events = PriorityQueue()
events.put(log_line)                   # normal lane
events.put(surge_alarm, urgent=True)   # urgent lane
events.get(timeout=0.2)                # the alarm comes out first
```

**Web page and sender.**

```python
ipc.wan_online.clear()                 # "Simulate WAN Internet Cut"
ipc.wan_online.set()                   # "Restore WAN Connection"
ipc.wan_online.is_set()                # sender: may we send now?
ipc.sensor_events.stats()              # {"size", "maxsize", "put_count", "dropped_count"}
```

**Unix socket.** Keep socket paths under 108 characters.

```python
from edge.unix_socket import UnixSocketClient, UnixSocketServer

def answer(question):                  # question and answer are dicts
    return {"status": "ok"}

server = UnixSocketServer("/tmp/songdo/processor.sock", answer)
server.start()                         # answers in a background thread
UnixSocketClient("/tmp/songdo/processor.sock").ask({"cmd": "status"})   # {"status": "ok"}
server.stop()
```

### Files

| File | Class | Role |
|---|---|---|
| `ipc.py` | `IpcChannels` | every channel in one object, created by the supervisor |
| `bounded_queue.py` | `BoundedQueue`, `STOP` | queue capped at 500, drop oldest, shutdown sentinel |
| `priority_queue.py` | `PriorityQueue` | urgent lane + normal lane |
| `shared_counter.py` | `SharedCounter` | integer in shared memory, safe and unsafe increment |
| `unix_socket.py` | `UnixSocketServer`, `UnixSocketClient` | JSON question/answer over a Unix socket |
| `race_demo.py` | `RaceDemo` | 80 processes, one counter, with and without lock |
| `deadlock_demo.py` | `DeadlockDemo` | opposite lock order, then the timeout fix |
| `priority_demo.py` | `PriorityDemo` | alarms in a backlog: FIFO vs priority |
