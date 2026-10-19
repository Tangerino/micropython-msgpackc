#!/usr/bin/env bash
# Print the GitHub release notes of a version: its CHANGELOG.md section and
# the table of ready-made firmware attached to the release.
#
# Usage: tools/release-notes.sh 1.0.0
#        tools/release-notes.sh --mp-version   (prints e.g. v1.29.0)
# Used by .github/workflows/release.yml; the firmware file names must match
# the ones it builds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# From py/mpconfig.h: CI checks the submodule out without its tags.
MP_VERSION="v$(awk '/^#define MICROPY_VERSION_(MAJOR|MINOR|MICRO) / { v = v (v == "" ? "" : ".") $3 } END { print v }' \
    "$ROOT/micropython/py/mpconfig.h")"
if [[ "${1:-}" == --mp-version ]]; then
    echo "$MP_VERSION"
    exit 0
fi
VERSION="${1:?usage: $0 VERSION}"

changes="$(awk -v v="$VERSION" '
    $0 ~ "^## \\[" v "\\]" { on = 1; next }
    on && /^## \[/ { exit }
    on { print }
' "$ROOT/CHANGELOG.md")"
if [[ -z "${changes//[[:space:]]/}" ]]; then
    echo "no section for $VERSION in CHANGELOG.md" >&2
    exit 1
fi

fw() { echo "$1-$MP_VERSION-msgpackc-$VERSION.bin"; }

cat <<EOF
$changes

## Ready-made firmware

MicroPython $MP_VERSION with msgpackc $VERSION built in (and \`msgpackc.ALoader\`
frozen), for the most common Espressif chips. Nothing to compile: download the
file for your chip and write it to the board.

| Your chip | File | Address |
|---|---|---|
| ESP32 (most ESP32 boards: DevKitC, WROOM...) | \`$(fw ESP32_GENERIC)\` | \`0x1000\` |
| ESP32 with PSRAM (WROVER...) | \`$(fw ESP32_GENERIC-SPIRAM)\` | \`0x1000\` |
| ESP32-S3 | \`$(fw ESP32_GENERIC_S3)\` | \`0x0\` |
| ESP32-C3 | \`$(fw ESP32_GENERIC_C3)\` | \`0x0\` |
| ESP32-C6 | \`$(fw ESP32_GENERIC_C6)\` | \`0x0\` |
| ESP32-P4, chip revision 3.0 or later | \`$(fw ESP32_GENERIC_P4)\` | \`0x2000\` |
| ESP32-P4, chip revision 0.x or 1.x (early boards) | \`$(fw ESP32_GENERIC_P4-PRE_REV3)\` | \`0x2000\` |

Write it with [esptool](https://docs.espressif.com/projects/esptool/)
(\`pip install esptool\`). **This erases everything on the board.** Replace
\`PORT\` with your serial port (\`/dev/ttyUSB0\`, \`/dev/cu.usbserial-...\`,
\`COM4\`...), and the address and file with the ones of your chip:

\`\`\`bash
esptool.py --port PORT erase_flash
esptool.py --port PORT --baud 460800 write_flash 0x1000 $(fw ESP32_GENERIC)
\`\`\`

Then, on the board:

\`\`\`python
>>> import msgpackc
>>> msgpackc.__version__
'$VERSION'
>>> msgpackc.loads(msgpackc.dumps({"temp": 21.5, "ok": True}))
{'temp': 21.5, 'ok': True}
\`\`\`

The ESP32 firmware (with and without PSRAM) and the ESP32-P4 (early
revisions) firmware were tested on real boards; the others are built by the
same CI job and pass the build, but were not run on hardware. \`SHA256SUMS\`
lists the checksums of the files. To build for another board, or to add
msgpackc to your own firmware, see
[docs/INSTALL.md](https://github.com/Tangerino/micropython-msgpackc/blob/v$VERSION/docs/INSTALL.md).
EOF
