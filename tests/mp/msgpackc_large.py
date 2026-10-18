# The 32-bit length formats (str 32, bin 32, array 32, map 32, ext 32), which
# need objects of 64 KiB and more. Skipped where the heap is too small.
try:
    import msgpackc
    import gc
except ImportError:
    print("SKIP")
    raise SystemExit

gc.collect()
if gc.mem_free() < 4_000_000:
    print("SKIP")
    raise SystemExit

m = msgpackc
N = 0x10000


def head(p, n):
    return p[:n]


s = "a" * N
p = m.dumps(s)
print(head(p, 5), len(p), m.loads(p) == s)
b = b"b" * N
p = m.dumps(b)
print(head(p, 5), len(p), m.loads(p) == b)
lst = [None] * N
p = m.dumps(lst)
print(head(p, 5), len(p), m.loads(p) == lst)
lst = [0] * 0xFFFF
p = m.dumps(lst)
print(head(p, 3), len(p))
d = {i: None for i in range(N)}
p = m.dumps(d)
print(head(p, 5), len(p), m.loads(p) == d)
del s, b, lst, d, p
gc.collect()


@m.ext_serializable(0x20)
class Big:
    def packb(self):
        return bytes(N)

    @staticmethod
    def unpackb(data, options):
        return len(data)


p = m.dumps(Big())
print(head(p, 6), len(p), m.loads(p))

# streams with large payloads
import io

f = io.BytesIO()
m.dump(["x" * 70000, b"y" * 70000], f)
f.seek(0)
r = m.load(f)
print(len(r[0]), len(r[1]))
