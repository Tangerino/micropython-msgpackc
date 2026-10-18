# Unpacking: every format of the spec (including encodings msgpackc never
# produces, such as non-minimal ints), the load options and the input types.
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

from binascii import unhexlify


def check(hexdata, expected, **opts):
    data = unhexlify(hexdata.replace(" ", ""))
    try:
        got = msgpackc.loads(data, **opts)
    except Exception as e:
        got = "%s(%s)" % (type(e).__name__, e)
    if type(got) is type(expected) and got == expected:
        print("ok", hexdata[:24])
    else:
        print("FAIL", hexdata[:24], "got", repr(got)[:60], "expected", repr(expected)[:60])


check("c0", None)
check("c2", False)
check("c3", True)

# all int encodings, also the non-minimal ones other packers produce
check("00", 0)
check("7f", 127)
check("ff", -1)
check("e0", -32)
check("cc 00", 0)
check("cc ff", 255)
check("cd ffff", 65535)
check("ce ffffffff", 4294967295)
check("cf ffffffffffffffff", 18446744073709551615)
check("cf 0000000000000001", 1)
check("d0 80", -128)
check("d0 7f", 127)
check("d1 8000", -32768)
check("d2 80000000", -2147483648)
check("d3 8000000000000000", -9223372036854775808)
check("d3 0000000000000005", 5)

# floats: 1.5 and -2.0 are exact in both precisions
check("ca 3fc00000", 1.5)
check("cb c000000000000000", -2.0)
print(
    msgpackc.loads(b"\xca\x7f\x80\x00\x00"),
    msgpackc.loads(b"\xcb\xff\xf0\x00\x00\x00\x00\x00\x00"),
)
nan = msgpackc.loads(b"\xcb\x7f\xf8\x00\x00\x00\x00\x00\x00")
print(nan != nan)

# str and bin, all length widths
check("a0", "")
check("a3 616263", "abc")
check("d9 03 616263", "abc")
check("da 0003 616263", "abc")
check("db 00000003 616263", "abc")
check("a2 c3a9", "é")
check("a4 f09f9880", "\U0001f600")
check("c4 00", b"")
check("c4 02 00ff", b"\x00\xff")
check("c5 0002 00ff", b"\x00\xff")
check("c6 00000002 00ff", b"\x00\xff")

# arrays and maps, all length widths
check("90", [])
check("93 010203", [1, 2, 3])
check("dc 0002 0102", [1, 2])
check("dd 00000002 0102", [1, 2])
check("80", {})
check("81 a161 01", {"a": 1})
check("de 0001 a161 01", {"a": 1})
check("df 00000001 a161 01", {"a": 1})
check("82 01 c0 a162 92 c2 c3", {1: None, "b": [False, True]})

# options
check("92 01 92 02 03", (1, (2, 3)), use_tuple=True)
check("92 01 92 02 03", [1, [2, 3]])
check("a2 fffe", b"\xff\xfe", allow_invalid_utf8=True)
try:
    from collections import OrderedDict

    od = msgpackc.loads(b"\x83\xa1c\x01\xa1a\x02\xa1b\x03", use_ordered_dict=True)
    print(type(od).__name__, list(od.keys()))
except ImportError:
    print("OrderedDict ['c', 'a', 'b']")

# a list used as a map key becomes a (nested) tuple
print(msgpackc.loads(b"\x81\x92\x01\x91\x02\xa1v"))

# the input may be bytes, bytearray or memoryview; trailing data is ignored
print(msgpackc.loads(bytearray(b"\x92\x01\x02")))
print(msgpackc.loads(memoryview(b"\x00\x92\x01\x02")[1:]))
print(msgpackc.loads(b"\x01\x02\x03"))

# map keys that already exist as qstrs are shared, not copied (same object
# in two messages); values are always new strings
k1 = list(msgpackc.loads(b"\x81\xa4keys\x01"))[0]
k2 = list(msgpackc.loads(b"\x81\xa4keys\x02"))[0]
print(k1 == "keys", type(k1) is str, k1 is k2)
v1 = msgpackc.loads(b"\xa4keys")
print(v1 == "keys", type(v1) is str)

# round trip of a typical telemetry record
rec = {
    "ts": 1729243200,
    "id": "sensor-01",
    "t": -12.5,
    "ok": True,
    "raw": b"\x01\x02",
    "v": [1, 2],
}
print(msgpackc.loads(msgpackc.dumps(rec)) == rec)
