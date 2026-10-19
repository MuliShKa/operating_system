# Environment and Startup (W1-W3)

This task prepares the Linux development environment and provides the first
one-command launcher for the Songdo edge node.

## Included in this task

- `scripts/preflight.sh` checks for Linux, Bash, Python 3.12, SQLite3, and the
  required command-line tools: `ps`, `pkill`, `awk`, `sed`, `flock`, and `curl`.
- `scripts/setup.sh` creates `.venv` and installs the packages in
  `requirements.txt` (`psutil` and `PyYAML`).
- `scripts/setup.sh` also creates `data/os5.db`, applies `sql/schema.sql`, and
  verifies SQLite WAL mode.
- `scripts/start_demo.sh` runs preflight, sets up the virtual environment if it
  is missing, and starts `src/edge/supervisor.py` in the foreground. The
  dashboard URL is printed before startup.

## Run

From the project root on a Linux machine with Python 3.12:

```bash
bash scripts/preflight.sh
bash scripts/setup.sh
bash scripts/start_demo.sh
```

`start_demo.sh` performs the setup automatically on first run, so the usual
launch command is:

```bash
bash scripts/start_demo.sh
```

Stop the foreground demo with Ctrl+C. Docker, systemd, and the node-name
argument are later-week tasks and are not included here.