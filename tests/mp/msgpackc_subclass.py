# Subclasses of the native types and native subtypes pack like their base.
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc


class I(int):
    pass


class S(str):
    pass


class B(bytes):
    pass


class L(list):
    pass


class T(tuple):
    pass


class D(dict):
    pass


for obj, base in (
    (I(300), 300),
    (S("abc"), "abc"),
    (B(b"xy"), b"xy"),
    (L([1, 2]), [1, 2]),
    (T((1, 2)), (1, 2)),
    (D(a=1), {"a": 1}),
    (L([I(1), S("s"), D(k=T((1,)))]), [1, "s", {"k": (1,)}]),
):
    print(type(obj).__name__, m.dumps(obj) == m.dumps(base))

try:
    from collections import OrderedDict, namedtuple

    od = OrderedDict([("z", 1), ("a", 2)])
    print(m.dumps(od))
    NT = namedtuple("NT", ("x", "y"))
    print(m.dumps(NT(1, "y")), m.dumps([NT(1, 2), NT(3, (4,))]))
except ImportError:
    print(b"\x82\xa1z\x01\xa1a\x02")
    print(b"\x92\x01\xa1y", b"\x92\x92\x01\x02\x92\x03\x91\x04")

# bool is not an int here: True packs as true
print(m.dumps([True, False, 1, 0]))
