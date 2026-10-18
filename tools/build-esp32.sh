#!/usr/bin/env bash
# Build MicroPython (the micropython/ submodule) with msgpackc for an ESP32
# family board, using the repo-local ESP-IDF (tools/setup-esp-idf.sh).
#
# Usage: tools/build-esp32.sh BOARD [VARIANT] [--test] [--without-msgpackc]
#   BOARD     a board of micropython/ports/esp32/boards, e.g. ESP32_GENERIC,
#             ESP32_GENERIC_S3, ESP32_GENERIC_C3, ESP32_GENERIC_P4
#   VARIANT   optional board variant, e.g. SPIRAM (ESP32_GENERIC) or
#             PRE_REV3 (ESP32_GENERIC_P4 with a chip older than revision 3)
#   --test    test/benchmark firmware (firmware/manifest_test.py): RAM
#             filesystem, flash data partitions never touched
#   --without-msgpackc   same firmware without the module (size comparison)
#
# Output: build/esp32-<board>[-<variant>][-test][-nomsgpackc]/firmware.bin
# (full image for address 0) and micropython.bin (application only).
#
# The esp32 port's Makefile is not used because its BUILD variable leaks into
# the nested mpy-cross build; this script runs the same idf.py command.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOARD="${1:?usage: $0 BOARD [VARIANT] [--test] [--without-msgpackc]}"
shift
VARIANT=""
TEST=0
WITH_MODULE=1
for arg in "$@"; do
    case "$arg" in
        --test) TEST=1 ;;
        --without-msgpackc) WITH_MODULE=0 ;;
        -*) echo "unknown option: $arg" >&2; exit 2 ;;
        *) VARIANT="$arg" ;;
    esac
done

PORT_DIR="$ROOT/micropython/ports/esp32"
if [[ ! -d "$PORT_DIR/boards/$BOARD" ]]; then
    echo "unknown board: $BOARD (see micropython/ports/esp32/boards)" >&2
    exit 2
fi

name="$(echo "$BOARD" | tr 'A-Z_' 'a-z-')"
[[ -n "$VARIANT" ]] && name="$name-$(echo "$VARIANT" | tr 'A-Z_' 'a-z-')"
[[ $TEST == 1 ]] && name="$name-test"
[[ $WITH_MODULE == 0 ]] && name="$name-nomsgpackc"
OUT="$ROOT/build/$name"

manifest="$ROOT/firmware/manifest.py"
[[ $TEST == 1 ]] && manifest="$ROOT/firmware/manifest_test.py"

# shellcheck source=esp-env.sh
source "$ROOT/tools/esp-env.sh"

make -C "$ROOT/micropython/mpy-cross" -j8 >/dev/null
if [[ ! -f "$ROOT/micropython/lib/berkeley-db-1.xx/README" ]]; then
    make -C "$PORT_DIR" BOARD="$BOARD" submodules
fi

flags=(-D MICROPY_BOARD="$BOARD" -D MICROPY_BOARD_DIR="$PORT_DIR/boards/$BOARD"
       -D MICROPY_FROZEN_MANIFEST="$manifest")
[[ -n "$VARIANT" ]] && flags+=(-D MICROPY_BOARD_VARIANT="$VARIANT")
if [[ $WITH_MODULE == 1 ]]; then
    flags+=(-D USER_C_MODULES="$ROOT/cmodules/micropython.cmake")
else
    flags+=(-D USER_C_MODULES=)
fi

echo ">> Building $BOARD${VARIANT:+ ($VARIANT)} into build/$name"
cd "$PORT_DIR"
idf.py "${flags[@]}" -B "$OUT" build
python3 makeimg.py "$OUT/sdkconfig" "$OUT/bootloader/bootloader.bin" \
    "$OUT/partition_table/partition-table.bin" "$OUT/micropython.bin" \
    "$OUT/firmware.bin" "$OUT/micropython.uf2"
echo ">> Done: build/$name/firmware.bin ($(wc -c < "$OUT/firmware.bin") bytes)"
