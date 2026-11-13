#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH="$ROOT/src" .venv/bin/python -c \
  'from edge.config import load_config; from edge.storage import init_db; init_db(load_config().database)'
mkdir -p data/backups
echo "OS2 environment is ready. Run scripts/start_demo.sh to launch the demo."
