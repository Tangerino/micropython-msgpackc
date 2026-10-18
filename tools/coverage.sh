#!/usr/bin/env bash
# Line and branch coverage of cmodules/msgpackc/modmsgpackc.c: build the
# coverage variant of the unix port, run every test program on it, report.
#
# Usage: tools/coverage.sh        (report in build/unix-coverage/msgpackc/*.gcov)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
B="$ROOT/build/unix-coverage"
"$ROOT/tools/build-unix.sh" coverage >/dev/null
find "$B" -name "*.gcda" -delete

MSGPACKC_FLAVOURS=coverage "$ROOT/.venv/bin/python" -m pytest -q "$ROOT/tests/host/test_suites.py"

cd "$B/msgpackc"
if command -v xcrun >/dev/null; then gcov=(xcrun llvm-cov gcov); else gcov=(gcov); fi
"${gcov[@]}" -b modmsgpackc.gcda | grep -A4 "modmsgpackc.c'"
echo "Not executed (#####): $(grep -c '#####' modmsgpackc.c.gcov) lines; see $B/msgpackc/modmsgpackc.c.gcov"
