# Robustness: hostile input, deep nesting, cycles, and Python callbacks that
# modify the data being packed or unpacked. Nothing here may crash.
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc


def show(f, *args, **kw):
    try:
        r = f(*args, **kw)
        print("returned", repr(r)[:50])
    except Exception as e:
        print(type(e).__name__, str(e)[:60])


# nesting deeper than the limit (32) is refused, not a stack overflow
deep = []
cur = deep
for _ in range(200):
    cur.append([])
    cur = cur[0]
show(m.dumps, deep)
show(m.loads, b"\x91" * 200 + b"\xc0")
show(m.loads, b"\x81\x01" * 200 + b"\xc0")

# the limit itself is fine
ok = []
cur = ok
for _ in range(31):
    cur.append([])
    cur = cur[0]
print(m.loads(m.dumps(ok)) == ok)
cur.append([])
show(m.dumps, ok)
show(m.loads, b"\x91" * 32 + b"\xc0")
print(m.loads(b"\x91" * 31 + b"\xc0") is not None)

# a list that contains itself
cyc = [1]
cyc.append(cyc)
show(m.dumps, cyc)

# huge declared sizes with little data: an error, no huge allocation
for data in (
    b"\xdd\x7f\xff\xff\xff",
    b"\xdf\x7f\xff\xff\xff",
    b"\xdb\x7f\xff\xff\xff",
    b"\xc6\x7f\xff\xff\xff",
    b"\xc9\x7f\xff\xff\xff\x01",
    b"\xdd\x7f\xff\xff\xff" + b"\x90" * 10,
):
    show(m.loads, data)
    show(m.loads, data, use_tuple=True)

# every truncation of a valid message
msg = m.dumps({"a": [1, 2.5, "xyz", b"\x00\x01", {"b": None}], "c": -70000, "d": 2**40})
errs = set()
for n in range(len(msg)):
    try:
        m.loads(msg[:n])
        errs.add("decoded")
    except m.InsufficientDataException:
        errs.add("InsufficientDataException")
print(sorted(errs))

# every single-byte value as a whole message
kinds = {}
for b in range(256):
    try:
        r = type(m.loads(bytes([b]))).__name__
    except Exception as e:
        r = type(e).__name__
    kinds[r] = kinds.get(r, 0) + 1
print(sorted(kinds.items()))


# an ext packb that grows the list being packed
@m.ext_serializable(0x40)
class Grow:
    def __init__(self, target):
        self.target = target

    def packb(self):
        self.target.append(0)
        return b""


lst = [0]
lst.append(Grow(lst))
show(m.dumps, lst)


# an ext packb that adds keys to the dict being packed
@m.ext_serializable(0x41)
class GrowDict:
    def __init__(self, target):
        self.target = target

    def packb(self):
        for i in range(20):
            self.target[i] = i
        return b""


d = {"a": 0}
d["b"] = GrowDict(d)
show(m.dumps, d)

# an ext unpackb that resizes the bytearray being unpacked
buf = bytearray()


@m.ext_serializable(0x42)
class Shrink:
    def packb(self):
        return b""

    @staticmethod
    def unpackb(data, options):
        buf[:] = b""
        return "shrunk"


@m.ext_serializable(0x43)
class Enlarge:
    def packb(self):
        return b""

    @staticmethod
    def unpackb(data, options):
        buf.extend(bytes(4096))  # the buffer moves
        return "enlarged"


buf.extend(m.dumps([Shrink(), "after"]))
show(m.loads, buf)
buf[:] = m.dumps([Enlarge(), "after", [1, 2, 3]])
show(m.loads, buf)

# keys whose hash raises are unhashable keys, not crashes
show(m.loads, b"\x81\x81\x01\x02\x03")
show(m.loads, b"\x81\x92\x01\x80\x02")
