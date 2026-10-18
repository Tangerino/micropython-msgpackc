# Unpacker: incremental decoding of data that arrives in arbitrary chunks.
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc
objs = [{"a": [1, 2, 3]}, "hello", 42, [None, True, b"\x00" * 40], -1.5, {"n": {"m": {}}}]
stream = b"".join(m.dumps(o) for o in objs)

# every chunk size from 1 byte to the whole stream gives the same objects
for size in (1, 2, 3, 5, 7, 16, 64, len(stream)):
    u = m.Unpacker()
    out = []
    for i in range(0, len(stream), size):
        u.feed(stream[i : i + size])
        out.extend(u)
    print(size if size < 64 else "64+", out == objs, len(u))

# nothing complete yet: iteration stops at once and the data is kept
u = m.Unpacker()
u.feed(stream[:3])
print(list(u), len(u), bool(u))
u.feed(stream[3:])
print(len(list(u)), len(u), bool(u))

# next_raw returns the bytes of each complete object, without decoding
u = m.Unpacker()
u.feed(stream)
raws = []
while True:
    r = u.next_raw()
    if r is None:
        break
    raws.append(r)
print([m.loads(r) for r in raws] == objs)

# load options
u = m.Unpacker(use_tuple=True)
u.feed(b"\x92\x01\x92\x02\x03")
print(next(u))

# reset discards buffered data
u = m.Unpacker()
u.feed(b"\x93\x01")
u.reset()
u.feed(b"\x05")
print(list(u))

# a bad byte (0xc1) is skipped, so the stream resynchronises
u = m.Unpacker()
u.feed(b"\x01\xc1\x02")
out = []
while True:
    try:
        for o in u:
            out.append(o)
        break
    except m.ReservedCodeException:
        out.append("bad")
print(out)

# an object that fails to decode is consumed; decoding goes on after it
u = m.Unpacker()
u.feed(b"\xa2\xff\xfe\x07")
try:
    next(u)
except m.InvalidStringException:
    print("invalid string skipped")
print(next(u))

# max_buffer_size bounds the memory used by incomplete data
u = m.Unpacker(max_buffer_size=8)
u.feed(b"\xdb\x00\x01\x00\x00abc")
try:
    u.feed(b"defgh")
except ValueError as e:
    print("ValueError", e)
print(len(u))

# an ext unpackb may not feed the Unpacker that is decoding it
u = m.Unpacker()


@m.ext_serializable(0x30)
class Reentrant:
    def packb(self):
        return b"x"

    @staticmethod
    def unpackb(data, options):
        try:
            u.feed(b"\x01")
        except RuntimeError as e:
            return "RuntimeError: %s" % e
        return "fed"


u.feed(m.dumps(Reentrant()))
print(list(u))

# a deeply nested object split in single bytes
deep = []
cur = deep
for i in range(30):
    cur.append([])
    cur = cur[0]
data = m.dumps(deep)
u = m.Unpacker()
got = []
for i in range(len(data)):
    u.feed(data[i : i + 1])
    got.extend(u)
print(got == [deep])
