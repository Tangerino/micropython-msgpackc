# Integers at the 64-bit limits, on builds with arbitrary precision ints and on
# builds limited to 64 bits (MICROPY_LONGINT_IMPL_LONGLONG), where a uint64
# above 2**63 - 1 cannot be represented and unpacks with OverflowError.
# No literal here exceeds 63 bits, so the file compiles on both.
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

# Does this build have ints wider than 64 bits? (On a longlong build int() of
# a larger number may silently overflow instead of raising.)
try:
    BIG = str(int("18446744073709551616")) == "18446744073709551616"
except (OverflowError, ValueError):
    BIG = False

m = msgpackc
INT64_MAX = 0x7FFFFFFFFFFFFFFF
INT64_MIN = -INT64_MAX - 1

for v in (INT64_MAX, INT64_MIN, 2**62, -(2**62), 2**32, -(2**32) - 1):
    p = m.dumps(v)
    print(p[0] in (0xCF, 0xD3), m.loads(p) == v)

print(m.dumps(INT64_MAX) == b"\xcf\x7f\xff\xff\xff\xff\xff\xff\xff")
print(m.dumps(INT64_MIN) == b"\xd3\x80\x00\x00\x00\x00\x00\x00\x00")

# a uint64 above INT64_MAX
try:
    v = m.loads(b"\xcf\xff\xff\xff\xff\xff\xff\xff\xff")
    print("uint64 max:", BIG and str(v) == "18446744073709551615")
except OverflowError:
    print("uint64 max:", not BIG)
