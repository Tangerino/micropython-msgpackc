#!/usr/bin/env bash
# Build the MicroPython unix port with msgpackc, in one of the configurations
# used by the tests. Output: build/unix-<flavour>/micropython
#
# Usage: tools/build-unix.sh [flavour]
#   standard  64-bit, double precision floats, arbitrary precision ints (default)
#   float32   single precision floats, like the ESP32 boards
#   longlong  ints limited to 64 bits (MICROPY_LONGINT_IMPL_LONGLONG), a
#             32-bit build: Linux only, needs gcc-i686-linux-gnu and
#             libffi-dev:i386 (as MicroPython's CI)
#   minimal   the minimal variant: no floats, no OrderedDict... (build check,
#             Linux only: it does not build on macOS, in MicroPython itself)
#   sanitize  standard + AddressSanitizer + UndefinedBehaviorSanitizer
#   coverage  the coverage variant, instrumented with gcov
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLAVOUR="${1:-standard}"
UNIX="$ROOT/micropython/ports/unix"

variant=standard
strip=strip
cflags=""
ldflags=""
extra=()
case "$FLAVOUR" in
    standard) ;;
    float32) cflags="-DMICROPY_FLOAT_IMPL=MICROPY_FLOAT_IMPL_FLOAT" ;;
    longlong)
        variant=longlong
        if [[ "$(uname)" != Linux ]] || ! command -v i686-linux-gnu-gcc >/dev/null; then
            echo "longlong is a 32-bit build: it needs Linux and i686-linux-gnu-gcc" >&2
            exit 2
        fi
        extra=(CROSS_COMPILE=i686-linux-gnu-)
        ;;
    minimal) variant=minimal ;;
    sanitize)
        # The flags of MicroPython's own CI (tools/ci.sh), ASan and UBSan in
        # one build. With clang, pointer-overflow is also excluded: it fires
        # on an idiom of the VM core itself (py/vm.c, &sp[-n]), not on msgpackc.
        # Use-after-return detection is off: its fake stack frames break the
        # NLR (non-local return) of MicroPython's exceptions.
        san="-fsanitize=address,undefined -fno-sanitize=nonnull-attribute"
        if cc --version 2>/dev/null | grep -qi clang; then
            san="$san -fsanitize-address-use-after-return=never -fno-sanitize=pointer-overflow"
            san="$san -fsanitize-ignorelist=$ROOT/tools/sanitizer-ignorelist.txt"
        else
            san="$san --param asan-use-after-return=0"
        fi
        # MICROPY_FLOAT_HIGH_QUALITY_HASH: the default float hash casts the
        # value to an int, undefined for huge floats (py/obj.h, upstream).
        cflags="$san -fno-sanitize-recover=undefined -fno-omit-frame-pointer -g -O1 -DMP_ASAN=1 -DMP_UBSAN=1"
        cflags="$cflags -DMICROPY_FLOAT_HIGH_QUALITY_HASH=1"
        ldflags="$san"
        strip="$ROOT/tools/strip-keep-symbols.sh" # micropython.syms: for atos
        ;;
    coverage) variant=coverage ;;
    *) echo "unknown flavour: $FLAVOUR" >&2; exit 2 ;;
esac

manifest="$ROOT/firmware/manifest_unix.py"
[[ $variant == minimal ]] && manifest=""  # the minimal variant freezes nothing

make -C "$ROOT/micropython/mpy-cross" -j8 >/dev/null
[[ -f "$ROOT/micropython/lib/micropython-lib/README.md" ]] || make -C "$UNIX" submodules
make -C "$UNIX" -j8 VARIANT="$variant" BUILD="$ROOT/build/unix-$FLAVOUR" \
    USER_C_MODULES="$ROOT/cmodules" FROZEN_MANIFEST="$manifest" \
    CFLAGS_EXTRA="$cflags" LDFLAGS_EXTRA="$ldflags" PROG=micropython \
    STRIP="$strip" "${extra[@]}"
if [[ $FLAVOUR == longlong ]] && command -v patchelf >/dev/null; then
    # find the i386 libffi at run time, as MicroPython's CI does
    patchelf --add-rpath /usr/i686-linux-gnu/lib "$ROOT/build/unix-longlong/micropython"
fi
echo ">> build/unix-$FLAVOUR/micropython"
