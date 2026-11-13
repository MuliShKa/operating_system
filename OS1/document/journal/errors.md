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
- **Port 8001 already taken** (2026-11-13) – another program on the machine listens on
  8001 and answers 404, so the receiver could not start. Fix: `EDGE_API_PORT` and
  `EDGE_RECEIVER_PORT` move the node; the official runs used receiver port 8011.
- **Root `.venv` gone** – the team removed it. `bash OS1/scripts/setup.sh` now creates
  `OS1/.venv` (ignored by git).
- **Wrong `.gitignore` patterns** – `./OS1/project` and `./project` ignore nothing: git does
  not understand a leading `./`, and paths are relative to the `.gitignore` folder. The
  working pattern is `/project/`.
- **No `kill` in the slim image** – `docker exec … kill -9` failed (`executable file not
  found`). Used `python -c "os.kill(pid, SIGKILL)"` instead.
- **Clicked the dashboard in Estève's Chrome** – not wanted. Dashboard checks are done with
  `curl` on `/api/status` from now on.
- **OS1-2 result too perfect** – a fixed 5 ms pause gave 1/80 on every trial. Switched to
  a random 0–5 ms pause (see 08).
- **VWorld layer name unknown** – two web searches did not confirm the building layer ID,
  so it is left empty in `config/node.yaml` and the node uses a labelled fixture.
