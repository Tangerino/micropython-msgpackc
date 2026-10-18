# Memory: repeated packing and unpacking does not leak, and the heap used by
# one call is small and bounded.
try:
    import msgpackc
    import gc
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc
rec = {"ts": 1729243200, "id": "sensor-01", "t": -12.5, "ok": True, "v": [1, 2, 3], "raw": b"\x01"}
data = m.dumps(rec)


def heap_after(n):
    for _ in range(n):
        m.loads(m.dumps(rec))
    gc.collect()
    return gc.mem_alloc()


# The conservative GC makes the figure wander by a few dozen bytes; a leak
# would grow with the number of calls (5000 calls leaking 1 byte = 5000).
heap_after(10)
a = heap_after(100)
heap_after(1000)
b = heap_after(5000)
print("no leak:", b - a <= 256)

# bytes allocated by one call (the GC is off, so nothing is reclaimed meanwhile)
gc.collect()
gc.disable()
a = gc.mem_alloc()
m.dumps(rec)
pack_alloc = gc.mem_alloc() - a
a = gc.mem_alloc()
m.loads(data)
unpack_alloc = gc.mem_alloc() - a
gc.enable()
print("dumps allocates <= 2x the result:", pack_alloc <= 2 * len(data) + 64)
print("loads allocates < 1 KiB:", unpack_alloc < 1024)
