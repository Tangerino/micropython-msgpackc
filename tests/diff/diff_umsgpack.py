# Differential test: msgpackc (C) against Peter Hinch's umsgpack (Python).
#
# Runs under MicroPython (unix port or a board) with both modules importable.
# Random objects are packed by both modules and must give the same bytes or
# the same exception (type and message). Random, valid, mutated and truncated
# byte strings are unpacked by both and must give equal objects or the same
# exception. The PRNG is seeded, so a run is reproducible.
#
#   micropython diff_umsgpack.py [quick] [seed=N]
#
# Last line: "RESULT: OK <n> checks" or "RESULT: FAIL <n> mismatches".

import io
import struct
import sys

import msgpackc
import umsgpack  # the reference: Peter Hinch's pure-Python module

try:
    from collections import OrderedDict, namedtuple
except ImportError:
    OrderedDict = namedtuple = None

QUICK = "quick" in sys.argv
SEED = 1
for a in sys.argv:
    if a.startswith("seed="):
        SEED = int(a[5:])

import random  # noqa: E402

random.seed(SEED)

N_PACK = 400 if QUICK else 20000
N_UNPACK = 1000 if QUICK else 60000
MAX_DEPTH = 4 if QUICK else 6
BIG = not QUICK  # strings and containers with 16/32-bit length headers

checks = 0
fails = 0
# umsgpack reads a declared length with fp.read(n), which allocates n bytes
# before finding out the data is not there: corrupt input gives MemoryError,
# or OverflowError on 32-bit ports when the length exceeds 2**31. msgpackc
# checks the data available first and raises InsufficientDataException.
# Counted, not reported.
improved = 0
AVOIDED = ("MemoryError", "OverflowError")
# On 32-bit ports umsgpack's range(n) overflows before reading the items, where
# msgpackc reads them and reports the first real error in the data.
UNPACK_ERRORS = (
    "InsufficientDataException",
    "InvalidStringException",
    "ReservedCodeException",
    "UnhashableKeyException",
    "DuplicateKeyException",
    "UnsupportedTypeException",
)
kinds = {}  # mismatch summary: (operation, msgpackc result, umsgpack result) -> count


def report(kind, inp, a, b):
    global fails
    fails += 1
    key = (kind.split()[0], a[0] if a[0] == "ok" else a[1], b[0] if b[0] == "ok" else b[1])
    kinds[key] = kinds.get(key, 0) + 1
    if fails <= 10:
        print("MISMATCH", kind)
        print("  input:   ", repr(inp)[:300])
        print("  msgpackc:", repr(a)[:300])
        print("  umsgpack:", repr(b)[:300])


def no_addr(msg):
    # "<Point object at 7f12ab>": the address differs between the two runs.
    out = []
    i = 0
    while True:
        j = msg.find(" at ", i)
        if j < 0:
            out.append(msg[i:])
            return "".join(out)
        out.append(msg[i : j + 4])
        i = j + 4
        while i < len(msg) and msg[i] in "0123456789abcdefx":
            i += 1


def same(a, b):
    # Compare the kinds first: comparing bytes with str makes MicroPython warn.
    global improved
    if a[0] == b[0] == "exc" and b[1] in AVOIDED and a[1] in UNPACK_ERRORS:
        improved += 1
        return True
    if (
        a[0] == b[0] == "exc"
        and a[1] == b[1]
        and a[1] in ("UnhashableKeyException", "DuplicateKeyException")
    ):
        # The message shows the key: when it is a dict its item order may
        # differ (msgpackc presizes dicts, so their hash tables differ).
        return sorted(no_addr(a[2])) == sorted(no_addr(b[2]))
    return a[0] == b[0] and a == b


def outcome(f, *args, **kw):
    try:
        return ("ok", f(*args, **kw))
    except Exception as e:  # noqa: BLE001 - every exception is part of the result
        return ("exc", type(e).__name__, str(e))


# --- values for the generator ----------------------------------------------

INT_EDGES = [
    0, 1, 0x7F, 0x80, 0xFF, 0x100, 0xFFFF, 0x10000, 0x7FFFFFFF, 0x80000000,
    0xFFFFFFFF, 0x100000000, 2**62, 2**63 - 1, 2**63, 2**64 - 1, 2**64, 2**65,
    -1, -31, -32, -33, -127, -128, -129, -32767, -32768, -32769,
    -(2**31) + 1, -(2**31), -(2**31) - 1, -(2**62), -(2**63) + 1, -(2**63),
    -(2**63) - 1, -(2**64), -(2**70),
]  # fmt: skip
STR_LENS = [0, 1, 2, 30, 31, 32, 33, 254, 255, 256, 257]
BIG_LENS = [65534, 65535, 65536, 65537]
depth_now = 0  # big strings and containers only near the top, or memory explodes
CHARS = "abcxyz09 _-\x00\x7féüΩ€中\U0001f600"


class MyInt(int):
    pass


class MyStr(str):
    pass


class MyList(list):
    pass


class MyTuple(tuple):
    pass


