# Exceptions: hierarchy, types and messages (the same as umsgpack's).
try:
    import msgpackc
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc
print(issubclass(m.UnsupportedTypeException, m.PackException))
for e in (
    m.InsufficientDataException,
    m.InvalidStringException,
    m.ReservedCodeException,
    m.UnhashableKeyException,
    m.DuplicateKeyException,
):
    print(e.__name__, issubclass(e, m.UnpackException), issubclass(e, Exception))


def show(f, *args, **kw):
    try:
        print("returned", f(*args, **kw))
    except Exception as e:
        print(type(e).__name__, e)


# packing
show(m.dumps, {1, 2})
show(m.dumps, object())
show(m.dumps, memoryview(b"x"))
show(m.dumps, [1, 2, {3: complex(1, 2)}])
show(m.dumps, 2**64)
show(m.dumps, -(2**63) - 1)
show(m.dumps, 1.5, force_float_precision="half")
show(m.dumps, 1, force_float_precision="half")  # only an error if a float is packed
show(m.dumps)
show(m.dumps, 1, 2)

# unpacking
show(m.loads, b"")
show(m.loads, b"\x92\x01")
show(m.loads, b"\xa5abc")
show(m.loads, b"\xcd\x01")
show(m.loads, b"\xc1")
show(m.loads, b"\x91\xc1")
show(m.loads, b"\xa2\xff\xfe")
show(m.loads, b"\x82\xa1a\x01\xa1a\x02")
show(m.loads, b"\x82\x01\x01\x01\x02")
show(m.loads, b"\x81\x80\x01")
show(m.loads, b"\x81\x91\x80\x01")
show(m.loads, b"\xd4\x7f\x00")
show(m.loads, b"\xd4\x80\x00")
show(m.loads, "abc")
show(m.loads, 123)
show(m.loads, None)

# a huge declared length is detected without allocating it
show(m.loads, b"\xdb\xff\xff\xff\xff")
show(m.loads, b"\xc6\xff\xff\xff\xff")
show(m.loads, b"\xdd\xff\xff\xff\xff\x01")
show(m.loads, b"\xdf\xff\xff\xff\xff\x01\x01")

# an ext type number far out of range (checked when the decorator is applied)
try:
    m.ext_serializable(2**70)(type("Huge", (), {}))
except ValueError as e:
    print("ValueError", e)

# catching the base classes
try:
    m.loads(b"\xc1")
except m.UnpackException:
    print("caught as UnpackException")
try:
    m.dumps(set())
except m.PackException:
    print("caught as PackException")
