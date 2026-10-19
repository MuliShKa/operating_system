#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

bash "$SCRIPT_DIR/preflight.sh"

python3.12 -m venv "$PROJECT_ROOT/.venv"
"$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$PROJECT_ROOT/.venv/bin/python" -m pip install --requirement "$PROJECT_ROOT/requirements.txt"

DB_PATH="$PROJECT_ROOT/data/os5.db"
SCHEMA_PATH="$PROJECT_ROOT/sql/schema.sql"
mkdir -p "$PROJECT_ROOT/data"

"$PROJECT_ROOT/.venv/bin/python" - "$DB_PATH" "$SCHEMA_PATH" <<'PY'
import sqlite3
import sys
from pathlib import Path

database_path, schema_path = map(Path, sys.argv[1:])
with sqlite3.connect(database_path) as connection:
	connection.execute("PRAGMA journal_mode=WAL")
	connection.executescript(schema_path.read_text(encoding="utf-8"))
	journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

if journal_mode.lower() != "wal":
	raise SystemExit(f"Could not enable SQLite WAL mode (mode: {journal_mode})")

print(f"Database ready: {database_path} (journal mode: {journal_mode})")
PY

printf 'Environment ready: %s/.venv\n' "$PROJECT_ROOT"
