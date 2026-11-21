#!/usr/bin/env bash
# Open the scenario launcher (OS1..OS5) at http://127.0.0.1:9000
exec python3 "$(dirname -- "${BASH_SOURCE[0]}")/launcher/server.py" "$@"
