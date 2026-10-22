#!/usr/bin/env bash
set -euo pipefail

# Find the project folder from this script location.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# Check system tools before installing packages.
bash "$SCRIPT_DIR/preflight.sh"

# Create Python environment and install the project packages.
PYTHON_BIN=python3
if command -v python3.12 >/dev/null 2>&1; then
	PYTHON_BIN=python3.12
fi
"$PYTHON_BIN" -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$PROJECT_ROOT/.venv/bin/python" -m pip install --requirement "$PROJECT_ROOT/requirements.txt"

DB_PATH="$PROJECT_ROOT/data/songdo.db"
SCHEMA_PATH="$PROJECT_ROOT/sql/schema.sql"
# Keep the database in the data folder.
mkdir -p "$PROJECT_ROOT/data"

"$PROJECT_ROOT/.venv/bin/python" - "$DB_PATH" "$SCHEMA_PATH" <<'PY'
import sqlite3
import sys
from pathlib import Path

database_path, schema_path = map(Path, sys.argv[1:])
with sqlite3.connect(database_path) as connection:
	# WAL lets readers and writers work at the same time.
	connection.execute("PRAGMA journal_mode=WAL")
	# Create the tables from the shared schema file.
	connection.executescript(schema_path.read_text(encoding="utf-8"))
	journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

# Do not finish setup if WAL was not enabled.
if journal_mode.lower() != "wal":
	raise SystemExit(f"Could not enable SQLite WAL mode (mode: {journal_mode})")

print(f"Database ready: {database_path} (journal mode: {journal_mode})")
PY

printf 'Environment ready: %s/.venv\n' "$PROJECT_ROOT"
