# msgpackc — fast MessagePack for MicroPython, in C

`msgpackc` is a [MessagePack](https://msgpack.org) serializer for
[MicroPython](https://micropython.org), written in C as a user module. It is
a drop-in alternative to Peter Hinch's excellent pure-Python
[umsgpack](https://github.com/peterhinch/micropython-msgpack): same API, same
options, same exceptions, same bytes on the wire, but tens of times faster
and allocating a fraction of the memory.

```python
import msgpackc

data = msgpackc.dumps({"id": "sensor-01", "temp": 21.5, "ok": True, "raw": b"\x01\x02"})
obj = msgpackc.loads(data)
```

MessagePack is like JSON, but binary: smaller messages, a `bytes` type, and
no text to parse. A `dict` that takes 60 bytes as JSON takes 36 as
MessagePack, and any MessagePack library in any language reads it.

<!-- BENCH-SUMMARY -->

Time to pack and unpack a list of 20 telemetry records (1 KiB), and heap allocated, per call ([all the figures](docs/BENCHMARKS.md)):

| | msgpackc dumps | umsgpack dumps | | msgpackc loads | umsgpack loads | |
|---|--:|--:|--:|--:|--:|--:|
| ESP32, internal RAM | **1204 µs**, 1040 B | 147757 µs, 60928 B | **122.7x** faster | **3833 µs**, 3296 B | 97049 µs, 19680 B | **25.3x** faster |
| ESP32, PSRAM | **2059 µs**, 1040 B | 169922 µs, 60928 B | **82.5x** faster | **5829 µs**, 3296 B | 118470 µs, 19680 B | **20.3x** faster |
| ESP32-P4 | **323 µs**, 1040 B | 24668 µs, 60928 B | **76.3x** faster | **791 µs**, 3296 B | 17104 µs, 19680 B | **21.6x** faster |
| unix port, Apple Silicon | **2.7 µs**, 1216 B | 196 µs, 120096 B | **74.0x** faster | **16.4 µs**, 5312 B | 169 µs, 38080 B | **10.3x** faster |

<!-- /BENCH-SUMMARY -->

## Features

- `dumps`, `dump`, `loads`, `load`, with the options of umsgpack
  (`force_float_precision`, `use_tuple`, `use_ordered_dict`,
  `allow_invalid_utf8`).
- **Extension types** with the same `@ext_serializable` decorator, for your
  classes and for built-in types such as `set` or `complex`; umsgpack's
  `mpk_*.py` extension modules work unchanged.
- **Streams**: `load` reads exactly one object from a file, socket or UART;
  `dump` writes it in one call.
- **Incremental decoding** with `Unpacker`, for data that arrives in pieces,
  and **asyncio** decoding with `ALoader`.
- **Safe on untrusted data**: corrupt or hostile input raises an exception;
  it never crashes the board nor allocates memory it does not need. Tested
  with fuzzing under AddressSanitizer and UndefinedBehaviorSanitizer.
- Tested on the unix port and on real ESP32 and ESP32-P4 boards; conforms to
  the cross-language [msgpack-test-suite](https://github.com/kawanet/msgpack-test-suite)
  and interoperates with [msgpack-python](https://github.com/msgpack/msgpack-python).
- About 12 KiB of flash (15 KiB on RISC-V chips), no RAM reserved, no configuration.

## Getting started

**Never built MicroPython?** Follow [docs/INSTALL.md](docs/INSTALL.md): it
goes step by step from a fresh computer to a board running `msgpackc`. In
short:

```bash
git clone --recursive https://github.com/Tangerino/micropython-msgpackc.git
cd micropython-msgpackc
make setup                     # tools for your computer
make unix                      # MicroPython for your computer, with msgpackc
build/unix-standard/micropython -c "import msgpackc; print(msgpackc.dumps([1, 2, 3]))"

make esp-idf                   # the ESP32 toolchain, installed inside this directory
make firmware BOARD=ESP32_GENERIC
make deploy BOARD=ESP32_GENERIC PORT=/dev/ttyUSB0   # erases the board!
```

**Already build your own firmware?** Add the module to it:

```bash
make USER_C_MODULES=/path/to/micropython-msgpackc/cmodules/micropython.cmake   # esp32, rp2
make USER_C_MODULES=/path/to/micropython-msgpackc/cmodules                     # unix, stm32, ...
```

**Coming from umsgpack?** Replace `import umsgpack` with
`import msgpackc as umsgpack`, or install the small compatibility package so
that `import umsgpack` keeps working: see
[docs/USAGE.md](docs/USAGE.md#9-moving-from-umsgpack).

## Documentation

| | |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | building and flashing, for beginners |
| [docs/USAGE.md](docs/USAGE.md) | the API, with examples, and the differences from umsgpack |
| [docs/TESTING.md](docs/TESTING.md) | how msgpackc is tested, and the results |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | speed and memory on the unix port, ESP32 and ESP32-P4 |
| [docs/HARDWARE_TESTING.md](docs/HARDWARE_TESTING.md) | testing on a board without losing what is on it |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to contribute |

## Repository layout

```
cmodules/                     the module: all you need to add it to a firmware
  micropython.cmake           entry point for USER_C_MODULES (CMake ports)
  msgpackc/modmsgpackc.c      the code
python/
  msgpackc_aio.py             msgpackc.ALoader (asyncio)
  umsgpack/__init__.py        compatibility package: `import umsgpack` -> msgpackc
firmware/                     manifests of the firmware built here
tests/                        test programs (see docs/TESTING.md)
bench/bench.py                the benchmark
tools/                        build, flash, test and benchmark scripts
micropython/                  MicroPython v1.29.0 (git submodule)
third_party/                  umsgpack and msgpack-test-suite, for the tests (submodules)
```

The ESP-IDF and the Espressif toolchains are installed in `tools/esp-idf`
and `tools/espressif` by `make esp-idf`; like `build/`, they are not part of
the repository.

## Acknowledgements

This project stands on the work of others, with gratitude:

- **Peter Hinch**, for [micropython-msgpack](https://github.com/peterhinch/micropython-msgpack)
  (umsgpack). Its careful API, its extension mechanism and its asyncio
  loader are the design `msgpackc` follows, its test suite checks
  `msgpackc` today, and its behaviour is the reference of our differential
  tests. If you prefer pure Python, or need to run on a stock firmware, use
  umsgpack: it is excellent. Peter's many other MicroPython libraries and
  documents are a treasure for the community.
- **Vanya A. Sergeev**, for [u-msgpack-python](https://github.com/vsergeev/u-msgpack-python),
  from which umsgpack was ported, and **WZab**, whose first port to
  MicroPython started it.
- **Damien George and the MicroPython contributors**, for
  [MicroPython](https://github.com/micropython/micropython).
- **Yusuke Kawasaki**, for the [msgpack-test-suite](https://github.com/kawanet/msgpack-test-suite).
- **Sadayuki Furuhashi** and the MessagePack community, for the
  [format](https://github.com/msgpack/msgpack/blob/master/spec.md).

`msgpackc` began as the MessagePack encoder written in C for the firmware of
the coIoTe IoT devices, as an accelerator of their Python packer; it was then
extracted, completed with a decoder, streams and extension types, and made a
general purpose module.

## License

MIT, see [LICENSE](LICENSE). umsgpack and msgpack-test-suite, used by the
tests as git submodules, are MIT licensed by their authors.
