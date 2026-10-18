# Fuzzer for msgpackc, meant to run on the sanitizer build of the unix port
# (tools/build-unix.sh sanitize), where any memory error aborts the process.
#
#   micropython fuzz_msgpackc.py [iterations=N] [seed=N]
#
# 1. Random, mutated and truncated byte strings go through loads(), load()
#    and an Unpacker fed in random chunks: only msgpackc exceptions (and
#    RuntimeError for nesting) may come out, never a crash, and the three
#    entry points must agree.
# 2. Random objects round-trip: loads(dumps(o)) equals o, up to the types
#    MessagePack cannot distinguish (tuple/list, bytearray/bytes, subclasses).
#
# Last line: "RESULT: OK ..." or "RESULT: FAIL ...".

import io
import random
import struct
import sys

import msgpackc as m

ITER = 200000
SEED = 7
for a in sys.argv:
    if a.startswith("iterations="):
        ITER = int(a[11:])
    if a.startswith("seed="):
        SEED = int(a[5:])
random.seed(SEED)

ALLOWED = (
    m.UnpackException,
    m.UnsupportedTypeException,  # unknown ext type, as in umsgpack
    RuntimeError,  # nesting deeper than the limit
    NotImplementedError,  # ext type registered without unpackb
)
fails = 0
counts = {}


def fail(*args):
    global fails
    fails += 1
    if fails <= 10:
        print("FAIL", *args)


@m.ext_serializable(0x01)
class E1:
    def __init__(self, data=b""):
        self.data = data

    def packb(self):
        return self.data

    @staticmethod
    def unpackb(data, options):
        return E1(data)

    def __eq__(self, other):
        return isinstance(other, E1) and self.data == other.data


@m.ext_serializable(0x02)
class NoUnpack:
    def packb(self):
        return b"\x00"


def outcome(f, *a, **kw):
    try:
        return ("ok", f(*a, **kw))
    except ALLOWED as e:
        return ("exc", type(e).__name__)
    except MemoryError:
        return ("exc", "MemoryError")


def rbytes(n):
    return bytes(random.getrandbits(8) for _ in range(n))


def robj(depth=0):
    r = random.getrandbits(4)
    if depth > 5:
        r %= 7
    if r == 0:
        return (random.getrandbits(32) << random.getrandbits(5)) - (1 << 35)
    if r == 1:
        return random.choice([None, True, False, 0, -1, 2**63, -(2**63), 2**64 - 1])
    if r == 2:
        return struct.unpack(">d", rbytes(8))[0]
    if r == 3:
        return "".join(
            chr(random.choice((97, 233, 8364, 128512))) for _ in range(random.getrandbits(6))
        )
    if r == 4:
        return rbytes(random.getrandbits(6))
    if r == 5:
        return E1(rbytes(random.choice((0, 1, 2, 3, 4, 8, 16, 17, 300))))
    if r == 6:
        return random.getrandbits(7)
    if r < 10:
        return [robj(depth + 1) for _ in range(random.getrandbits(3))]
    if r < 12:
        return tuple(robj(depth + 1) for _ in range(random.getrandbits(3)))
    if r < 15:
        d = {}
        for _ in range(random.getrandbits(3)):
            k = robj(6)  # a scalar
            if isinstance(k, (list, E1)) or k != k:
                k = str(k)
            d[k] = robj(depth + 1)
        return d
    return bytearray(rbytes(random.getrandbits(4)))


def norm(o):
    """The object as it comes back from loads(dumps(o))."""
    if isinstance(o, (list, tuple)):
        return [norm(x) for x in o]
    if isinstance(o, dict):
        return {norm_key(k): norm(v) for k, v in o.items()}
    if isinstance(o, bytearray):
        return bytes(o)
    if isinstance(o, float):
        return struct.pack(">d", o) if m.float_precision == "double" else struct.pack(">f", o)
    return o


def norm_key(k):
    return tuple(norm(k)) if isinstance(k, tuple) else norm(k)


def norm_loaded(o):
    if isinstance(o, (list, tuple)):
        return [norm_loaded(x) for x in o]
    if isinstance(o, dict):
        return {norm_key_loaded(k): norm_loaded(v) for k, v in o.items()}
    if isinstance(o, float):
        return struct.pack(">d", o) if m.float_precision == "double" else struct.pack(">f", o)
    return o


def norm_key_loaded(k):
    return tuple(norm_loaded(k)) if isinstance(k, tuple) else norm_loaded(k)


corpus = [m.dumps(robj()) for _ in range(200)]


def mutate(d):
    d = bytearray(d)
    for _ in range(random.getrandbits(2) + 1):
        if not d:
            d.extend(rbytes(1))
            continue
        i = random.getrandbits(16) % len(d)
        r = random.getrandbits(2)
        if r == 0:
            d[i] = random.getrandbits(8)
        elif r == 1:
            d = d[:i]
        elif r == 2:
            d[i:i] = bytes([random.choice((0xC1, 0xDC, 0xDD, 0xDE, 0xDF, 0xDB, 0xC6, 0xC9, 0xD8))])
        else:
            d[i:i] = random.choice(corpus)
    return bytes(d)


def feed_all(data):
    u = m.Unpacker()
    out = []
    i = 0
    while i < len(data):
        n = random.getrandbits(3) + 1
        u.feed(data[i : i + n])
        i += n
        while True:
            try:
                for o in u:
                    out.append(("ok", o))
                break
            except ALLOWED as e:
                out.append(("exc", type(e).__name__))
    return out, len(u)


for it in range(ITER):
    r = random.getrandbits(2)
    if r == 0:
        data = rbytes(random.getrandbits(5))
    elif r == 1:
        data = random.choice(corpus)
    else:
        data = mutate(random.choice(corpus))

    a = outcome(m.loads, data)
    b = outcome(m.load, io.BytesIO(data))
    key = a[0] if a[0] == "ok" else a[1]
    counts[key] = counts.get(key, 0) + 1
    if a[0] != b[0] or (a[0] == "exc" and a[1] != b[1]):
        fail("loads/load disagree", data, a, b)
    if random.getrandbits(3) == 0:
        # A whole object at the start of the stream must come out of the
        # Unpacker exactly as loads() decodes it.
        out, pending = feed_all(data)
        # Compared re-packed: a NaN inside never equals itself.
        if a[0] == "ok" and out and out[0][0] == "ok" and m.dumps(out[0][1]) != m.dumps(a[1]):
            fail("Unpacker disagrees", data, out[0], a)

    if it % 4 == 0:
        o = robj()
        try:
            p = m.dumps(o)
        except Exception as e:
            fail("dumps raised", repr(o)[:80], e)
            continue
        back = m.loads(p)
        if norm_loaded(back) != norm(o):
            fail("round trip", repr(o)[:80], repr(back)[:80])

print("outcomes:", sorted(counts.items()))
if fails:
    print("RESULT: FAIL", fails, "failures in", ITER, "iterations")
else:
    print("RESULT: OK", ITER, "iterations")
