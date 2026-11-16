#!/usr/bin/env bash
set -euo pipefail

# Scheduled online backup of the node database.
# flock -n: if a previous backup still holds the lock, this run stops at once
# instead of running in parallel (no overlapping runs, no lock pile-up).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=python3

DB_PATH="${EDGE_DATABASE_PATH:-$PROJECT_ROOT/data/songdo.db}"
LOCK_FILE="${EDGE_BACKUP_LOCK:-$(dirname -- "$DB_PATH")/backups/.backup.lock}"
mkdir -p "$(dirname -- "$LOCK_FILE")"

# File descriptor 9 holds the lock until this script exits (even on a crash:
# the kernel releases a flock when the process dies).
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
	printf 'Backup skipped: another backup holds %s\n' "$LOCK_FILE"
	exit 0
fi

cd "$PROJECT_ROOT"
EDGE_DATABASE_PATH="$DB_PATH" PYTHONPATH="$PROJECT_ROOT/src" "$PYTHON" -m edge.backup
