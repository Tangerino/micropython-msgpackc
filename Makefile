# msgpackc: MessagePack for MicroPython, in C.
#
# Run `make help` for the list of targets. Everything is built under build/,
# and the ESP-IDF lives in tools/ (both ignored by git).

SHELL := bash

BOARD   ?= ESP32_GENERIC
VARIANT ?=
PORT    ?=
FLAVOURS ?= standard float32

PY := .venv/bin/python
UV := $(shell command -v uv 2>/dev/null)

# Build directory of the selected ESP32 firmware (see tools/build-esp32.sh).
fw_dir = build/$(shell echo $(BOARD) | tr 'A-Z_' 'a-z-')$(if $(VARIANT),-$(shell echo $(VARIANT) | tr 'A-Z_' 'a-z-'))$(1)

.PHONY: help setup esp-idf unix unix-all firmware firmware-test deploy flash-app \
        test test-quick test-sanitize coverage test-device bench bench-unix bench-board \
        format lint clean

help:
	@echo "msgpackc - MessagePack for MicroPython, in C"
	@echo
	@echo "First time:"
	@echo "  make setup                 submodules, host Python tools, mpy-cross"
	@echo "  make esp-idf               ESP-IDF v5.5.2 + toolchains, inside tools/ (for the boards)"
	@echo
	@echo "Unix port (your computer):"
	@echo "  make unix                  build/unix-standard/micropython with msgpackc"
	@echo "  make test                  all host tests (suite, differential, fuzz, interop...)"
	@echo "  make test-quick            the same, smaller"
	@echo "  make test-sanitize         tests on an AddressSanitizer + UBSan build"
	@echo "  make coverage              line/branch coverage of the module"
	@echo "  make bench-unix            benchmark on the unix port"
	@echo
	@echo "Boards (BOARD=$(BOARD) VARIANT=$(VARIANT) PORT=$(PORT)):"
	@echo "  make firmware              standard firmware with msgpackc"
	@echo "  make deploy PORT=...       erase the board and write that firmware"
	@echo "  make firmware-test         test firmware (RAM filesystem, umsgpack frozen in)"
	@echo "  make flash-app PORT=...    write only the test firmware application"
	@echo "  make test-device PORT=...  all tests on the board"
	@echo "  make bench-board PORT=...  benchmark on the board"
	@echo
	@echo "  make format / make lint    MicroPython code style (uncrustify, ruff)"

setup:
	git submodule update --init micropython third_party/micropython-msgpack third_party/msgpack-test-suite
	$(MAKE) -C micropython/ports/unix submodules
	$(MAKE) -C micropython/mpy-cross -j8
ifdef UV
	uv sync
else
	python3 -m venv .venv && .venv/bin/pip install -q msgpack pytest mpremote pyserial \
	    micropython-uncrustify==1.0.0.post1 ruff==0.11.6
endif

esp-idf:
	tools/setup-esp-idf.sh

unix:
	tools/build-unix.sh standard

unix-all:
	for f in $(FLAVOURS); do tools/build-unix.sh $$f || exit 1; done

firmware:
	tools/build-esp32.sh $(BOARD) $(VARIANT)

firmware-test:
	tools/build-esp32.sh $(BOARD) $(VARIANT) --test

# Erases the whole flash, as MicroPython's own deploy instructions do. The
# offsets of bootloader, partition table and application come from the
# flash_args file written by ESP-IDF, so this works for every chip.
deploy: firmware
	@test -n "$(PORT)" || (echo "PORT=... is required" && false)
	. tools/esp-env.sh && cd $(call fw_dir,) && esptool.py --port $(PORT) erase_flash && \
	  esptool.py --port $(PORT) -b 460800 write_flash @flash_args

flash-app:
	@test -n "$(PORT)" || (echo "PORT=... is required" && false)
	tools/flash-app.sh $(PORT) $(call fw_dir,-test)

test: unix-all
	$(PY) -m pytest

test-quick: unix-all
	MSGPACKC_QUICK=1 $(PY) -m pytest

test-sanitize:
	tools/build-unix.sh sanitize
	ASAN_OPTIONS=detect_leaks=0:abort_on_error=1 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
	  MSGPACKC_FLAVOURS=sanitize $(PY) -m pytest

coverage:
	tools/coverage.sh

test-device:
	@test -n "$(PORT)" || (echo "PORT=... is required" && false)
	tools/test-device.sh $(PORT)

bench-unix: unix
	$(PY) tools/bench.py run --unix standard

bench-board:
	@test -n "$(PORT)" || (echo "PORT=... is required" && false)
	$(PY) tools/bench.py run --port $(PORT) --label $(shell echo $(BOARD) | tr 'A-Z_' 'a-z-')$(if $(VARIANT),-$(shell echo $(VARIANT) | tr 'A-Z_' 'a-z-'))

format:
	.venv/bin/uncrustify -c micropython/tools/uncrustify.cfg -lC --no-backup -q cmodules/msgpackc/*.c
	.venv/bin/ruff format .

lint:
	.venv/bin/uncrustify -c micropython/tools/uncrustify.cfg -lC --check -q cmodules/msgpackc/*.c
	.venv/bin/ruff format --check .
	.venv/bin/ruff check .

clean:
	rm -rf build
