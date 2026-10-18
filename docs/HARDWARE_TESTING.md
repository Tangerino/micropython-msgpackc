# Testing on real boards

The tests and benchmarks of this project run on real ESP32 boards, not only
on a computer: timing, memory and 32-bit behaviour are only true there. This
page explains how to do that **without losing what is on the board**: a
board on your bench usually runs an application, with its own files and
settings, that you want back afterwards.

- [The idea](#the-idea)
- [1. Back up the whole flash](#1-back-up-the-whole-flash)
- [2. Build the test firmware](#2-build-the-test-firmware)
- [3. Write only the application](#3-write-only-the-application)
- [4. Run the tests and the benchmarks](#4-run-the-tests-and-the-benchmarks)
- [5. Put the board back as it was](#5-put-the-board-back-as-it-was)
- [What was tested](#what-was-tested)

## The idea

An ESP32 flash is divided in partitions: the bootloader, a partition table,
one or more *application* partitions (the firmware), and *data* partitions
(the filesystem with `boot.py`, `main.py` and the application's files,
settings in NVS, logs...).

The **test firmware** of this project is built so that it can run on such a
board without touching its data:

- only the application partition is written, the rest of the flash is left
  as it is (`tools/flash-app.sh`);
- its `_boot.py` (`firmware/testboot/_boot.py`) does **not** mount the flash
  filesystem: it mounts a small filesystem in RAM instead. The application's
  files are not read, not modified, and its `boot.py`/`main.py` do not run;
- it includes Peter Hinch's umsgpack, frozen, as the reference for the
  differential tests and the benchmarks.

So the board's files and settings survive, and once you write the original
application back, the board is exactly as before. A full backup of the
flash comes first anyway.

> Use this on boards whose application partition is at least as large as
> the test firmware application (1.5 to 1.7 MiB depending on the chip):
> `tools/flash-app.sh` checks it and refuses otherwise.

## 1. Back up the whole flash

```bash
tools/backup-flash.sh /dev/ttyUSB0
```

The file goes to `.private/flash-backups/<chip>_<mac>_<size>.bin` (the
`.private/` directory is not in git), with its SHA-256 next to it. Reading
8 MiB takes about 3 minutes over a USB-UART bridge; 16 MiB over the
USB-Serial/JTAG port of an ESP32-P4 takes about 25 minutes.

## 2. Build the test firmware

```bash
make firmware-test BOARD=ESP32_GENERIC VARIANT=SPIRAM
```

(see [INSTALL.md](INSTALL.md#52-choose-your-board) for `BOARD` and
`VARIANT`). The output is in `build/<board>-<variant>-test/`.

## 3. Write only the application

```bash
make flash-app BOARD=ESP32_GENERIC VARIANT=SPIRAM PORT=/dev/ttyUSB0
```

which runs `tools/flash-app.sh`: it reads the partition table **from the
board**, finds its application partition (`factory`, else `ota_0`), checks
that the test application fits, and writes `micropython.bin` there and
nowhere else.

Check it booted:

```bash
.venv/bin/mpremote connect /dev/ttyUSB0 exec "import os, msgpackc; print(os.uname().version, os.listdir('/'))"
```

`os.listdir('/')` shows the RAM filesystem: empty, the application's files
are not visible.

## 4. Run the tests and the benchmarks

```bash
make test-device PORT=/dev/ttyUSB0
make bench-board BOARD=ESP32_GENERIC VARIANT=SPIRAM PORT=/dev/ttyUSB0
```

`test-device` runs, on the board: the `run-tests.py` suite, the differential
test against umsgpack, the msgpack-test-suite conformance and the fuzzer.
`bench-board` saves the results in `docs/benchmarks/` and regenerates
[BENCHMARKS.md](BENCHMARKS.md).

## 5. Put the board back as it was

Write back only the application partition of the backup (fast):

```bash
tools/restore-flash.sh /dev/ttyUSB0 .private/flash-backups/<file>.bin --app-only
```

or the whole flash (slow, but byte for byte):

```bash
tools/restore-flash.sh /dev/ttyUSB0 .private/flash-backups/<file>.bin
```

To check that nothing else changed, make a second backup and compare the
two files: `cmp backup1.bin backup2.bin`. Differences can only be in the
data the original application itself wrote while it ran.

## What was tested

The figures in [TESTING.md](TESTING.md) and [BENCHMARKS.md](BENCHMARKS.md)
were obtained this way on two boards running a production IoT application,
which was back in service afterwards:

| board | chip | flash / PSRAM | firmware |
|---|---|---|---|
| ESP32-PICO-V3-02 | ESP32 rev 3.0, 240 MHz, dual core | 8 MiB / 2 MiB | `ESP32_GENERIC`, `SPIRAM` and no variant |
| ESP32-P4 board | ESP32-P4 rev 1.0 (RISC-V), 360 MHz | 16 MiB / 32 MiB | `ESP32_GENERIC_P4`, `PRE_REV3` |
