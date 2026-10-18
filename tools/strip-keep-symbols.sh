#!/usr/bin/env bash
# Used as STRIP for the sanitizer build: keep a copy of the binary with its
# symbols (<binary>.syms), then strip it as usual. On macOS the AddressSanitizer
# runtime refuses to start ("Interceptors are not working") when the binary
# keeps its symbol table; stripping does not move code, so the .syms copy
# translates the addresses of a report: atos -o micropython.syms <address>
set -euo pipefail
binary="${*: -1}"
cp "$binary" "$binary.syms"
exec strip "$@"
