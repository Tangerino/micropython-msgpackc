# Installing msgpackc

This guide takes you from nothing to a board running MicroPython with
`msgpackc`. Follow the steps in order; every command is meant to be copied
as it is. No previous experience with MicroPython builds is needed.

- [1. What you need](#1-what-you-need)
- [2. Get the code](#2-get-the-code)
- [3. Prepare the tools](#3-prepare-the-tools)
- [4. Try msgpackc on your computer](#4-try-msgpackc-on-your-computer)
- [5. Build a firmware for an ESP32 board](#5-build-a-firmware-for-an-esp32-board)
- [6. Add msgpackc to your own MicroPython build](#6-add-msgpackc-to-your-own-micropython-build)
- [7. The Python helpers](#7-the-python-helpers)
- [8. Troubleshooting](#8-troubleshooting)

> **Why a build?** `msgpackc` is written in C, so it is compiled *into* the
> MicroPython firmware: you cannot just copy a file to the board. This repo
> makes that build a few commands long.

> **Shortcut for ESP32 boards:** each
> [release](https://github.com/Tangerino/micropython-msgpackc/releases/latest)
> has ready-made firmware for ESP32 (with and without PSRAM), ESP32-S3, C3,
> C6 and P4, with the `esptool.py` commands to write them. If your board is
> one of these and you do not need to change anything, you can skip this
> guide.

## 1. What you need

**A computer** with one of:

- **macOS** (Intel or Apple Silicon), with the Xcode command line tools:
  `xcode-select --install`
- **Linux** (Ubuntu, Debian, Fedora...), with the build tools. On Ubuntu or
  Debian:
  ```bash
  sudo apt install git make gcc python3 python3-venv pkg-config libffi-dev cmake ninja-build
  ```
- **Windows**: use [WSL 2](https://learn.microsoft.com/windows/wsl/install)
  with Ubuntu and follow the Linux instructions inside it. To reach a USB
  board from WSL, see [usbipd-win](https://learn.microsoft.com/windows/wsl/connect-usb).

You also need **git**, **Python 3.10 or newer** (`python3 --version`) and,
optionally, [**uv**](https://docs.astral.sh/uv/) (a fast Python package
manager; without it the steps use `pip`).

**Disk space**: about 1 GB for the code and the computer build. Building for
ESP32 boards needs the ESP-IDF, which this repo installs inside itself:
another 5 GB for all chips, about 2 GB for the original ESP32 only.

**For a board**: an ESP32-family board (ESP32, ESP32-S3, ESP32-C3, ESP32-C6,
ESP32-P4...) and a USB **data** cable (some cables only charge).

## 2. Get the code

```bash
git clone --recursive https://github.com/Tangerino/micropython-msgpackc.git
cd micropython-msgpackc
```

`--recursive` also downloads MicroPython v1.29.0 (in `micropython/`) and the
reference code used by the tests (in `third_party/`). If you cloned without
it, run `git submodule update --init` now.

Every command below is run from this directory.

## 3. Prepare the tools

```bash
make setup
```

This fetches the libraries MicroPython needs, builds `mpy-cross` (the
MicroPython compiler) and creates a Python environment in `.venv/` with the
test and board tools (`mpremote`, `pytest`, `msgpack`...). It takes a few
minutes the first time and does not touch the rest of your system.

## 4. Try msgpackc on your computer

MicroPython also runs on your computer (the "unix port"). It is the quickest
way to see `msgpackc` working:

```bash
make unix
build/unix-standard/micropython
```

You get the MicroPython prompt `>>>`. Type:

```python
>>> import msgpackc
>>> data = msgpackc.dumps({"temp": 21.5, "ok": True, "tags": ["a", "b"]})
>>> data
b'\x83\xa4tags\x92\xa1a\xa1b\xa2ok\xc3\xa4temp\xcb@5\x80\x00\x00\x00\x00\x00'
>>> msgpackc.loads(data)
{'tags': ['a', 'b'], 'ok': True, 'temp': 21.5}
```

Leave with `Ctrl-D`. The order of the keys printed may differ: MicroPython
dicts are unordered.

To run the whole test suite on your computer: `make test` (about 15
minutes; `make test-quick` takes 2). See [TESTING.md](TESTING.md).

## 5. Build a firmware for an ESP32 board

### 5.1 Install the ESP-IDF (once)

The ESP-IDF is Espressif's development framework; MicroPython v1.29 uses
version 5.5.2. This repo installs it **inside its own `tools/` directory**:
nothing goes to your home directory, and it never ends up in git.

```bash
make esp-idf
```

It downloads about 1.5 GB and takes 10 to 30 minutes. By default it installs
the compilers for esp32, esp32s3, esp32c3, esp32c6 and esp32p4. To install
only what you need (much smaller), choose the chips:

```bash
IDF_CHIPS=esp32 tools/setup-esp-idf.sh
```

| your chip | IDF_CHIPS |
|---|---|
| ESP32, ESP32-S2, ESP32-S3 | `esp32`, `esp32s2`, `esp32s3` |
| ESP32-C3, C5, C6, H2 | `esp32c3`, `esp32c5`, `esp32c6`, `esp32h2` |
| ESP32-P4 | `esp32p4` |

You never need to "activate" anything: the build commands of this repo do it
for themselves. If you want to use `idf.py` or `esptool.py` by hand, open a
shell and run `source tools/esp-env.sh` first.

### 5.2 Choose your board

MicroPython has a generic firmware for each chip. Pick the `BOARD` (and
`VARIANT` if needed) that matches yours:

| your board | BOARD | VARIANT |
|---|---|---|
| ESP32 (most "ESP32 DevKit" boards) | `ESP32_GENERIC` | |
| ESP32 with PSRAM (WROVER, PICO-V3...) | `ESP32_GENERIC` | `SPIRAM` |
| ESP32-S3 | `ESP32_GENERIC_S3` | `SPIRAM_OCT` if it has octal PSRAM |
| ESP32-C3 | `ESP32_GENERIC_C3` | |
| ESP32-C6 | `ESP32_GENERIC_C6` | |
| ESP32-P4, chip revision 3 or later | `ESP32_GENERIC_P4` | |
| ESP32-P4, chip revision 0.x or 1.x | `ESP32_GENERIC_P4` | `PRE_REV3` |

Not sure? Connect the board and ask it (see 5.4 for the port name):

```bash
source tools/esp-env.sh
esptool.py --port /dev/ttyUSB0 flash_id
```

It prints the chip, its revision, whether it has PSRAM ("Embedded PSRAM")
and the flash size. Other boards are in `micropython/ports/esp32/boards/`.

### 5.3 Build

```bash
make firmware BOARD=ESP32_GENERIC
```

or, for example, `make firmware BOARD=ESP32_GENERIC_P4 VARIANT=PRE_REV3`.
The first build takes 5 to 10 minutes; later builds are faster. The result is
in `build/<board>/firmware.bin`, for example `build/esp32-generic/firmware.bin`.

### 5.4 Find the serial port

Plug the board in, then:

- **macOS**: `ls /dev/tty.usb*` gives something like `/dev/tty.usbserial-0001`
  or `/dev/tty.usbmodem14101`.
- **Linux**: `ls /dev/ttyUSB* /dev/ttyACM*` gives `/dev/ttyUSB0` or
  `/dev/ttyACM0`. If you get "permission denied" later, add yourself to the
  `dialout` group (`sudo usermod -aG dialout $USER`), then log out and in.
- **WSL**: attach the board with `usbipd`, it then appears as `/dev/ttyUSB0`
  or `/dev/ttyACM0`.

Nothing appears? Try another cable (charge-only cables are common), or
install the USB driver of your board (CP210x or CH340, written on the chip
next to the USB connector).

### 5.5 Write the firmware to the board

> **This erases the whole flash of the board**, including any files on it.
> If the board holds something you want to keep, read
> [HARDWARE_TESTING.md](HARDWARE_TESTING.md) first: it shows how to back up
> the flash and how to test without erasing anything.

```bash
make deploy BOARD=ESP32_GENERIC PORT=/dev/ttyUSB0
```

Use the same `BOARD` and `VARIANT` as for the build. Some boards must be put
in download mode by hand: hold the **BOOT** button, press and release
**RESET** (or **EN**), release **BOOT**, then run the command again.

### 5.6 Use it

```bash
.venv/bin/mpremote connect /dev/ttyUSB0
```

You are now at the board's `>>>` prompt (leave with `Ctrl-]`). Try the same
lines as in section 4. To run a script from your computer on the board:

```bash
.venv/bin/mpremote connect /dev/ttyUSB0 run myscript.py
```

To run all the tests on the board, flash the *test firmware* instead (it
includes the reference implementation for the comparisons):

```bash
make firmware-test BOARD=ESP32_GENERIC
# then flash it, see HARDWARE_TESTING.md, and:
make test-device PORT=/dev/ttyUSB0
```

## 6. Add msgpackc to your own MicroPython build

If you already build MicroPython yourself (any port, v1.29 or later), you only
need the `cmodules/` directory of this repo. Copy it next to your project, or
reference it where it is, and pass it as a
[user C module](https://docs.micropython.org/en/latest/develop/cmodules.html):

**Ports built with CMake** (esp32, rp2): point to the `.cmake` file

```bash
cd micropython/ports/esp32
make BOARD=ESP32_GENERIC USER_C_MODULES=/path/to/cmodules/micropython.cmake
```

```bash
cd micropython/ports/rp2
make BOARD=RPI_PICO USER_C_MODULES=/path/to/cmodules/micropython.cmake
```

**Ports built with make** (unix, stm32, samd, nrf, mimxrt...): point to the
directory

```bash
cd micropython/ports/stm32
make BOARD=PYBV11 USER_C_MODULES=/path/to/cmodules
```

That is all: `import msgpackc` works on the new firmware. To check that the
module is in a firmware, run `help("modules")` at its prompt and look for
`msgpackc`.

The module needs nothing from the board and has no configuration to set. It
adds about 12 KiB of flash (15 KiB on RISC-V chips such as the ESP32-C3, C6 and P4) and reserves no RAM.

## 7. The Python helpers

Two optional Python files complete the C module. The firmware built by this
repo (`make firmware`) already contains the first one.

| file | gives you | needed for |
|---|---|---|
| `python/msgpackc_aio.py` | `msgpackc.ALoader` | asynchronous decoding with asyncio |
| `python/umsgpack/__init__.py` | `import umsgpack` | running code written for umsgpack unchanged |

To put them on a board without rebuilding, copy them with mpremote:

```bash
.venv/bin/mpremote connect PORT mkdir :lib + cp python/msgpackc_aio.py :lib/
.venv/bin/mpremote connect PORT mkdir :lib/umsgpack + cp python/umsgpack/__init__.py :lib/umsgpack/
```

or install them with `mip` from the board itself (when it has a network
connection) or from your computer:

```bash
.venv/bin/mpremote connect PORT mip install github:Tangerino/micropython-msgpackc
```

To freeze them into your own firmware, add to your manifest:

```python
module("msgpackc_aio.py", base_path="/path/to/python")
package("umsgpack", base_path="/path/to/python")
```

## 8. Troubleshooting

**`make esp-idf` stops with "This script was called from a virtual
environment"**: the script removes active virtualenvs from `PATH` itself; if
you see this, run `deactivate` (or open a new terminal) and try again.

**`xtensa-esp32-elf-gcc is not a full path and was not found in the PATH`**
(or `riscv32-esp-elf-gcc`): the compiler of your chip is not installed. Run
`IDF_CHIPS=<your chip> tools/setup-esp-idf.sh` (see 5.1).

**`Invalid BOARD specified`**: the board name is wrong; the names are the
directories of `micropython/ports/esp32/boards/`, in capital letters.

**The ESP32-P4 does not boot after flashing** (it keeps resetting): your chip
is older than revision 3; build with `VARIANT=PRE_REV3`.

**`A fatal error occurred: Failed to connect`**: put the board in download
mode (5.5), close any other program that uses the serial port (an open
`mpremote`, the Arduino IDE serial monitor...), try a lower speed by
running esptool by hand with `-b 115200`.

**`ImportError: no module named 'msgpackc'`** on the board: the board runs a
firmware without the module (for example one downloaded from
micropython.org). Build and flash it as in section 5.

**`ImportError: no module named 'msgpackc_aio'`** when using
`msgpackc.ALoader`: your firmware does not include the helper; copy it as in
section 7.

**The build of the unix port fails on macOS with `ffi.h` not found**: install
libffi (`brew install libffi pkg-config`).

Still stuck? Open an issue with the command you ran and its full output.
