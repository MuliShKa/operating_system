#!/usr/bin/env bash
cd "$(dirname "$0")"
EDGE_DATABASE_PATH=/tmp/songdo_dashboard_test.db PYTHONPATH=src exec .venv/bin/python -m edge.supervisor
