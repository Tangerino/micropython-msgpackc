"""The MicroPython-side test programs, run on each unix build:
the run-tests.py suite, the differential test against umsgpack, the fuzzer,
the msgpack-test-suite conformance and umsgpack's own test suite."""

import os
import shutil
import subprocess

from conftest import INTBIG_TESTS, LONGLONG, ROOT, micropython, run_mp

PETER = ROOT / "third_party" / "micropython-msgpack"


def test_run_tests_suite(flavour):
    tests = sorted(
        str(p)
        for p in (ROOT / "tests" / "mp").glob("*.py")
        if flavour not in LONGLONG or p.name not in INTBIG_TESTS
    )
    env = dict(os.environ, MICROPY_MICROPYTHON=str(micropython(flavour)))
    proc = subprocess.run(
        ["python3", "run-tests.py", "--heapsize", "32M", *tests],
        cwd=ROOT / "micropython" / "tests",
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]


def test_differential_vs_umsgpack(bigint_flavour, quick):
    out = run_mp(bigint_flavour, ROOT / "tests/diff/diff_umsgpack.py", *(["quick"] if quick else []),
                 path=[PETER])  # fmt: skip
    assert "RESULT: OK" in out, out[-3000:]


def test_fuzz(bigint_flavour, quick):
    out = run_mp(bigint_flavour, ROOT / "tests/fuzz/fuzz_msgpackc.py",
                 f"iterations={5000 if quick else 100000}", heap="128M")  # fmt: skip
    assert "RESULT: OK" in out, out[-3000:]


def test_conformance(bigint_flavour):
    suite = ROOT / "third_party/msgpack-test-suite/dist/msgpack-test-suite.json"
    out = run_mp(bigint_flavour, ROOT / "tests/conformance/conformance.py", suite)
    assert "RESULT: OK" in out, out


def test_umsgpack_own_suite(bigint_flavour, tmp_path):
    flavour = bigint_flavour
    """Peter Hinch's test_umsgpack.py, through the umsgpack compatibility
    package: the result must be the same as with umsgpack itself."""
    unittest = ROOT / "micropython/lib/micropython-lib/python-stdlib/unittest"
    shim = tmp_path / "shim" / "umsgpack"
    shim.mkdir(parents=True)
    shutil.copy(ROOT / "python/umsgpack/__init__.py", shim)
    for f in (PETER / "umsgpack").glob("mpk_*.py"):
        shutil.copy(f, shim)
    shutil.copy(PETER / "test_umsgpack.py", tmp_path)

    def failed(path):
        env = dict(os.environ, MICROPYPATH=f"{path}:{unittest}:.frozen")
        proc = subprocess.run(
            [str(micropython(flavour)), "-X", "heapsize=64M", "test_umsgpack.py"],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )  # fmt: skip
        return sorted(line for line in proc.stdout.splitlines() if line.startswith("FAIL:"))

    assert failed(tmp_path / "shim") == failed(PETER)
