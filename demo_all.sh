#!/usr/bin/env bash
# Live demo: run the scenarios of OS1..OS5 one team after another, in quick mode.
# Waits for Enter before each team. Usage:
#   bash demo_all.sh            -> OS1 OS2 OS3 OS4 OS5
#   bash demo_all.sh OS1 OS3    -> only these teams
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEAMS=("$@")
[[ ${#TEAMS[@]} -eq 0 ]] && TEAMS=(OS1 OS2 OS3 OS4 OS5)
declare -A RESULT

wait_for_api() { # OS2 scenarios need its node running on port 8000
	for _ in $(seq 60); do
		curl -s -o /dev/null http://127.0.0.1:8000/ && return 0
		sleep 1
	done
	return 1
}

run_team() {
	local team=$1
	cd "$ROOT/$team" || return 1
	export PYTHONPATH="$ROOT/$team/src"
	case $team in
	OS1) .venv/bin/python scenarios/run_os1_scenarios.py --quick ;;
	OS2)
		bash scripts/start_demo.sh >/tmp/os2_demo.log 2>&1 &
		local node=$!
		echo "Starting the OS2 node..."
		if ! wait_for_api; then
			echo "OS2 node did not start (see /tmp/os2_demo.log)"
			kill "$node" 2>/dev/null
			return 1
		fi
		.venv/bin/python scenarios/run_os2_scenarios.py --offline-seconds 30
		local status=$?
		kill -INT "$node" 2>/dev/null
		wait "$node" 2>/dev/null
		return $status
		;;
	OS3) .venv/bin/python scenarios/run_os3_scenarios.py --quick ;;
	OS4) .venv/bin/python scenarios/run_os4_scenarios.py --quick ;;
	OS5) .venv/bin/python scenarios/run_all_scenarios.py ;;
	*) echo "Unknown team: $team"; return 1 ;;
	esac
}

for team in "${TEAMS[@]}"; do
	clear
	printf '\n========== %s ==========\n\nPress Enter to start (Ctrl+C to stop)... ' "$team"
	read -r
	if run_team "$team"; then RESULT[$team]=PASS; else RESULT[$team]=FAIL; fi
	printf '\n%s finished: %s. Press Enter to continue... ' "$team" "${RESULT[$team]}"
	read -r
done

clear
printf '\n===== Summary =====\n'
for team in "${TEAMS[@]}"; do printf '  %-4s %s\n' "$team" "${RESULT[$team]}"; done
