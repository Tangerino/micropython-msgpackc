"""Interoperability with msgpack-python, the reference implementation of
MessagePack for CPython: data packed by one side must unpack on the other."""

import math
import random
import struct

import msgpack
import pytest

from conftest import run_mp

# Records are length-prefixed binary (4 bytes, big endian), not text lines:
# reading very long lines is slow on MicroPython.
SCRIPT = """
import sys
import msgpackc
with open(sys.argv[1], "rb") as f, open(sys.argv[2], "wb") as out:
    while True:
        n = f.read(4)
        if not n:
            break
        obj = msgpackc.loads(f.read(int.from_bytes(n, "big")))
        data = msgpackc.dumps(obj)
        out.write(len(data).to_bytes(4, "big"))
        out.write(data)
"""


def write_records(path, blobs):
    path.write_bytes(b"".join(len(b).to_bytes(4, "big") + b for b in blobs))


def read_records(path):
    data, out, i = path.read_bytes(), [], 0
    while i < len(data):
        n = int.from_bytes(data[i : i + 4], "big")
        out.append(data[i + 4 : i + 4 + n])
        i += 4 + n
    return out


def rand_obj(rng, depth=0, single=False):
    r = rng.randrange(14 if depth < 4 else 8)
    if r == 0:
        return rng.choice([None, True, False])
    if r == 1:
        return rng.randrange(-(2**63), 2**64)
    if r == 2:
        return rng.randrange(-200, 200)
    if r == 3:
        x = rng.uniform(-1e6, 1e6)
        return struct.unpack(">f", struct.pack(">f", x))[0] if single else x
    if r == 4:
        n = rng.choice([0, 1, 31, 32, 255, 256, 300, 70000])
        return "".join(rng.choice("aé€😀z") for _ in range(n))
    if r == 5:
        return rng.randbytes(rng.choice([0, 1, 255, 256, 70000]))
    if r == 6:
        return rng.choice([2**63 - 1, -(2**63), 2**64 - 1, 0, -1, -32, -33, 127, 128])
    if r == 7:
        return float(rng.choice(["inf", "-inf"]))
    if r < 11:
        return [rand_obj(rng, depth + 1, single) for _ in range(rng.choice([0, 1, 15, 16, 17]))]
    return {
        rng.choice([str(rng.random()), rng.randrange(-1000, 1000), rng.randbytes(3)]): rand_obj(
            rng, depth + 1, single
        )
        for _ in range(rng.choice([0, 1, 15, 16, 17]))
    }


def same(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return a == b or (math.isnan(a) and math.isnan(b))
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_cpython_msgpack_round_trip(bigint_flavour, quick, seed, tmp_path):
    flavour = bigint_flavour
    """CPython packs, msgpackc unpacks and packs again, CPython unpacks."""
    single = flavour == "float32"
    rng = random.Random(seed)
    objs = [rand_obj(rng, single=single) for _ in range(200 if quick else 2000)]
    src = tmp_path / "in.bin"
    dst = tmp_path / "out.bin"
    write_records(src, [msgpack.packb(o, use_bin_type=True) for o in objs])
    script = tmp_path / "interop.py"
    script.write_text(SCRIPT)
    run_mp(flavour, script, src, dst)
    back = read_records(dst)
    assert len(back) == len(objs)
    for obj, data in zip(objs, back):
        assert same(msgpack.unpackb(data, raw=False, strict_map_key=False), obj), obj


def test_same_bytes_as_msgpack_python(bigint_flavour, tmp_path):
    flavour = bigint_flavour
    """For the same scalar values both choose the same (smallest) encoding."""
    # Python expressions, evaluated on both sides (literals this big do not
    # compile on MicroPython).
    exprs = ["None", "True", "False", "0", "127", "128", "255", "256", "65535", "65536",
             "2**32 - 1", "2**32", "2**64 - 1", "-1", "-32", "-33", "-128", "-129", "-32768",
             "-32769", "-(2**31)", "-(2**31) - 1", "-(2**63)", "''", "'a' * 31", "'a' * 32",
             "'a' * 255", "'a' * 256", "'a' * 65535", "'a' * 65536", "b''", "b'x' * 255",
             "b'x' * 256", "b'x' * 65536", "[]", "[0] * 15", "[0] * 16", "[0] * 65536", "{}",
             "{i: i for i in range(16)}"]  # fmt: skip
    script = tmp_path / "same.py"
    script.write_text(
        "import msgpackc\nfrom binascii import hexlify\n"
        f"for e in {exprs!r}:\n    print(hexlify(msgpackc.dumps(eval(e))).decode())\n"
    )
    values = [eval(e) for e in exprs]
    out = run_mp(flavour, script).split()
    expected = [msgpack.packb(v, use_bin_type=True).hex() for v in values]
    assert out == expected
    # floats: double (or single on float32 ports, like use_single_float)
    single = flavour == "float32"
    script.write_text(
        "import msgpackc\nfrom binascii import hexlify\n"
        "for v in (0.5, -2.25, 1e10, float('inf')):\n"
        "    print(hexlify(msgpackc.dumps(v)).decode())\n"
    )
    out = run_mp(flavour, script).split()
    expected = [
        msgpack.packb(v, use_single_float=single).hex() for v in (0.5, -2.25, 1e10, float("inf"))
    ]
    assert out == expected
