# Edge cases of the API, mostly error paths, found with the coverage build.
try:
    import msgpackc
    import io
    import sys
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc


def show(f, *args, **kw):
    try:
        r = f(*args, **kw)
        print("returned", repr(r)[:60])
    except Exception as e:
        print(type(e).__name__, str(e)[:60])


# arrays longer than the stream preallocation (64 items), as list and tuple
data = m.dumps(list(range(100)))
print(m.load(io.BytesIO(data)) == list(range(100)))
print(m.load(io.BytesIO(data), use_tuple=True) == tuple(range(100)))
print(len(m.load(io.BytesIO(m.dumps({i: i for i in range(100)})))))


# read() returning an empty result, or more than asked for
class Reader:
    def __init__(self, data, extra=b""):
        self.data = data
        self.extra = extra

    def read(self, n):
        out, self.data = self.data[:n], self.data[n:]
        return out + self.extra


show(m.load, Reader(b"\x92\x01"))
show(m.load, Reader(b"\x92\x01\x02", extra=b"!"))


# I/O errors of native streams are OSError. Some filesystems (littlefs on the
# boards) report a read of a write-only file as end of data, or ignore a write
# to a read-only file, instead: those outcomes are accepted too.
def io_outcome(f, *args):
    try:
        f(*args)
        return "ok"
    except (OSError, m.InsufficientDataException):
        return "ok"


try:
    with open("msgpackc_edge.tmp", "wb") as f:
        f.write(b"\x01")
        print(io_outcome(m.load, f))  # not readable
    with open("msgpackc_edge.tmp", "rb") as f:
        print(io_outcome(m.dump, 1, f))  # not writable
    import os

    os.remove("msgpackc_edge.tmp")
except OSError:
    print("ok")  # no writable filesystem
    print("ok")


# a list that grows while it is packed (by an ext packb), not at the end
@m.ext_serializable(0x60)
class Grow:
    def __init__(self, target):
        self.target = target

    def packb(self):
        self.target.append(0)
        return b""


lst = [0]
lst.append(Grow(lst))
lst.append(1)
show(m.dumps, lst)


# a dict that grows while it is packed
@m.ext_serializable(0x61)
class GrowDict:
    def __init__(self, target):
        self.target = target

    def packb(self):
        for i in range(100):
            self.target["k%d" % i] = i
        return b""


d = {"a%d" % i: i for i in range(10)}
d["g"] = GrowDict(d)
show(m.dumps, d)

# the registry module replaced in sys.modules is rebuilt; broken dicts are an error
reg = sys.modules["_msgpackc_ext"]
sys.modules["_msgpackc_ext"] = 1
m.ext_serializable(0x62)(type("Fresh", (), {}))
print(sorted(m.packers))
sys.modules["_msgpackc_ext"].packers = 1
show(m.loads, b"\xd4\x62\x00")
sys.modules["_msgpackc_ext"] = reg

# iterating an Unpacker again without feeding it, and other operations
u = m.Unpacker()
u.feed(b"\x92")
print(list(u), list(u), len(u))
print(type(hash(u)) is int)
show(lambda: -u)
show(m.Unpacker, 1)
show(u.feed, 1)
show(m.Unpacker(max_buffer_size=4).feed, b"12345")
