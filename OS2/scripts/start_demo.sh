#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${OS2_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment not found. Run scripts/setup.sh first." >&2
  exit 1
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" -m edge.upstream_receiver &
UPSTREAM_PID=$!
"$PYTHON" -m edge.supervisor &
SUPERVISOR_PID=$!

cleanup() {
  for pid in "$SUPERVISOR_PID" "$UPSTREAM_PID"; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  wait "$SUPERVISOR_PID" 2>/dev/null || true
  wait "$UPSTREAM_PID" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "OS2 demo running at http://127.0.0.1:8000"
echo "Use the dashboard WAN control to simulate disconnect and recovery."
wait -n "$SUPERVISOR_PID" "$UPSTREAM_PID"