class MyDict(dict):
    pass


class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def packb(self):
        return struct.pack(">ii", self.x, self.y)

    @staticmethod
    def unpackb(data, options):
        return Point(*struct.unpack(">ii", data))


class NoPackb:
    pass


NT = namedtuple("NT", ("a", "b")) if namedtuple else None


def rint():
    r = random.getrandbits(3)
    if r < 4:
        return random.choice(INT_EDGES) + random.getrandbits(2) - 1
    if r < 6:
        return random.getrandbits(7) - 64
    bits = random.getrandbits(6) + 1
    v = random.getrandbits(min(bits, 32))
    if bits > 32:
        v = (v << (bits - 32)) | random.getrandbits(bits - 32)
    return -v if random.getrandbits(1) else v


def rfloat():
    r = random.getrandbits(3)
    if r == 0:
        return random.choice([0.0, -0.0, 1.0, -1.5, 0.1, 1e10, 1e-10, 3.4e38, 1e300, -1e-300])
    if r == 1:
        return float(random.choice(["inf", "-inf", "nan"]))
    if r < 5:
        return (random.getrandbits(20) - 2**19) / (random.getrandbits(10) + 1)
    b = bytes(random.getrandbits(8) for _ in range(8))
    return struct.unpack(">d", b)[0]


def rsize():
    if BIG and depth_now <= 1 and random.getrandbits(6) == 0:
        return random.choice(BIG_LENS)
    return random.choice(STR_LENS) if random.getrandbits(2) == 0 else random.getrandbits(5)


def rstr():
    n = rsize()
    if n > 300:
        return random.choice(CHARS) * n
    return "".join(random.choice(CHARS) for _ in range(n))


def rbytes():
    n = rsize()
    if n > 300:
        return bytes([random.getrandbits(8)]) * n
    return bytes(random.getrandbits(8) for _ in range(n))


def rlen():
    r = random.getrandbits(4)
    if r == 0 and BIG and depth_now == 0:
        return random.choice([15, 16, 17, 300])
    return random.getrandbits(3)


def rkey():
    r = random.getrandbits(3)
    if r < 4:
        return rstr()[:12]
    if r == 4:
        return rint()
    if r == 5:
        return rbytes()[:6]
    if r == 6:
        return random.choice([None, True, False, 1.5])
    return (rint(), rstr()[:4])


def robj(depth=0, ext=False):
    global depth_now
    depth_now = depth
    r = random.getrandbits(5)
    if depth >= MAX_DEPTH:
        r %= 12
    if r < 3:
        return rint()
    if r == 3:
        return random.choice([None, True, False])
    if r < 6:
        return rfloat()
    if r < 9:
        return rstr()
    if r < 11:
        return rbytes()
    if r == 11:
        return bytearray(rbytes())
    if r < 15:
        return [robj(depth + 1, ext) for _ in range(rlen())]
    if r < 17:
        return tuple(robj(depth + 1, ext) for _ in range(rlen()))
    if r < 21:
        return {rkey(): robj(depth + 1, ext) for _ in range(rlen())}
    if r == 21:
        return MyInt(rint() & 0xFFFF)
    if r == 22:
        return rstr()  # str subclasses: see check_str_subclass()
    if r == 23:
        return MyList([robj(depth + 1, ext) for _ in range(rlen())])
    if r == 24:
        return MyTuple(robj(depth + 1, ext) for _ in range(rlen()))
    if r == 25:
        return MyDict({rkey(): robj(depth + 1, ext) for _ in range(rlen())})
    if r == 26 and OrderedDict:
        return OrderedDict([(rstr()[:5], robj(depth + 1, ext)) for _ in range(rlen())])
    if r == 27 and NT:
        return NT(robj(depth + 1, ext), robj(depth + 1, ext))
    if r == 28:
        return Point(random.getrandbits(16), -random.getrandbits(16)) if ext else rint()
    if r == 29:
        return complex(rfloat(), rfloat()) if ext else rstr()
    if r == 30:
        return {rint() & 0xFF for _ in range(rlen())}  # set: ext only
    return random.choice([NoPackb(), memoryview(b"x"), object(), rstr])  # unsupported


def canon(o):
    """A comparable form of an unpacked object: types, float bits, dict as set."""
    t = type(o).__name__
    if isinstance(o, float):
        return ("float", struct.pack(">d", o))
    if isinstance(o, complex):
        return ("complex", struct.pack(">dd", o.real, o.imag))
    if isinstance(o, (list, tuple)):
        return (t, tuple(canon(x) for x in o))
    if isinstance(o, dict):
        items = [(canon(k), canon(v)) for k, v in o.items()]
        if t != "OrderedDict":
            items.sort(key=repr)
        return (t, tuple(items))
    if isinstance(o, set):
        return ("set", tuple(sorted((canon(x) for x in o), key=repr)))
    if isinstance(o, Point):
        return ("Point", o.x, o.y)
    return (t, o)


def canon_outcome(res):
    return (res[0], canon(res[1])) if res[0] == "ok" else res


