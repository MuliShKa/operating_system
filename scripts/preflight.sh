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

# Check Python version and all tools used by the project.
if ! command -v python3.12 >/dev/null 2>&1; then
	failures+=("Python 3.12 (python3.12)")
elif ! python3.12 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' >/dev/null 2>&1; then
	failures+=("Python 3.12 (python3.12 reports another version)")
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

# Setup can start when every check passed.
printf 'Preflight passed: Linux, Bash, Python 3.12, SQLite3, and required tools are available.\n'
