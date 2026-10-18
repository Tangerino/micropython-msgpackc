#!/usr/bin/env bash
# Run the unix jobs of the CI (.github/workflows/ci.yml) locally, in an
# Ubuntu 24.04 x86-64 container: a check on Linux from macOS or Windows.
#
# Usage: tools/docker-ci.sh [flavour...]   (default: standard longlong minimal sanitize)
# Needs Docker. On an ARM computer the x86-64 container is emulated: slow, and
# the sanitizers do not work under emulation. Run the sanitizer build in a
# native container instead: DOCKER_PLATFORM=linux/arm64 tools/docker-ci.sh sanitize
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLAVOURS="${*:-standard longlong minimal sanitize}"

PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
docker run --rm --platform "$PLATFORM" -v "$ROOT:/src:ro" -e FLAVOURS="$FLAVOURS" ubuntu:24.04 bash -c '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if [[ "$(uname -m)" == x86_64 ]]; then
    dpkg --add-architecture i386
    i386="gcc-i686-linux-gnu patchelf libffi-dev:i386"
fi
apt-get update -qq
apt-get install -y -qq git make gcc python3 python3-venv pkg-config libffi-dev rsync \
    curl ca-certificates ${i386:-} >/dev/null
curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
export PATH="$HOME/.local/bin:$PATH"
# A copy without the host build output, ESP-IDF and virtualenv.
rsync -a --exclude build --exclude .venv --exclude tools/esp-idf --exclude tools/espressif \
    --exclude .private /src/ /work/
cd /work
git config --global --add safe.directory "*"
make setup >/dev/null
rc=0
for f in $FLAVOURS; do
    echo "=== $f"
    tools/build-unix.sh "$f" >/tmp/build-$f.log 2>&1 || { tail -30 /tmp/build-$f.log; rc=1; continue; }
    if [[ $f == minimal ]]; then
        build/unix-minimal/micropython -c "import msgpackc; print(msgpackc.loads(msgpackc.dumps([1, \"a\", b\"b\", None])))" || rc=1
        continue
    fi
    ASAN_OPTIONS=detect_leaks=0:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
    MSGPACKC_FLAVOURS=$f MSGPACKC_QUICK=1 .venv/bin/python -m pytest -q --tb=short || rc=1
done
exit $rc
'
