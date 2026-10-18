# dump/load on streams: native streams (BytesIO), Python file-like objects,
# short reads, several objects in a row, end of data.
try:
    import msgpackc
    import io
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc

# several objects back to back; load reads exactly one object each time
f = io.BytesIO()
objs = [1, "two", [3, {"four": b"\x04"}], None, -(2**40), {"x": [1.5]}]
for o in objs:
    m.dump(o, f)
f.seek(0)
print([m.load(f) for _ in objs] == objs)
try:
    m.load(f)
except m.InsufficientDataException:
    print("end of data")


# a file-like object whose read(n) returns one byte at a time
class Slow:
    def __init__(self, data):
        self.data = data

    def read(self, n):
        chunk, self.data = self.data[:1], self.data[1:]
        return chunk


big = {"key%d" % i: list(range(i)) for i in range(20)}
print(m.load(Slow(m.dumps(big))) == big)
print(m.load(Slow(m.dumps("s" * 300))) == "s" * 300)
print(m.load(Slow(m.dumps(b"b" * 3000))) == b"b" * 3000)


# read() returning None (non-blocking stream without data) is end of data
class NoData:
    def read(self, n):
        return None


try:
    m.load(NoData())
except m.InsufficientDataException:
    print("no data")


# a truncated object
try:
    m.load(io.BytesIO(m.dumps([1, 2, 3])[:-1]))
except m.InsufficientDataException:
    print("truncated")


# a writer with only a write() method receives the whole object in one call
class Writer:
    def __init__(self):
        self.calls = []

    def write(self, data):
        self.calls.append(bytes(data))


w = Writer()
m.dump({"a": [1, 2, 3]}, w)
print(len(w.calls), w.calls[0] == m.dumps({"a": [1, 2, 3]}))

# nothing is written if packing fails
w = Writer()
try:
    m.dump([1, 2, set()], w)
except m.UnsupportedTypeException:
    print("written:", w.calls)

# load options apply to streams too
print(m.load(io.BytesIO(b"\x92\x01\x02"), use_tuple=True))

# objects without read()/write()
for f, args in ((m.load, (1,)), (m.dump, (1, 1))):
    try:
        f(*args)
    except AttributeError:
        print("AttributeError")
