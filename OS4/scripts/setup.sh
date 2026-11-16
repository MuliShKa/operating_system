#!/usr/bin/env bash
set -euo pipefail

# Resolve paths from this file so setup works even when called from another directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# Fail early with an actionable message if the host is missing required tools.
bash "$SCRIPT_DIR/preflight.sh"

PYTHON_BIN=python3
if command -v python3.12 >/dev/null 2>&1; then
	PYTHON_BIN=python3.12
fi

# Keep Python packages isolated from the system interpreter, then install
# the versions declared by the repository.
"$PYTHON_BIN" -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$PROJECT_ROOT/.venv/bin/python" -m pip install --requirement "$PROJECT_ROOT/requirements.txt"

DB_PATH="$PROJECT_ROOT/data/songdo.db"
SCHEMA_PATH="$PROJECT_ROOT/sql/schema.sql"
# Create the data directories before SQLite opens the database file.
mkdir -p "$PROJECT_ROOT/data" "$PROJECT_ROOT/data/backups"

"$PROJECT_ROOT/.venv/bin/python" - "$DB_PATH" "$SCHEMA_PATH" <<'PY'
import sqlite3
import sys
from pathlib import Path

database_path, schema_path = map(Path, sys.argv[1:])
with sqlite3.connect(database_path) as connection:
	# WAL mode lets the dashboard read while the processor writes to SQLite.
	connection.execute("PRAGMA journal_mode=WAL")
	# Apply the checked-in schema so setup and application use the same tables.
	connection.executescript(schema_path.read_text(encoding="utf-8"))
	journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

# Treat a failed WAL configuration as a setup error rather than continuing
# with a database that does not match the expected runtime configuration.
if journal_mode.lower() != "wal":
	raise SystemExit(f"Could not enable SQLite WAL mode (mode: {journal_mode})")

print(f"Database ready: {database_path} (journal mode: {journal_mode})")
PY

printf 'Environment ready: %s/.venv\n' "$PROJECT_ROOT"
