"""Every task the launcher can run: the scenarios and test suites of OS1..OS5.

A task only says WHAT to run. server.py decides WHEN (one at a time, in a queue).
Each command runs inside its team folder, with that team's own virtualenv.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Task:
    id: str                 # unique, e.g. "OS1-3"
    team: str               # "OS1"
    title: str
    concept: str            # OS concept shown on the card
    expected: str           # what PASS means
    official: tuple[str, ...]  # command args after the python executable
    quick: tuple[str, ...] | None = None  # None = same as official
    kind: str = "scenario"  # "scenario" | "extra" | "tests"
    note: str = ""          # short warning shown on the card (long run, kills a process...)

    def args(self, quick: bool) -> tuple[str, ...]:
        return self.quick if quick and self.quick is not None else self.official


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    summary: str
    tasks: list[Task] = field(default_factory=list)

    @property
    def folder(self) -> Path:
        return REPO_ROOT / self.id

    @property
    def python(self) -> Path:
        return self.folder / ".venv" / "bin" / "python"


def _os1(n: str, title: str, concept: str, expected: str, note: str = "") -> Task:
    run = ("scenarios/run_os1_scenarios.py", "--only", f"OS1-{n}")
    return Task(f"OS1-{n}", "OS1", title, concept, expected, run, (*run, "--quick"), note=note)


def _runner(team: str, n: str, title: str, concept: str, expected: str,
            kind: str = "scenario", note: str = "") -> Task:
    run = (f"scenarios/run_{team.lower()}_scenarios.py", "--only", f"{team.lower()}_{n}")
    return Task(f"{team}-{n}", team, title, concept, expected, run, (*run, "--quick"), kind, note)


def _os2(n: str, title: str, concept: str, expected: str, note: str = "") -> Task:
    # OS2 scenarios need a live OS2 node: os2_run.py starts it, runs one scenario, stops it.
    wrapper = str(LAUNCHER_DIR / "os2_run.py")
    return Task(f"OS2-{n}", "OS2", title, concept, expected,
                (wrapper, n, "--offline-seconds", "600"), (wrapper, n, "--offline-seconds", "30"),
                note=note)


def _os5(module: str, title: str, concept: str, expected: str) -> Task:
    return Task(f"OS5-{module.removeprefix('test_').replace('_', '-')}", "OS5", title, concept, expected,
                ("-m", "unittest", "-v", f"tests.{module}"))


def _tests(team: str, count: str) -> Task:
    return Task(f"{team}-tests", team, "Unit test suite", "unittest discover",
                f"All {count} test files pass.", ("-m", "unittest", "discover", "-s", "tests", "-v"),
                kind="tests")


TEAMS: list[Team] = [
    Team("OS1", "Smart Building Edge Gateway",
         "CO₂ and occupancy sensors → local decision → ventilation damper, even without Internet.", [
             _os1("1", "Sensor ingestion & building inventory", "File descriptors · offline-first cache",
                  "Inventory loaded, every reading tagged with its building."),
             _os1("2", "Race condition on the occupancy counter", "Shared memory · mutex · critical section",
                  "No lock: counter < 80. With mutex: exactly 80."),
             _os1("3", "Ventilation rule & command expiry", "Monotonic clock · 15 s TTL",
                  "CO₂ > 1000 ppm → damper 100 %; 16 s late actuator → command rejected."),
             _os1("4", "Process profiling under CPU load", "/proc · RSS · context switches",
                  "Sampled every 2 s; involuntary switches rise under load."),
             _os1("5", "Signature demo: Internet cut", "Durable outbox · store-and-forward",
                  "Backlog drained, 0 lost, 0 duplicates.", note="Official: 10 min offline"),
             _tests("OS1", "7"),
         ]),
    Team("OS2", "Robot Edge Controller",
         "LiDAR / IMU readings → 50 ms control loop → safe emergency stop, with an offline outbox.", [
             _os2("1", "Process topology", "fork · supervisor · PIDs",
                  "Five worker processes alive with distinct PIDs."),
             _os2("2", "Monotonic control loop jitter", "Monotonic clock · periodic scheduling",
                  "50 ms loop measured with bounded jitter."),
             _os2("3", "Obstacle emergency stop", "Command TTL · latched safety state",
                  "Expired command rejected; 0.5 m obstacle latches the stop."),
             _os2("4", "Worker crash & restart", "SIGKILL · supervisor restart",
                  "Controller restarted within 2 s with a new PID.", note="Kills a process on purpose"),
             _os2("5", "Offline conservation", "Durable outbox · idempotent receiver",
                  "Every offline event acknowledged, no loss, no duplicate.", note="Official: 10 min offline"),
             _tests("OS2", "8"),
         ]),
    Team("OS3", "Autonomous Mobility Edge Node",
         "Vehicle speeds and pedestrian counts → variable speed sign at a crosswalk, WAN or not.", [
             _runner("OS3", "1", "Bus stop context & speed telemetry", "Cached public data · ingestion",
                     "Cached Incheon BIS data correlated with crosswalk counts.", note="~45 s"),
             _runner("OS3", "2", "Priority-aware bounded queue", "Priority queue · bounded buffer",
                     "Pedestrian alarms processed before background logs."),
             _runner("OS3", "3", "Overload & drop-oldest", "Bounded queue · back-pressure",
                     "Queue capped at 500, oldest dropped, no crash."),
             _runner("OS3", "4", "Transactional state & version guard", "SQLite WAL · ACID",
                     "No torn read across writer and reader processes."),
             _runner("OS3", "5", "Signature demo: Internet cut", "Outbox · event replay",
                     "Sign keeps working offline; events replayed, none lost.",
                     note="Quick: 60 s · Official: 10 min offline"),
             _tests("OS3", "6"),
         ]),
    Team("OS4", "IoT Edge Gateway",
         "PM2.5, noise and light sensors → mist cannon relay on the Techno-Strip Tower.", [
             _runner("OS4", "1", "Multi-stream sensor ingestion", "Unix sockets · epoll",
                     "Three sensors at different rates aggregated by one process.", note="~30 s"),
             _runner("OS4", "2", "Event time vs receipt time", "Timestamps · out-of-order delivery",
                     "observed_at kept apart from received_at, late readings reordered."),
             _runner("OS4", "3", "Mist cannon relay", "Command TTL · actuator",
                     "PM2.5 > 50 µg/m³ → relay on for 30 s, stale command rejected."),
             _runner("OS4", "4", "Scheduled database backup", "flock · SQLite online backup",
                     "Backups never overlap and are never corrupt."),
             _runner("OS4", "5", "Signature demo: Internet cut", "Outbox · backlog drain",
                     "100 % of events acknowledged after the WAN returns.",
                     note="Quick: 60 s · Official: 10 min offline"),
             _runner("OS4", "6", "Sensor faults (extra)", "Fail-safe actuation",
                     "A broken sensor never starts the mist cannon.", kind="extra"),
             _runner("OS4", "7", "Quiet-night policy (extra)", "Multi-sensor context policy",
                     "At night only a 'Very Bad' reading starts the pump.", kind="extra"),
             _tests("OS4", "5"),
         ]),
    Team("OS5", "Fault-Tolerant Smart-City Node",
         "Water level and voltage → backup sluice gate decision; OS5 checks run as test modules.", [
             _os5("test_os_fundamentals", "OS concurrency fundamentals", "Bounded queue · race · deadlock",
                  "Nothing lost or uncounted; deadlock avoided with lock timeouts."),
             _os5("test_worker_recovery", "Worker crash & recovery", "Supervisor · restart budget",
                  "Only the dead worker restarts, within its restart budget."),
             _os5("test_health", "Liveness & readiness", "Heartbeats · health checks",
                  "Stale heartbeats and stopped workers reported as not ready."),
             _os5("test_storage", "Durable outbox", "SQLite transaction · idempotence",
                  "Event and outbox row atomic, idempotent, marked sent."),
             _os5("test_schema", "Database schema", "SQLite WAL",
                  "Required tables created, WAL mode on."),
             _os5("test_demo_integration", "End-to-end pipeline", "Queues · decision · storage",
                  "Sensor → decision → storage; expired gate command not stored."),
             _os5("test_compound_failure", "WAN outage + processor restart", "Fault tolerance",
                  "Outbox delivery survives a WAN cut and a worker restart."),
             Task("OS5-all", "OS5", "Complete OS5 suite", "run_all_scenarios.py",
                  "Every OS5 test passes.", ("scenarios/run_all_scenarios.py",), kind="tests"),
         ]),
]

TASKS: dict[str, Task] = {task.id: task for team in TEAMS for task in team.tasks}


def team_of(task: Task) -> Team:
    return next(team for team in TEAMS if team.id == task.team)
