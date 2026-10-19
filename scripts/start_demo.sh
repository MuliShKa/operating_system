#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

bash "$SCRIPT_DIR/preflight.sh"

if [[ ! -x "$VENV_PYTHON" ]]; then
	bash "$SCRIPT_DIR/setup.sh"
fi

if [[ ! -f "$PROJECT_ROOT/src/edge/supervisor.py" ]]; then
	printf 'Supervisor entry point is missing: %s/src/edge/supervisor.py\n' "$PROJECT_ROOT" >&2
	exit 1
fi

printf 'Opening the dashboard at http://127.0.0.1:8000\n'
cd "$PROJECT_ROOT"
exec "$VENV_PYTHON" "$PROJECT_ROOT/src/edge/supervisor.py"
