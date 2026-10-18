#!/usr/bin/env bash
# Write ONLY the application (micropython.bin) to a board, leaving its
# bootloader, partition table and data partitions (filesystem, NVS...) as
# they are. Meant for the test firmware on a board that runs another
# application: see docs/HARDWARE_TESTING.md.
#
# Usage: tools/flash-app.sh PORT BUILD_DIR
#   BUILD_DIR  e.g. build/esp32-generic-spiram-test
#
# The partition table is read from the board first: the application must fit
# in its application partition (factory, else ota_0), or nothing is written.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:?usage: $0 PORT BUILD_DIR}"
BUILD="${2:?usage: $0 PORT BUILD_DIR}"
APP="$BUILD/micropython.bin"
[[ -f "$APP" ]] || { echo "no $APP: build it first" >&2; exit 1; }
source "$ROOT/tools/esp-env.sh" >/dev/null

table="$(mktemp)"
trap 'rm -f "$table"' EXIT
# A sparse image with only the partition table, for partitions.py.
esptool.py --port "$PORT" read_flash 0x8000 0xc00 "$table.part" >/dev/null
python3 - "$table.part" "$table" <<'PY'
import sys
data = open(sys.argv[1], "rb").read()
with open(sys.argv[2], "wb") as f:
    f.seek(0x8000)
    f.write(data)
PY
rm -f "$table.part"
read -r offset size < <(python3 "$ROOT/tools/partitions.py" app "$table")
app_size=$(wc -c < "$APP")
printf ">> Board application partition: 0x%x, %d KiB; application: %d KiB\n" \
    "$offset" $((size / 1024)) $((app_size / 1024))
if (( app_size > size )); then
    echo "!! the application does not fit: nothing written" >&2
    exit 1
fi
esptool.py --port "$PORT" -b 460800 write_flash "$offset" "$APP"
