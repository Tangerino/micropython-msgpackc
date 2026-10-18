#!/usr/bin/env bash
# Install a private copy of ESP-IDF and the Espressif toolchains INSIDE this
# repository (tools/esp-idf and tools/espressif). Nothing is written to
# ~/.espressif and nothing here is committed to git (see .gitignore).
#
# Usage:
#   tools/setup-esp-idf.sh                 # default chips: esp32,esp32s3,esp32c3,esp32c6,esp32p4
#   IDF_CHIPS=esp32 tools/setup-esp-idf.sh # only what you need (smaller download)
#
# Optional speed-ups if you already have ESP-IDF somewhere else:
#   IDF_REFERENCE=~/esp-idf-5.5.2   borrow git objects from an existing full clone
#   IDF_DIST_CACHE=~/.espressif/dist  reuse already-downloaded toolchain archives
set -euo pipefail

IDF_VERSION="${IDF_VERSION:-v5.5.2}" # recommended by MicroPython v1.29 (ports/esp32/README.md)
IDF_CHIPS="${IDF_CHIPS:-esp32,esp32s3,esp32c3,esp32c6,esp32p4}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IDF_DIR="$ROOT/tools/esp-idf"
export IDF_TOOLS_PATH="$ROOT/tools/espressif"

if [[ ! -d "$IDF_DIR/.git" ]]; then
    echo ">> Cloning ESP-IDF $IDF_VERSION into tools/esp-idf"
    # Shallow clone (as suggested by Espressif): ~1 GB instead of ~4 GB of history.
    ref=(--depth 1 --shallow-submodules)
    if [[ -n "${IDF_REFERENCE:-}" && -d "${IDF_REFERENCE}/.git" ]] \
        && [[ "$(git -C "$IDF_REFERENCE" rev-parse --is-shallow-repository)" == false ]]; then
        ref=(--reference "$IDF_REFERENCE" --dissociate)
    fi
    git clone -q -b "$IDF_VERSION" "${ref[@]}" https://github.com/espressif/esp-idf.git "$IDF_DIR"
else
    echo ">> tools/esp-idf already present: $(git -C "$IDF_DIR" describe --tags)"
fi
git -C "$IDF_DIR" submodule update --init --recursive --depth 1 --jobs 8 -q

if [[ -n "${IDF_DIST_CACHE:-}" && -d "${IDF_DIST_CACHE}" ]]; then
    echo ">> Seeding the download cache from $IDF_DIST_CACHE"
    mkdir -p "$IDF_TOOLS_PATH/dist"
    cp -n "$IDF_DIST_CACHE"/* "$IDF_TOOLS_PATH/dist/" 2>/dev/null || true
fi

# install.sh refuses to run from inside a Python virtualenv, so drop any venv
# (a directory with a pyvenv.cfg next to its bin/) from PATH for this script.
clean_path=""
IFS=: read -ra parts <<< "$PATH"
for d in "${parts[@]}"; do
    [[ -f "$d/../pyvenv.cfg" ]] && continue
    clean_path="${clean_path:+$clean_path:}$d"
done
export PATH="$clean_path"
unset VIRTUAL_ENV

echo ">> Installing toolchains for: $IDF_CHIPS (into tools/espressif)"
"$IDF_DIR/install.sh" "$IDF_CHIPS"

echo
echo ">> Done. Activate the environment in a new shell with:"
echo "     source tools/esp-env.sh"
