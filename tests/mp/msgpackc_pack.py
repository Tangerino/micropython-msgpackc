# Packing: every format family of the MessagePack spec, at every size boundary.
# Expected bytes come from https://github.com/msgpack/msgpack/blob/master/spec.md
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

from binascii import unhexlify


def check(obj, hexpected, **opts):
    expected = unhexlify(hexpected.replace(" ", ""))
    try:
        got = msgpackc.dumps(obj, **opts)
    except Exception as e:
        got = "%s(%s)" % (type(e).__name__, e)
    if got == expected:
        print("ok", repr(obj)[:40])
    else:
        print("FAIL", repr(obj)[:40], "got", got, "expected", expected)


# nil, bool
check(None, "c0")
check(False, "c2")
check(True, "c3")

# positive fixint, uint 8/16/32/64
check(0, "00")
check(1, "01")
check(0x7F, "7f")
check(0x80, "cc 80")
check(0xFF, "cc ff")
check(0x100, "cd 0100")
check(0xFFFF, "cd ffff")
check(0x10000, "ce 00010000")
check(0x7FFFFFFF, "ce 7fffffff")
check(0x80000000, "ce 80000000")
check(0xFFFFFFFF, "ce ffffffff")
check(0x100000000, "cf 0000000100000000")
check(0x7FFFFFFFFFFFFFFF, "cf 7fffffffffffffff")
check(0x8000000000000000, "cf 8000000000000000")
check(0xFFFFFFFFFFFFFFFF, "cf ffffffffffffffff")

# negative fixint, int 8/16/32/64
check(-1, "ff")
check(-32, "e0")
check(-33, "d0 df")
check(-128, "d0 80")
check(-129, "d1 ff7f")
check(-32768, "d1 8000")
check(-32769, "d2 ffff7fff")
check(-(2**31), "d2 80000000")
check(-(2**31) - 1, "d3 ffffffff7fffffff")
check(-(2**63), "d3 8000000000000000")

# float 32/64, explicit precision (the default is the port's float)
check(1.5, "cb 3ff8000000000000", force_float_precision="double")
check(1.5, "ca 3fc00000", force_float_precision="single")
check(-0.0, "cb 8000000000000000", force_float_precision="double")
check(float("inf"), "ca 7f800000", force_float_precision="single")
check(float("-inf"), "cb fff0000000000000", force_float_precision="double")
print(msgpackc.float_precision in ("single", "double"))
print(msgpackc.dumps(0.5) == msgpackc.dumps(0.5, force_float_precision=msgpackc.float_precision))

# str: fixstr, str 8/16 (str 32 is in msgpackc_large.py)
check("", "a0")
check("a", "a1 61")
check("a" * 31, "bf" + "61" * 31)
check("a" * 32, "d9 20" + "61" * 32)
check("a" * 255, "d9 ff" + "61" * 255)
check("a" * 256, "da 0100" + "61" * 256)
# the length counts UTF-8 bytes, not characters
check("é", "a2 c3a9")
check("€", "a3 e282ac")
check("\U0001f600", "a4 f09f9880")
check("é" * 16, "d9 20" + "c3a9" * 16)

# bin 8/16 (bin 32 is in msgpackc_large.py); bytearray packs as bin too
check(b"", "c4 00")
check(b"\x00\xff", "c4 02 00ff")
check(b"x" * 255, "c4 ff" + "78" * 255)
check(b"x" * 256, "c5 0100" + "78" * 256)
check(bytearray(b"\x01\x02"), "c4 02 0102")

# array: fixarray, array 16 (array 32 is in msgpackc_large.py); tuple packs as array
check([], "90")
check([1, 2, 3], "93 010203")
check((1, 2, 3), "93 010203")
check([0] * 15, "9f" + "00" * 15)
check([0] * 16, "dc 0010" + "00" * 16)

# map: fixmap, map 16 (map 32 is in msgpackc_large.py)
check({}, "80")
check({"a": 1}, "81 a161 01")
check({1: None}, "81 01 c0")
d15 = {i: i for i in range(15)}
print(msgpackc.dumps(d15)[0] == 0x8F, len(msgpackc.dumps(d15)))
d16 = {i: i for i in range(16)}
print(msgpackc.dumps(d16)[:3] == b"\xde\x00\x10", len(msgpackc.dumps(d16)))

# nesting
check([1, [2, [3, {}]]], "92 01 92 02 92 03 80")
check({"k": [True, None, {"x": b"\x00"}]}, "81 a16b 93 c3 c0 81 a178 c40100")

# the README example of umsgpack: 41 bytes
obj = [1, True, False, 0xFFFFFFFF, {"foo": b"\x80\x01\x02", "bar": [1, 2, 3, {"a": [1, 2, 3, {}]}]}, -1, 2.12345]  # fmt: skip
print(len(msgpackc.dumps(obj, force_float_precision="single")))

# dump writes the same bytes to a stream
import io

f = io.BytesIO()
msgpackc.dump({"a": [1, 2]}, f)
print(f.getvalue() == msgpackc.dumps({"a": [1, 2]}))
