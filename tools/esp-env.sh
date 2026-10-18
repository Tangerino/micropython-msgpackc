# Source this file (do not execute it) to use the repo-local ESP-IDF:
#     source tools/esp-env.sh
_here="${BASH_SOURCE[0]:-${(%):-%x}}"
_root="$(cd "$(dirname "$_here")/.." && pwd)"
if [[ ! -f "$_root/tools/esp-idf/export.sh" ]]; then
    if [[ -n "${IDF_PATH:-}" ]] && command -v idf.py >/dev/null; then
        # An ESP-IDF already set up in this shell (e.g. the espressif/idf
        # Docker image used by the CI): use it.
        echo "Using the ESP-IDF at $IDF_PATH"
        unset _here _root
        return 0
    fi
    echo "ESP-IDF is not installed yet. Run: tools/setup-esp-idf.sh" >&2
    return 1
fi
export IDF_TOOLS_PATH="$_root/tools/espressif"
# ESP-IDF brings its own Python environment: hide any active virtualenv.
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vx "$VIRTUAL_ENV/bin" | paste -sd: -)"
    unset VIRTUAL_ENV
fi
. "$_root/tools/esp-idf/export.sh" >/dev/null
unset _here _root
echo "ESP-IDF $(git -C "$IDF_PATH" describe --tags) ready (IDF_TOOLS_PATH=$IDF_TOOLS_PATH)"
