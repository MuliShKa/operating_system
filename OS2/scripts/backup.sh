#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${OS2_PYTHON:-$ROOT/.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment not found. Run scripts/setup.sh first." >&2
  exit 1
fi

exec 9>"$ROOT/data/backup.lock"
if ! flock -n 9; then
  echo "Another OS2 backup is already running." >&2
  exit 1
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m edge.maintenance
