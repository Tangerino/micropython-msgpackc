#!/usr/bin/env bash
# Write back a backup made by tools/backup-flash.sh.
#
# Usage: tools/restore-flash.sh PORT BACKUP.bin [--app-only]
#   --app-only  write back only the application partition (factory/ota_0),
#               the only part tools/flash-app.sh changes: much faster
# The result is read back and compared with the backup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:?usage: $0 PORT BACKUP.bin [--app-only]}"
BACKUP="${2:?usage: $0 PORT BACKUP.bin [--app-only]}"
source "$ROOT/tools/esp-env.sh" >/dev/null

if [[ "${3:-}" == "--app-only" ]]; then
    read -r offset size < <(python3 "$ROOT/tools/partitions.py" app "$BACKUP")
    tmp="$(mktemp)"
    dd if="$BACKUP" of="$tmp" bs=4096 skip=$((offset / 4096)) count=$((size / 4096)) 2>/dev/null
    echo ">> Restoring the application partition at $(printf 0x%x "$offset") ($size bytes)"
    esptool.py --port "$PORT" -b 460800 write_flash "$offset" "$tmp"
    rm -f "$tmp"
else
    echo ">> Restoring the whole flash from $BACKUP"
    esptool.py --port "$PORT" -b 460800 write_flash 0 "$BACKUP"
fi
