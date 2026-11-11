# Errors and surprises

- **`edge.shared_counter` missing** – the first test run failed: `bounded_queue.py`
  imports `SharedCounter`. Fix: copy `shared_counter.py` too.
- **OS5 WAN flag starts offline** – `ipc.py` in OS5 calls `wan_online.clear()` right after
  a comment saying the WAN starts online, so OS5 never syncs until someone presses
  "Restore". Fixed in OS1 (`set()`), with a test.
- **Receiver database shared between runs** – in OS5 it is always
  `data/upstream_receiver.db`, so two runs would mix their counts. OS1 derives it from
  `EDGE_DATABASE_PATH`.
- **Root `.gitignore` gone from main** – it moved to `OS5/`, so `.venv/`, `data/` and
  `project/` show as untracked at the repository root. Do not `git add -A` from the root.
