"""OS1-4: read one process's CPU time, RSS and context switches from /proc."""

import os
from pathlib import Path

PAGE_SIZE_KB = os.sysconf("SC_PAGE_SIZE") // 1024
CLOCK_TICKS_PER_S = os.sysconf("SC_CLK_TCK")

# Positions in /proc/[pid]/stat, counted after the "pid (name)" prefix.
STATE, UTIME, STIME, THREADS, RSS_PAGES = 0, 11, 12, 17, 21


def parse_stat(text: str) -> dict:
    """
    Parse /proc/[pid]/stat. The process name can contain spaces and brackets,
    so the fields start after the LAST closing bracket.
    """
    fields = text[text.rindex(")") + 2:].split()
    return {
        "state": fields[STATE],
        "cpu_s": (int(fields[UTIME]) + int(fields[STIME])) / CLOCK_TICKS_PER_S,
        "threads": int(fields[THREADS]),
        "rss_kb": int(fields[RSS_PAGES]) * PAGE_SIZE_KB,
    }


def parse_context_switches(text: str) -> dict:
    """Parse /proc/[pid]/status: /proc/[pid]/stat does not have these counters."""
    values = dict(
        line.split(":\t", 1) for line in text.splitlines() if ":\t" in line
    )
    return {
        "voluntary_ctxt": int(values["voluntary_ctxt_switches"]),
        "involuntary_ctxt": int(values["nonvoluntary_ctxt_switches"]),
    }


def read_process(pid: int, proc_dir: Path = Path("/proc")) -> dict:
    """Return one sample. Raise OSError if the process has gone."""
    folder = proc_dir / str(pid)
    return {
        "pid": pid,
        **parse_stat((folder / "stat").read_text()),
        **parse_context_switches((folder / "status").read_text()),
    }
