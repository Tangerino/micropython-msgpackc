# How msgpackc is tested

A serializer is trusted with every message an application sends and
receives, and on a microcontroller a bug in C does not raise an exception: it
reboots the board, or worse. So `msgpackc` is tested from several independent
angles, each able to catch what the others miss.

- [Summary](#summary)
- [Running the tests](#running-the-tests)
- [1. The run-tests.py suite](#1-the-run-testspy-suite)
- [2. Differential test against umsgpack](#2-differential-test-against-umsgpack)
- [3. umsgpack's own test suite](#3-umsgpacks-own-test-suite)
- [4. Conformance: msgpack-test-suite](#4-conformance-msgpack-test-suite)
- [5. Interoperability with msgpack-python](#5-interoperability-with-msgpack-python)
- [6. Fuzzing under sanitizers](#6-fuzzing-under-sanitizers)
- [7. Coverage](#7-coverage)
- [8. Memory](#8-memory)
- [9. Real hardware](#9-real-hardware)
- [Build configurations](#build-configurations)
- [Benchmarks](#benchmarks)
- [Problems found along the way](#problems-found-along-the-way)

## Summary

Results of version 1.0.0 (2026-10-18), all passing:

| test | unix port | ESP32 | ESP32-P4 |
|---|---|---|---|
| [run-tests.py suite](#1-the-run-testspy-suite) (13 files, ~290 cases) | standard, float32, sanitize, coverage, longlong (10 files), minimal (build) | 12/12 with and without PSRAM (`large` skipped: heap) | 13/13 |
| [differential vs umsgpack](#2-differential-test-against-umsgpack) | ~178,000 checks per run, on every build; 2.3 million during development | 3 seeds | 3 seeds |
| [umsgpack's own suite](#3-umsgpacks-own-test-suite) | same results as umsgpack | | |
| [msgpack-test-suite](#4-conformance-msgpack-test-suite) | 318/318, double and single floats | 318/318 | 318/318 |
| [interoperability with msgpack-python](#5-interoperability-with-msgpack-python) | 6,000 objects both ways per build, identical encodings | | |
| [fuzzing](#6-fuzzing-under-sanitizers) | ASan + UBSan (clang, and gcc on Linux): 100,000 iterations per run, 1 million during development | 5,000 iterations | 5,000 iterations |
| [coverage](#7-coverage) | 99.1% of lines, 100% of branches executed, 95.9% taken both ways | | |
| [memory](#8-memory) | no leak; bounded allocation | no leak | no leak |

Linux was checked in Ubuntu 24.04 containers (`tools/docker-ci.sh`): x86-64
standard, 32-bit `longlong` and `minimal`, and on ARM64 the gcc sanitizer
build.

## Running the tests

| command | what | time |
|---|---|---|
| `make test-quick` | everything below on the unix port, smaller | ~2 min |
| `make test` | everything below on the unix port (standard and float32 builds) | ~15 min |
| `make test-sanitize` | the same on an ASan + UBSan build | ~8 min |
| `make coverage` | the suites on the coverage build, then the coverage report | ~2 min |
| `make test-device PORT=...` | suite, differential, conformance and fuzzer on a board | ~15 min |
| `tools/docker-ci.sh` | the unix jobs of the CI, in an Ubuntu container | slow |

The host tests are driven by `pytest` (`tests/host/`); each one runs a
MicroPython program on a unix build of the module. Select the builds with
`MSGPACKC_FLAVOURS="standard float32"` and the short versions with
`MSGPACKC_QUICK=1`.

## 1. The run-tests.py suite

`tests/mp/` holds the test programs in MicroPython's own format: a script and
its expected output (`.exp`), run by MicroPython's test runner
`micropython/tests/run-tests.py`, unchanged, on the unix port and on the
boards. The tests are self-checking: the expected bytes come from the
[MessagePack specification](https://github.com/msgpack/msgpack/blob/master/spec.md)
and are written in the test, so the `.exp` files mostly say `ok`.

| file | covers |
|---|---|
| `msgpackc_pack.py` | every format family at every size boundary |
| `msgpackc_unpack.py` | every format, including non-minimal encodings, options, input types |
| `msgpackc_errors.py` | the exception hierarchy, every error and its message |
| `msgpackc_ext.py` | extension types: every header size, user classes, built-ins, registry, errors |
| `msgpackc_stream.py` | `dump`/`load` on native streams and Python file-like objects, short reads |
| `msgpackc_unpacker.py` | `Unpacker` with every chunk size, `next_raw`, resynchronisation, limits |
| `msgpackc_aloader.py` | `ALoader` with asyncio, observer, end of stream |
| `msgpackc_subclass.py` | subclasses of the native types, `namedtuple`, `OrderedDict` |
| `msgpackc_safety.py` | hostile input: nesting, cycles, huge lengths, every truncation, data changed by callbacks |
| `msgpackc_memory.py` | no leak; heap allocated per call |
| `msgpackc_edge.py` | error paths found with the coverage build |
| `msgpackc_large.py` | the 32-bit length formats (skipped on small heaps) |

## 2. Differential test against umsgpack

`tests/diff/diff_umsgpack.py` runs msgpackc and umsgpack side by side on the
same inputs and compares everything: the bytes produced by `dumps` and
`dump`, the objects returned by `loads` and `load`, and for errors the
exception type **and** message. Inputs:

- random objects of every supported and unsupported type, nested, with
  sizes around every format boundary, subclasses, extension types;
- random bytes, valid messages, and valid messages mutated (bytes changed,
  inserted, truncated, bits flipped);
- every load option and float precision.

The generator is seeded, so a failure can be replayed. A full run is about
178,000 checks; it runs with several seeds on each build and, shorter, on
each board.

The only differences found are deliberate, and listed in
[USAGE.md](USAGE.md#10-differences-from-umsgpack). The most important: where
umsgpack raises `MemoryError` or `OverflowError` on a corrupt length (it
allocates the length before reading), msgpackc raises
`InsufficientDataException`. Those cases are counted by the test ("MemoryError
avoided"): around 1,500 per full run.

## 3. umsgpack's own test suite

Peter Hinch's `test_umsgpack.py` (from u-msgpack-python, 132 test
vectors in 14 tests) runs on msgpackc through the `umsgpack` compatibility package, with
umsgpack's own `mpk_*.py` extension modules. On MicroPython, umsgpack itself
fails 2 of its 14 tests (they compare an `OrderedDict` with a `dict`, which
MicroPython does not consider equal); msgpackc passes and fails exactly the
same tests (`tests/host/test_suites.py::test_umsgpack_own_suite`).

## 4. Conformance: msgpack-test-suite

[msgpack-test-suite](https://github.com/kawanet/msgpack-test-suite) is the
set of cross-language test vectors of MessagePack: for each value, the list
of its valid encodings. `tests/conformance/conformance.py` checks that every
valid encoding unpacks to the value and that packing the value gives one of
them: **318 of 318 checks pass**, with double and single precision floats, on
the unix port, the ESP32 and the ESP32-P4.

## 5. Interoperability with msgpack-python

[msgpack-python](https://github.com/msgpack/msgpack-python) is the reference
implementation for CPython. `tests/host/test_interop.py`:

- packs thousands of random objects with msgpack-python, unpacks and packs
  them again with msgpackc, and unpacks the result with msgpack-python: the
  objects must survive both directions;
- checks that, for the same value, msgpackc and msgpack-python choose the
  same encoding, byte for byte, at every size boundary.

## 6. Fuzzing under sanitizers

`tests/fuzz/fuzz_msgpackc.py` feeds random, mutated and truncated data to
`loads`, `load` and an `Unpacker` fed in random chunks, checks that they
agree, and round-trips random objects. It runs on a unix build with
**AddressSanitizer and UndefinedBehaviorSanitizer** (`make test-sanitize`),
where any out-of-bounds access, use after free, overflow or undefined
behaviour aborts the run. The whole test suite and the differential test run
on that build too.

## 7. Coverage

`make coverage` runs the test programs on the coverage build and reports the
coverage of `modmsgpackc.c` with gcov: **99.1% of the lines, all branches
executed, 95.9% of them taken both ways**. The 9 lines never executed are
error paths that cannot be reached on purpose: objects above 4 GiB (4 lines;
no board holds one), a native subtype without a known layout (none exists in
MicroPython), a stream that writes less without reporting an error, a native
stream without `read`, and a second container-size check that the first
one always triggers before.

## 8. Memory

`msgpackc_memory.py` checks that thousands of calls do not make the heap
grow, and bounds the memory one call allocates: `dumps` allocates the result
and little more, `loads` allocates the objects it returns. The benchmark
measures the allocation of each call (see [BENCHMARKS.md](BENCHMARKS.md)).

## 9. Real hardware

The suite, the differential test, the conformance check and the fuzzer run on
real boards with `make test-device`, using the test firmware described in
[HARDWARE_TESTING.md](HARDWARE_TESTING.md).

## Build configurations

| build | where | floats | ints | notes |
|---|---|---|---|---|
| unix `standard` | macOS, Linux (CI) | double | arbitrary precision | 64-bit |
| unix `float32` | macOS, Linux (CI) | single | arbitrary precision | the float semantics of the boards |
| unix `longlong` | Linux (CI) | double | 64-bit only | a 32-bit build |
| unix `minimal` | Linux (CI) | none | | build check of the smallest configuration |
| unix `sanitize` | macOS, Linux (CI) | double | arbitrary precision | ASan + UBSan |
| unix `coverage` | macOS, Linux (CI) | double | arbitrary precision | gcov |
| ESP32 (Xtensa) | ESP32-PICO-V3-02 board | single | arbitrary precision | with and without PSRAM |
| ESP32-P4 (RISC-V) | ESP32-P4 board | single | arbitrary precision | 32 MiB PSRAM |

The CI also builds the firmware for ESP32, ESP32-S3, ESP32-C3, ESP32-C6 and
ESP32-P4.

## Benchmarks

`bench/bench.py` measures, for msgpackc, umsgpack and the built-in `json`,
on the same payloads: the time of `dumps` and `loads` (median of 5 runs,
each long enough for the timer), the heap allocated by one call (with the GC
disabled) and the size of the result. `tools/bench.py` runs it on unix builds
and boards and writes [BENCHMARKS.md](BENCHMARKS.md).

On the boards umsgpack is frozen into the firmware, which is the fastest and
leanest way to run Python code: the comparison is fair to it. Timings on a
computer vary with its load; on the boards they are stable to a few percent.

## Problems found along the way

Testing found real problems in msgpackc before its release, among them:

- `namedtuple` objects were read as Python class instances
  (`mp_obj_cast_to_native_base()` assumes one): found by the differential
  test.
- `load()` crashed on a Python file-like object: `mp_get_stream()` assumes the
  object is a native stream. Native streams are now recognised by their
  `read`/`write` methods.
- On the ESP32, a nesting limit of 128 levels left too little C stack to raise
  the exception at the deepest level: found only on the board. The limit is
  now 32.
- `hash()` of an `Unpacker` failed: found with the coverage build.
- On a 32-bit build, gcc rejected a length check as "always false"
  (`-Wtype-limits`, an error with `-Werror`); and a MicroPython configuration
  without `bytearray` failed to link: both found by the Linux builds of the CI
  (`tools/docker-ci.sh`), which macOS does not cover.
- Looking up every unpacked string as an existing qstr made lists of strings
  2.7 times slower to unpack on the ESP32-P4: only map keys are looked up now
  (see `MSGPACKC_REUSE_QSTR` in [USAGE.md](USAGE.md#12-build-time-configuration)).

It also found three issues of MicroPython itself, which only affect
sanitizer builds and are worked around in `tools/build-unix.sh`; they are
worth reporting upstream:

- `py/gc.c` marks `gc_get_ptr()` with `no_sanitize_address` behind
  `#if __GNUC__ > 4`, which is false for clang (it defines `__GNUC__` as 4):
  with clang, ASan reports the GC's scan of the C stack as a
  stack-buffer-overflow. Worked around with an ignore list
  (`tools/sanitizer-ignorelist.txt`).
- `mp_float_hash()` (`py/obj.h`) converts the float to an integer, undefined
  behaviour for huge floats (any `{1e300: 0}`); worked around with
  `MICROPY_FLOAT_HIGH_QUALITY_HASH=1`.
- clang's `pointer-overflow` check fires on an idiom of `py/vm.c`
  (`&sp[-n]`); gcc does not report it.

On builds limited to 64-bit ints (`longlong`), `int()` of a number above
2**64 does not raise `OverflowError`: `tests/mp/msgpackc_int64.py` checks for
big ints by converting the result back to a string.

And one of the macOS toolchain: the AddressSanitizer runtime refuses to start
("Interceptors are not working") when the binary keeps its symbol table; the
sanitizer build is stripped and keeps a copy with symbols
(`micropython.syms`) for reading reports.
