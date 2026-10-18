# Ext types: the ext_serializable decorator, user classes and built-in types,
# every ext header size, and the registry dicts.
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

import struct

m = msgpackc


@m.ext_serializable(0x10)
class Blob:
    def __init__(self, data):
        self.data = data

    def packb(self):
        return self.data

    @staticmethod
    def unpackb(data, options):
        return Blob(data)


# fixext 1/2/4/8/16, then ext 8/16 around the boundaries (ext 32 is in
# msgpackc_large.py)
for n in (0, 1, 2, 3, 4, 8, 15, 16, 17, 255, 256, 300):
    p = m.dumps(Blob(bytes(i % 256 for i in range(n))))
    q = m.loads(p)
    print(n, p[:4], len(p), type(q).__name__, len(q.data))

# negative ext type
print(m.dumps(m.ext_serializable(-5)(type("Neg", (), {"packb": lambda self: b"\x01"}))()))


class Base:
    def __init__(self, x):
        self.x = x

    def packb(self):
        return struct.pack(">h", self.x)

    @classmethod
    def unpackb(cls, data, options):
        return cls(struct.unpack(">h", data)[0])


m.ext_serializable(0x11)(Base)


class Derived(Base):
    pass


p = m.dumps(Derived(-3))
print(p, type(m.loads(p)).__name__, m.loads(p).x)


# a built-in type, with the dumps options passed to packb
@m.ext_serializable(0x50, complex)
class Complex:
    @staticmethod
    def packb(obj, options):
        fmt = ">ff" if options.get("force_float_precision") == "single" else ">dd"
        return struct.pack(fmt, obj.real, obj.imag)

    @staticmethod
    def unpackb(data, options):
        return complex(*struct.unpack(">ff" if len(data) == 8 else ">dd", data))


print(m.loads(m.dumps([1, 2 + 3j])))
print(
    len(m.dumps(1j, force_float_precision="single")),
    len(m.dumps(1j, force_float_precision="double")),
)


# a built-in ext type has priority over the native encoding (umsgpack's
# mpk_tuple trick); its packb may call dumps recursively
@m.ext_serializable(0x52, tuple)
class Tuple:
    @staticmethod
    def packb(obj, options):
        return m.dumps(list(obj))

    @staticmethod
    def unpackb(data, options):
        return tuple(m.loads(data))


print(m.dumps((1, 2)), m.loads(m.dumps([(1, 2), [3]])))

# the options given to loads reach unpackb
seen = []


@m.ext_serializable(0x12)
class Opt:
    def packb(self):
        return b""

    @staticmethod
    def unpackb(data, options):
        seen.append(sorted(options.items()))
        return None


m.loads(m.dumps(Opt()), use_tuple=True, custom_option=7)
print(seen)

# the registry
print(sorted(m.packers.keys()))
print(m.custom[Blob], m.builtins[complex][1])


# errors
def show(f, *args):
    try:
        print("returned", f(*args))
    except Exception as e:
        print(type(e).__name__, e)


show(lambda: m.ext_serializable(0x10)(type("Again", (), {})))
show(lambda: m.ext_serializable(0x13)(Blob))
show(lambda: m.ext_serializable(128)(type("Big", (), {})))
show(lambda: m.ext_serializable(-129)(type("Small", (), {})))
show(lambda: m.ext_serializable("1")(type("Str", (), {})))


@m.ext_serializable(0x14)
class NoMethods:
    pass


show(m.dumps, NoMethods())
show(m.loads, b"\xd4\x14\x00")


@m.ext_serializable(0x53, bytearray)
class NoPackb:
    pass


show(m.dumps, bytearray(b"x"))
show(m.loads, b"\xd4\x15\x00")
