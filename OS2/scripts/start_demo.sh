#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${OS2_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment not found. Run scripts/setup.sh first." >&2
  exit 1
fi

for utility in setsid; do
  if ! command -v "$utility" >/dev/null; then
    echo "Required utility not found: $utility" >&2
    exit 1
  fi
done

group_has_live_processes() {
  local stat_file
  local stat_line
  local fields
  local state
  local parent
  local process_group

  for stat_file in /proc/[0-9]*/stat; do
    [[ -r "$stat_file" ]] || continue
    IFS= read -r stat_line < "$stat_file" || continue
    fields="${stat_line##*) }"
    read -r state parent process_group _ <<< "$fields"
    if [[ "$process_group" == "$1" && "$state" != Z && "$state" != X ]]; then
      return 0
    fi
  done
  return 1
}

print_process_group() {
  local stat_file
  local stat_line
  local fields
  local state
  local parent
  local process_group
  local pid
  local command

  for stat_file in /proc/[0-9]*/stat; do
    [[ -r "$stat_file" ]] || continue
    IFS= read -r stat_line < "$stat_file" || continue
    fields="${stat_line##*) }"
    read -r state parent process_group _ <<< "$fields"
    if [[ "$process_group" == "$1" ]]; then
      pid="${stat_file#/proc/}"
      pid="${pid%/stat}"
      command=""
      IFS= read -r command < "/proc/$pid/comm" || true
      printf '  pid=%s ppid=%s state=%s command=%s\n' \
        "$pid" "$parent" "$state" "$command" >&2
    fi
  done
}

wait_for_group_exit() {
  local process_group="$1"
  local timeout_s="$2"
  local started_at=$SECONDS

  while group_has_live_processes "$process_group"; do
    if (( SECONDS - started_at >= timeout_s )); then
      return 1
    fi
    sleep 0.1
  done
}

stop_process_group() {
  local pid="$1"
  local name="$2"

  kill -TERM "$pid" 2>/dev/null || true
  if ! wait_for_group_exit "$pid" 10; then
    echo "$name did not stop after SIGTERM; terminating its process group." >&2
    kill -TERM -- "-$pid" 2>/dev/null || true
    if ! wait_for_group_exit "$pid" 2; then
      echo "$name process group did not exit; killing it." >&2
      print_process_group "$pid"
      kill -KILL -- "-$pid" 2>/dev/null || true
    fi
  fi
  wait "$pid" 2>/dev/null || true
}

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
setsid "$PYTHON" -m edge.upstream_receiver &
UPSTREAM_PID=$!
setsid "$PYTHON" -m edge.supervisor &
SUPERVISOR_PID=$!

cleanup() {
  trap - EXIT INT TERM
  stop_process_group "$SUPERVISOR_PID" "OS2 supervisor"
  stop_process_group "$UPSTREAM_PID" "OS2 upstream receiver"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "OS2 demo running at http://127.0.0.1:8000"
echo "Use the dashboard WAN control to simulate disconnect and recovery."
wait -n "$SUPERVISOR_PID" "$UPSTREAM_PID"
