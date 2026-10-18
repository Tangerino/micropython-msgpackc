#!/usr/bin/env bash
# Save the whole flash of a board, before trying a firmware on it.
#
# Usage: tools/backup-flash.sh PORT [OUTPUT.bin]
# The file (default: .private/flash-backups/<chip>_<mac>_<size>.bin, not in
# git) restores the board byte for byte: tools/restore-flash.sh PORT FILE.
# Reading 16 MiB over a USB-Serial/JTAG port can take about 25 minutes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:?usage: $0 PORT [OUTPUT.bin]}"
source "$ROOT/tools/esp-env.sh" >/dev/null

info="$(esptool.py --port "$PORT" flash_id)"
chip="$(sed -n 's/^Chip is \([^ ]*\).*/\1/p' <<< "$info" | tr 'A-Z' 'a-z')"
mac="$(sed -n 's/^MAC: //p' <<< "$info" | tr -d ':')"
size="$(sed -n 's/^Detected flash size: //p' <<< "$info")"
case "$size" in
    *MB) bytes=$(( ${size%MB} * 1024 * 1024 )) ;;
    *) echo "cannot read the flash size: $size" >&2; exit 1 ;;
esac
out="${2:-$ROOT/.private/flash-backups/${chip}_${mac}_${size}.bin}"
mkdir -p "$(dirname "$out")"

echo ">> Reading $size of flash from $chip ($mac) into $out"
esptool.py --port "$PORT" -b 460800 read_flash 0 "$bytes" "$out"
shasum -a 256 "$out" | tee "$out.sha256"
