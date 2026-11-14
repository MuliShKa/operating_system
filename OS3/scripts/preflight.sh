#!/usr/bin/env bash
set -euo pipefail

failures=()

# The project scripts need Linux tools.
if [[ "$(uname -s)" != "Linux" ]]; then
	failures+=("Linux kernel (detected: $(uname -s))")
fi

if [[ -z "${BASH_VERSION:-}" ]]; then
	failures+=("Bash shell")
fi

# Prefer python3.12 (course platform); otherwise use python3.
PYTHON_BIN=python3
if command -v python3.12 >/dev/null 2>&1; then
	PYTHON_BIN=python3.12
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
	failures+=("Python 3.12 or newer (python3)")
elif ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 12) else 1)' >/dev/null 2>&1; then
	failures+=("Python 3.12 or newer ($PYTHON_BIN reports $($PYTHON_BIN --version 2>&1))")
fi

for tool in sqlite3 ps pkill awk sed flock curl; do
	if ! command -v "$tool" >/dev/null 2>&1; then
		failures+=("$tool")
	fi
done

if ((${#failures[@]})); then
	# Show all missing tools before we stop.
	printf 'Preflight failed. Missing or incompatible requirements:\n' >&2
	printf '  - %s\n' "${failures[@]}" >&2
	exit 1
fi

printf 'Preflight passed: Linux, Bash, Python %s, SQLite3, and required tools are available.\n' "$($PYTHON_BIN --version 2>&1 | awk '{print $2}')"
