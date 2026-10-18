"""Shared helpers for the host tests: they drive MicroPython unix builds of
msgpackc (build/unix-<flavour>/micropython, made by tools/build-unix.sh)."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FLAVOURS = os.environ.get("MSGPACKC_FLAVOURS", "standard float32").split()


def micropython(flavour):
    path = ROOT / "build" / f"unix-{flavour}" / "micropython"
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not built (tools/build-unix.sh {flavour})")
    return path


def run_mp(flavour, *args, path=(), heap="512M", timeout=1800, cwd=None):
    """Run a script on a unix build; return its stdout (warnings removed)."""
    env = dict(os.environ)
    env["MICROPYPATH"] = ":".join([str(p) for p in path] + [".frozen"])
    proc = subprocess.run(
        [str(micropython(flavour)), "-X", f"heapsize={heap}", *map(str, args)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=cwd,
    )
    out = "\n".join(
        line for line in proc.stdout.splitlines() if not line.startswith("Warning: Comparison")
    )
    assert proc.returncode == 0, f"exit {proc.returncode}\n{out[-3000:]}\n{proc.stderr[-3000:]}"
    return out


# Builds whose ints stop at 64 bits (MICROPY_LONGINT_IMPL_LONGLONG) cannot even
# compile the tests that use larger ints: they run only the rest.
INTBIG_TESTS = {"msgpackc_pack.py", "msgpackc_unpack.py", "msgpackc_errors.py"}
LONGLONG = {"longlong"}


@pytest.fixture(params=FLAVOURS)
def flavour(request):
    return request.param


@pytest.fixture
def bigint_flavour(flavour):
    """A flavour with arbitrary precision ints (needed by the random tests)."""
    if flavour in LONGLONG:
        pytest.skip("needs ints wider than 64 bits")
    return flavour


@pytest.fixture
def quick():
    return os.environ.get("MSGPACKC_QUICK") == "1"
