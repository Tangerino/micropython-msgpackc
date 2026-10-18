# Benchmark: msgpackc (C) against umsgpack (Peter Hinch, pure Python) and the
# built-in json module (C), on the same payloads. Runs under MicroPython: the
# unix port or a board.
#
#   micropython bench.py [quick]
#
# For every payload and library it measures:
#   - dumps and loads time in microseconds per call (median of several runs,
#     each long enough for the timer resolution);
#   - heap bytes allocated by one call (the GC is disabled meanwhile);
#   - the size of the encoded data.
# Each result is printed as a line "BENCH {json}", for tools/bench.py, followed
# by a readable table.

import gc
import json
import sys
import time

import msgpackc

try:
    import umsgpack
except ImportError:
    umsgpack = None

QUICK = "quick" in sys.argv
RUNS = 3 if QUICK else 5
MIN_US = 20_000 if QUICK else 100_000  # minimum duration of one run


def telemetry(i):
    return {
        "ts": 1729243200 + i,
        "id": "sensor-%02d" % (i % 100),
        "temp": 21.5 + i * 0.25,
        "hum": 48 + i % 7,
        "ok": True,
        "vbat": 3.71,
    }


PAYLOADS = [
    ("int", 42),
    ("telemetry", telemetry(0)),
    ("telemetry x20", [telemetry(i) for i in range(20)]),
    (
        "config",
        {
            "device": {"name": "gateway-7", "fw": "8.0.1", "serial": 40218, "debug": False},
            "wifi": {"ssid": "plant-floor", "channel": 6, "power": -4, "roam": [1, 6, 11]},
            "mqtt": {"host": "mqtt.example.org", "port": 8883, "tls": True, "keepalive": 60},
            "modbus": [{"addr": a, "baud": 9600, "regs": [0, 1, 2, 3, 40001]} for a in range(5)],
            "limits": {"tmin": -20.0, "tmax": 85.0, "vmin": 3.3},
        },
    ),
    ("int list x100", [i * 1237 - 50000 for i in range(100)]),
    ("float list x100", [i * 0.37 - 10 for i in range(100)]),
    ("str list x50", ["item-%d" % i for i in range(50)]),
    ("map x100", {"k%03d" % i: i for i in range(100)}),
    ("bytes 1 KiB", bytes(range(256)) * 4),
]

LIBS = [("msgpackc", msgpackc.dumps, msgpackc.loads)]
if umsgpack:
    LIBS.append(("umsgpack", umsgpack.dumps, umsgpack.loads))
LIBS.append(("json", json.dumps, json.loads))


def per_call_us(f, arg):
    # Find a loop count that lasts at least MIN_US, then take the median of RUNS.
    n = 1
    while True:
        gc.collect()
        t = time.ticks_us()
        for _ in range(n):
            f(arg)
        dt = time.ticks_diff(time.ticks_us(), t)
        if dt >= MIN_US or n >= 1 << 20:
            break
        n *= 2 if dt < MIN_US // 8 else 4
    samples = [dt / n]
    for _ in range(RUNS - 1):
        gc.collect()
        t = time.ticks_us()
        for _ in range(n):
            f(arg)
        samples.append(time.ticks_diff(time.ticks_us(), t) / n)
    samples.sort()
    return samples[len(samples) // 2]


def alloc_bytes(f, arg):
    f(arg)  # warm up (lazy imports of umsgpack, qstr creation...)
    gc.collect()
    gc.disable()
    try:
        a = gc.mem_alloc()
        f(arg)
        return gc.mem_alloc() - a
    finally:
        gc.enable()


def platform():
    try:
        import os

        u = os.uname()
        return "%s %s" % (u.machine, u.release)
    except Exception:
        return sys.platform


results = []
for pname, obj in PAYLOADS:
    for lname, dumps, loads in LIBS:
        if lname == "json" and isinstance(obj, bytes):
            continue  # JSON has no binary type
        data = dumps(obj)
        r = {
            "payload": pname,
            "lib": lname,
            "size": len(data),
            "dumps_us": per_call_us(dumps, obj),
            "loads_us": per_call_us(loads, data),
            "dumps_alloc": alloc_bytes(dumps, obj),
            "loads_alloc": alloc_bytes(loads, data),
        }
        results.append(r)
        print("BENCH", json.dumps(r))

print("BENCH-INFO", json.dumps({"platform": platform(), "float": msgpackc.float_precision}))
print()
print(
    "%-16s %-9s %6s %10s %10s %9s %9s"
    % ("payload", "lib", "bytes", "dumps us", "loads us", "d alloc", "l alloc")
)
for r in results:
    print(
        "%-16s %-9s %6d %10.1f %10.1f %9d %9d"
        % (
            r["payload"],
            r["lib"],
            r["size"],
            r["dumps_us"],
            r["loads_us"],
            r["dumps_alloc"],
            r["loads_alloc"],
        )
    )
