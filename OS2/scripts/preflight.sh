#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "OS2 runtime requires Linux or WSL2." >&2
  exit 1
fi

python3 - <<'PY'
import socket
import sqlite3
import sys

if sys.version_info < (3, 12):
    raise SystemExit(f"Python 3.12+ required; found {sys.version.split()[0]}")
if not hasattr(socket, "AF_UNIX"):
    raise SystemExit("Unix domain sockets are unavailable")
if sqlite3.sqlite_version_info < (3, 35, 0):
    raise SystemExit(f"SQLite 3.35+ required; found {sqlite3.sqlite_version}")
print(f"Python {sys.version.split()[0]} / SQLite {sqlite3.sqlite_version}")
PY

for utility in bash flock; do
  command -v "$utility" >/dev/null || {
    echo "Required utility not found: $utility" >&2
    exit 1
  }
done

echo "OS2 preflight passed."
