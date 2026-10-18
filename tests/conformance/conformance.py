# Conformance with the msgpack-test-suite (https://github.com/kawanet/msgpack-test-suite),
# the cross-language test vectors of MessagePack. For each case:
#   - every accepted encoding must unpack to the expected value;
#   - packing the value must give one of the accepted encodings.
#
#   micropython conformance.py [path/to/msgpack-test-suite.json]
#
# The timestamp extension (type -1) is not built in (as in umsgpack): its
# cases are checked through a user-registered ext class, like any ext type.

import json
import sys
from binascii import hexlify, unhexlify

import msgpackc

if "SUITE_JSON" in globals():
    # tools/test-device.sh prepends the suite to this script for the boards
    suite = json.loads(SUITE_JSON)  # noqa: F821
else:
    path = "msgpack-test-suite.json"
    for a in sys.argv[1:]:
        if a.endswith(".json"):
            path = a
    with open(path) as f:
        suite = json.load(f)


class Ext:
    """Any ext type: kept as (type, data)."""

    def __init__(self, code, data):
        self.code = code
        self.data = data

    def __eq__(self, other):
        return isinstance(other, Ext) and (self.code, self.data) == (other.code, other.data)

    def __repr__(self):
        return "Ext(%d, %r)" % (self.code, self.data)


def ext_class(code):
    # one registered class per ext type found in the suite
    def packb(self):
        return self.data

    def unpackb(data, options):
        return Ext(code, data)

    cls = type("Ext%d" % (code & 0xFF), (Ext,), {"packb": packb, "unpackb": staticmethod(unpackb)})
    msgpackc.ext_serializable(code)(cls)
    return cls


ext_classes = {}


def make_ext(code, data):
    if code not in ext_classes:
        ext_classes[code] = ext_class(code)
    return ext_classes[code](code, data)


def value(case):
    if "nil" in case:
        return None
    if "bool" in case:
        return case["bool"]
    if "binary" in case:
        return unhexlify(case["binary"].replace("-", ""))
    if "bignum" in case:
        return int(case["bignum"])
    if "number" in case:
        return case["number"]
    if "string" in case:
        return case["string"]
    if "array" in case:
        return case["array"]
    if "map" in case:
        return case["map"]
    if "timestamp" in case:
        sec, nsec = case["timestamp"]
        return ("timestamp", sec, nsec)
    if "ext" in case:
        code, data = case["ext"]
        return make_ext(code, unhexlify(data.replace("-", "")))
    raise ValueError("unknown case %r" % case)


def timestamp_bytes(sec, nsec):
    # the three timestamp encodings of the spec
    if nsec == 0 and 0 <= sec < 2**32:
        return sec.to_bytes(4, "big")
    if 0 <= sec < 2**34:
        return ((nsec << 34) | sec).to_bytes(8, "big")
    return nsec.to_bytes(4, "big") + (sec & (2**64 - 1)).to_bytes(8, "big")


def equal(a, b):
    if isinstance(b, float) or isinstance(a, float):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False
        if msgpackc.float_precision == "single":
            return abs(a - b) <= abs(b) * 1e-6
        return a == b
    if isinstance(b, (list, tuple)):
        return (
            isinstance(a, (list, tuple))
            and len(a) == len(b)
            and all(equal(x, y) for x, y in zip(a, b))
        )
    if isinstance(b, dict):
        return (
            isinstance(a, dict)
            and len(a) == len(b)
            and all(k in a and equal(a[k], v) for k, v in b.items())
        )
    if isinstance(a, Ext) or isinstance(b, Ext):
        return a == b
    return type(a) is type(b) and a == b


checks = 0
fails = 0
for group in sorted(suite):
    for case in suite[group]:
        expected = value(case)
        if isinstance(expected, tuple) and expected[0] == "timestamp":
            expected = make_ext(-1, timestamp_bytes(expected[1], expected[2]))
        encodings = [unhexlify(h.replace("-", "")) for h in case["msgpack"]]
        for enc in encodings:
            checks += 1
            try:
                got = msgpackc.loads(enc)
            except Exception as e:
                got = e
            if not equal(got, expected):
                fails += 1
                print("FAIL unpack", group, hexlify(enc), repr(got), repr(expected))
        checks += 1
        try:
            packed = msgpackc.dumps(expected)
        except Exception as e:
            packed = e
        if packed not in encodings:
            # a float that the port stores in single precision may also be
            # packed as a single while the suite lists only doubles
            fails += 1
            print("FAIL pack", group, repr(expected), packed, case["msgpack"])

if fails:
    print("RESULT: FAIL", fails, "of", checks, "checks")
else:
    print("RESULT: OK", checks, "checks")
