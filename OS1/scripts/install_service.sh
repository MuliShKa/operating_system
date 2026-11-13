#!/usr/bin/env bash
set -euo pipefail

# Install the systemd user units for this node (no root needed).
#   bash scripts/install_service.sh          install the node service and the backup timer
#   bash scripts/install_service.sh --start  also start them now
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TEAM="OS1"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
	bash "$SCRIPT_DIR/setup.sh"
fi

mkdir -p "$UNIT_DIR"
for unit in songdo-edge@.service songdo-backup@.service songdo-backup@.timer; do
	# The unit files use @PROJECT_DIR@ because systemd needs absolute paths.
	sed "s|@PROJECT_DIR@|$PROJECT_ROOT|g" "$PROJECT_ROOT/systemd/$unit" > "$UNIT_DIR/$unit"
	printf 'Installed %s\n' "$UNIT_DIR/$unit"
done

systemctl --user daemon-reload

if [[ "${1:-}" == "--start" ]]; then
	systemctl --user enable --now "songdo-edge@$TEAM.service" "songdo-backup@$TEAM.timer"
	systemctl --user --no-pager status "songdo-edge@$TEAM.service" | head -n 12
else
	printf 'Start with: systemctl --user enable --now songdo-edge@%s.service songdo-backup@%s.timer\n' "$TEAM" "$TEAM"
fi
