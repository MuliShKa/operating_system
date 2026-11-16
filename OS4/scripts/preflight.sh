#!/usr/bin/env bash
set -euo pipefail

# Audit the host before anything is installed or started (handbook: preflight.sh).
# Every missing requirement is listed, not just the first one.
failures=()
warnings=()

if [[ "$(uname -s)" != "Linux" ]]; then
	failures+=("Linux kernel (detected: $(uname -s)): epoll, Unix sockets, flock and /proc are used")
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
else
	# The OS4 node needs: Unix datagram sockets, epoll selectors, SQLite online backup (3.35+ is plenty).
	if ! "$PYTHON_BIN" - >/dev/null 2>&1 <<'PY'
import selectors, socket, sqlite3, sys
assert hasattr(socket, "AF_UNIX") and hasattr(selectors, "EpollSelector")
assert sqlite3.sqlite_version_info >= (3, 35, 0)
PY
	then
		failures+=("Python with AF_UNIX sockets, epoll and SQLite >= 3.35")
	fi
fi

# Required tools. flock = overlap-free backups; ps/pkill = process inspection ladder.
for tool in ps pkill awk sed flock curl; do
	if ! command -v "$tool" >/dev/null 2>&1; then
		failures+=("$tool")
	fi
done

# Nice to have: only used by hand in the command ladder (the code uses Python's sqlite3 module).
for tool in sqlite3 ss pidstat vmstat; do
	command -v "$tool" >/dev/null 2>&1 || warnings+=("$tool (optional, used by the inspection commands)")
done

if ((${#failures[@]})); then
	printf 'Preflight failed. Missing or incompatible requirements:\n' >&2
	printf '  - %s\n' "${failures[@]}" >&2
	exit 1
fi

printf 'Preflight passed: Linux, Bash, Python %s, sockets/epoll/SQLite, and required tools are available.\n' "$($PYTHON_BIN --version 2>&1 | awk '{print $2}')"
if ((${#warnings[@]})); then
	printf 'Note, optional and missing: %s\n' "${warnings[*]}"
fi