# --- pack --------------------------------------------------------------------

PACK_OPTS = [{}, {}, {"force_float_precision": "single"}, {"force_float_precision": "double"}]


def check_pack(obj, opts):
    global checks
    a = outcome(msgpackc.dumps, obj, **opts)
    b = outcome(umsgpack.dumps, obj, **opts)
    checks += 1
    if not same(a, b):
        report("dumps %r" % opts, obj, a, b)
    return b[1] if b[0] == "ok" else None


def check_dump(obj):
    global checks
    fa, fb = io.BytesIO(), io.BytesIO()
    a = outcome(msgpackc.dump, obj, fa)
    b = outcome(umsgpack.dump, obj, fb)
    checks += 1
    if a[0] != b[0] or (a[0] == "ok" and fa.getvalue() != fb.getvalue()) or a[1:] != b[1:]:
        report("dump", obj, (a, fa.getvalue()), (b, fb.getvalue()))


# --- unpack ------------------------------------------------------------------

LOAD_OPTS = [{}, {"use_tuple": True}, {"use_ordered_dict": True}, {"allow_invalid_utf8": True}]


def check_unpack(data):
    global checks
    opts = random.choice(LOAD_OPTS)
    a = canon_outcome(outcome(msgpackc.loads, data, **opts))
    b = canon_outcome(outcome(umsgpack.loads, data, **opts))
    checks += 1
    if not same(a, b):
        report("loads %r" % opts, data, a, b)
    if random.getrandbits(3) == 0:
        a = canon_outcome(outcome(msgpackc.load, io.BytesIO(data), **opts))
        checks += 1
        if not same(a, b):
            report("load %r" % opts, data, a, b)


def mutate(data):
    data = bytearray(data)
    for _ in range(random.getrandbits(2) + 1):
        r = random.getrandbits(2)
        if not data:
            data.append(random.getrandbits(8))
        elif r == 0:
            data[random.getrandbits(16) % len(data)] = random.getrandbits(8)
        elif r == 1:
            data = data[: random.getrandbits(16) % len(data)]
        elif r == 2:
            i = random.getrandbits(16) % len(data)
            data[i:i] = bytes([random.choice([0xC1, 0xDD, 0xDF, 0xDB, 0xC6, 0xC9, 0xFF])])
        else:
            data[random.getrandbits(16) % len(data)] ^= 1 << random.getrandbits(3)
    return bytes(data)


def run_phase(ext):
    corpus = []
    for i in range(N_PACK):
        obj = robj(0, ext)
        packed = check_pack(obj, random.choice(PACK_OPTS))
        if i % 16 == 0:
            check_dump(obj)
        if packed is not None and len(corpus) < 300:
            corpus.append(packed)
    for i in range(N_UNPACK):
        r = random.getrandbits(2)
        if r == 0 or not corpus:
            data = bytes(random.getrandbits(8) for _ in range(random.getrandbits(4)))
        elif r == 1:
            data = random.choice(corpus)
        else:
            data = mutate(random.choice(corpus))
        check_unpack(data)


def check_str_subclass():
    # umsgpack cannot pack str subclasses on MicroPython (bytes(sub, "utf-8")
    # raises TypeError there); msgpackc packs them as their str value.
    global checks
    for _ in range(N_PACK // 20):
        s = rstr()
        checks += 1
        if msgpackc.dumps(MyStr(s)) != umsgpack.dumps(s):
            report("dumps str subclass", s, msgpackc.dumps(MyStr(s)), umsgpack.dumps(s))


def register_ext():
    for mod in (msgpackc, umsgpack):
        mod.ext_serializable(0x10)(Point)

        @mod.ext_serializable(0x50, complex)
        class Complex:
            @staticmethod
            def packb(obj, options):
                return struct.pack(">dd", obj.real, obj.imag)

            @staticmethod
            def unpackb(data, options):
                return complex(*struct.unpack(">dd", data))

        def make_set(mod):
            @mod.ext_serializable(0x51, set)
            class Set:
                @staticmethod
                def packb(s, options):
                    return mod.dumps(sorted(s))

                @staticmethod
                def unpackb(data, options):
                    return set(mod.loads(data))

        make_set(mod)


def check_registration_errors():
    global checks
    for args in ((0x10,), (200,), (-129,), ("x",)):
        a = outcome(lambda: msgpackc.ext_serializable(*args)(type("A", (), {})))
        b = outcome(lambda: umsgpack.ext_serializable(*args)(type("A", (), {})))
        checks += 1
        if a[0] != b[0] or a[1] != b[1]:
            report("ext_serializable %r" % (args,), args, a, b)


run_phase(False)
check_str_subclass()
register_ext()
check_registration_errors()
run_phase(True)

if fails:
    for k, n in kinds.items():
        print("  %5d x %s: msgpackc %s, umsgpack %s" % (n, k[0], k[1], k[2]))
    print("RESULT: FAIL", fails, "mismatches in", checks, "checks")
else:
    print("RESULT: OK", checks, "checks (%d MemoryError/OverflowError avoided)" % improved)
