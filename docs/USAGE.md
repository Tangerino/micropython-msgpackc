# Using msgpackc

`msgpackc` is a [MessagePack](https://msgpack.org) serializer for MicroPython,
written in C. Its API is the one of Peter Hinch's
[umsgpack](https://github.com/peterhinch/micropython-msgpack), which is itself
the API of the `json` module: if you know one of them, you already know
`msgpackc`.

- [1. Quick tour](#1-quick-tour)
- [2. Supported types](#2-supported-types)
- [3. Functions](#3-functions)
- [4. Options](#4-options)
- [5. Exceptions](#5-exceptions)
- [6. Extension types](#6-extension-types)
- [7. Streams and incremental decoding](#7-streams-and-incremental-decoding)
- [8. Asynchronous decoding (ALoader)](#8-asynchronous-decoding-aloader)
- [9. Moving from umsgpack](#9-moving-from-umsgpack)
- [10. Differences from umsgpack](#10-differences-from-umsgpack)
- [11. Limits and safety](#11-limits-and-safety)
- [12. Build-time configuration](#12-build-time-configuration)

## 1. Quick tour

```python
import msgpackc

data = msgpackc.dumps({"id": "sensor-01", "temp": 21.5, "ok": True, "raw": b"\x01\x02"})
print(len(data))                # 36 bytes on a board (40 where floats are doubles)
                                # the same record in JSON takes 60
obj = msgpackc.loads(data)      # {'id': 'sensor-01', 'temp': 21.5, ...}
```

Send `data` over MQTT, UART, a socket or store it in a file: it is plain
`bytes`, readable by any MessagePack library in any language (Python's
`msgpack`, JavaScript's `@msgpack/msgpack`, Go, Rust, C...).

## 2. Supported types

| Python | MessagePack | Notes |
|---|---|---|
| `None` | nil | |
| `bool` | true / false | |
| `int` | int / uint, 8 to 64 bits | from `-2**63` to `2**64 - 1`; the smallest encoding is used |
| `float` | float 32 or float 64 | see `force_float_precision` |
| `str` | str | UTF-8 |
| `bytes`, `bytearray` | bin | both unpack as `bytes` |
| `list`, `tuple` | array | both unpack as `list` (or `tuple`, see `use_tuple`) |
| `dict`, `OrderedDict` | map | unpack as `dict` (or `OrderedDict`, see `use_ordered_dict`) |
| anything else | ext | with an [extension type](#6-extension-types) |

Subclasses of these types (and `namedtuple`) are packed like their base type.

Any other object (a `set`, a `complex`, your own class...) raises
`UnsupportedTypeException`, unless you register an extension type for it.

## 3. Functions

### `msgpackc.dumps(obj, **options) -> bytes`

Pack `obj` and return the bytes.

### `msgpackc.dump(obj, fp, **options)`

Pack `obj` and write it to `fp`: any stream (a file, `io.BytesIO`, a socket,
a UART) or any object with a `write(data)` method. The whole object is
written with a single `write()`: if packing fails, nothing is written.

### `msgpackc.loads(data, **options) -> object`

Unpack one object from `data`: `bytes`, `bytearray` or `memoryview` (a
`memoryview` avoids copying part of a larger buffer). Bytes after the end of
the first object are ignored.

### `msgpackc.load(fp, **options) -> object`

Unpack one object from `fp`: any stream, or any object with a `read(n)`
method. It reads exactly the bytes of one object, so you can call it again to
read the next one:

```python
import io, msgpackc

f = io.BytesIO()
for reading in ({"t": 20.5}, {"t": 20.7}, {"t": 21.0}):
    msgpackc.dump(reading, f)
f.seek(0)
print(msgpackc.load(f), msgpackc.load(f), msgpackc.load(f))
```

### `msgpackc.Unpacker(**options)`

Incremental decoder for data that arrives in pieces: see
[section 7](#7-streams-and-incremental-decoding).

### `msgpackc.ext_serializable(ext_type, example=None)`

Class decorator that registers an extension type: see
[section 6](#6-extension-types).

### `msgpackc.ALoader(stream, **options)`

Asynchronous decoder for an `asyncio.StreamReader`: see
[section 8](#8-asynchronous-decoding-aloader).

### Constants

- `msgpackc.float_precision`: `"single"` or `"double"`, the precision of the
  floats of this MicroPython build (most boards: `"single"`).
- `msgpackc.__version__`: the version of the module, e.g. `"1.0.0"`.
- `msgpackc.custom`, `msgpackc.builtins`, `msgpackc.packers`: the registered
  extension types (as in umsgpack; for inspection).

## 4. Options

Options are keyword arguments. Unknown options are accepted and passed on to
the extension types (as umsgpack does).

### Pack options (`dumps`, `dump`)

| option | values | default |
|---|---|---|
| `force_float_precision` | `"single"`: floats as float 32 (5 bytes); `"double"`: as float 64 (9 bytes) | `msgpackc.float_precision` |

On a board with single precision floats there is nothing to gain from
`"double"`. On a computer, `"single"` saves 4 bytes per float.

### Unpack options (`loads`, `load`, `Unpacker`, `ALoader`)

| option | effect | default |
|---|---|---|
| `use_tuple=True` | arrays unpack as `tuple` instead of `list` | `False` |
| `use_ordered_dict=True` | maps unpack as `collections.OrderedDict`, keeping the order of the data | `False` |
| `allow_invalid_utf8=True` | a str that is not valid UTF-8 unpacks as `bytes` instead of raising | `False` |

`Unpacker` also takes `max_buffer_size` (see below), and `ALoader` takes
`observer`.

## 5. Exceptions

The same classes as umsgpack, available as `msgpackc.<name>`:

```
Exception
 ├── PackException
 │    └── UnsupportedTypeException   an object cannot be packed (also: an
 │                                   unknown ext type when unpacking)
 └── UnpackException
      ├── InsufficientDataException  the data ends before the object does
      ├── InvalidStringException     a str that is not valid UTF-8
      ├── ReservedCodeException      the reserved byte 0xc1
      ├── UnhashableKeyException     a map key that cannot be a dict key
      └── DuplicateKeyException      the same key twice in a map
```

Other exceptions you may see: `TypeError` (wrong argument types),
`ValueError` (an invalid `force_float_precision`, a full `Unpacker`),
`RuntimeError` (nesting deeper than the limit, or a container modified by an
extension type while it is being packed), `OSError` (stream errors) and
`NotImplementedError` (an extension class without `packb`/`unpackb`).

Catch `msgpackc.UnpackException` to handle all errors caused by bad data:

```python
try:
    msg = msgpackc.loads(payload)
except msgpackc.UnpackException as e:
    print("corrupt message:", repr(e))
```

## 6. Extension types

MessagePack can carry application-defined types, each identified by a number
from -128 to 127 (negative numbers are reserved by the MessagePack spec; -1
is the timestamp type). The data of an extension is any `bytes` you choose.

### Your own classes

Decorate the class with `ext_serializable(number)` and give it a `packb()`
method returning `bytes` and a static `unpackb(data, options)` method:

```python
import struct
import msgpackc

@msgpackc.ext_serializable(0x10)
class Point3d:
    def __init__(self, x, y, z):
        self.v = (float(x), float(y), float(z))

    def packb(self):
        return struct.pack(">fff", *self.v)

    @staticmethod
    def unpackb(data, options):
        return Point3d(*struct.unpack(">fff", data))

data = msgpackc.dumps([Point3d(1, 2, 3), "label"])
print(msgpackc.loads(data))     # [<Point3d object at ...>, 'label']
```

Subclasses of a registered class are packed with its type number.

### Built-in types

Give the type as second argument; `packb` is then a static method that
receives the object and the pack options:

```python
@msgpackc.ext_serializable(0x51, set)
class Set:
    @staticmethod
    def packb(obj, options):
        return msgpackc.dumps(list(obj))

    @staticmethod
    def unpackb(data, options):
        return set(msgpackc.loads(data))

print(msgpackc.loads(msgpackc.dumps({1, 2, 3})))   # {1, 2, 3}
```

A registered built-in type has priority over the native encoding, so you can
for example make tuples come back as tuples (register `tuple`).

The numbers 0x50 to 0x5F are used by umsgpack's extension modules
(`complex` 0x50, `set` 0x51, `tuple` 0x52, `bytearray` 0x53, `OrderedDict`
0x54): use the same numbers to stay compatible with them.

Registrations last until the next soft reset.

## 7. Streams and incremental decoding

Data that arrives in arbitrary pieces (UART, BLE, a socket) does not contain
whole messages per read. `Unpacker` buffers what you feed it and returns the
objects as soon as they are complete:

```python
import msgpackc
from machine import UART

uart = UART(1, 115200)
unpacker = msgpackc.Unpacker(max_buffer_size=4096)

while True:
    data = uart.read()
    if data:
        unpacker.feed(data)
        for msg in unpacker:      # every complete object, then stops
            handle(msg)
```

| method | |
|---|---|
| `feed(data)` | append bytes (any buffer) |
| iteration / `next(unpacker)` | the next complete object; iteration stops when none is complete yet |
| `next_raw()` | the bytes of the next complete object without decoding it, or `None` |
| `reset()` | discard all buffered data |
| `len(unpacker)` | bytes buffered and not consumed yet |

- `max_buffer_size=n` makes `feed()` raise `ValueError` rather than buffer
  more than `n` bytes: a corrupt length cannot make the buffer grow without
  limit. The default, 0, means no limit.
- An object that fails to decode (for example an invalid string) raises its
  exception and is skipped; the reserved byte 0xc1 raises
  `ReservedCodeException` and is skipped. Decoding goes on with the next
  object, so a stream can recover from noise.
- Completeness is checked without decoding and without allocating, so
  feeding byte by byte costs little.

## 8. Asynchronous decoding (ALoader)

```python
import asyncio
import msgpackc
from machine import UART

async def receiver():
    uart = UART(1, 115200)
    async for msg in msgpackc.ALoader(asyncio.StreamReader(uart)):
        print("received", msg)

asyncio.run(receiver())
```

- `await loader.load()` returns the next object; at the end of the stream it
  raises `EOFError`. `async for` stops at the end of the stream, unless the
  stream ends inside an object (then `EOFError` is raised).
- `observer=callable`: called with the raw bytes of each object, then with
  `b""`, before the object is returned (for example to compute a CRC).
- ALoader is Python code (`python/msgpackc_aio.py`), imported on first use
  of `msgpackc.ALoader`. The firmware built by this project includes it. If
  you build your own firmware, freeze `python/msgpackc_aio.py` or copy it to
  the board (see [INSTALL.md](INSTALL.md#7-the-python-helpers)).

Packing needs nothing special: `writer.write(msgpackc.dumps(obj))`, then
`await writer.drain()`.

## 9. Moving from umsgpack

`msgpackc` has the same functions, options, exceptions, decorator and output
bytes as umsgpack. Two ways to switch:

1. Change the import: `import msgpackc as umsgpack`.
2. Keep `import umsgpack` everywhere: copy the compatibility package
   `python/umsgpack/` to the board (`/lib/umsgpack/__init__.py`). It forwards
   everything to `msgpackc`. umsgpack's extension modules (`mpk_complex.py`,
   `mpk_set.py`, `mpk_tuple.py`, `mpk_bytearray.py`, `mpk_odict.py`) work
   unchanged: copy the ones you use from
   [umsgpack's repository](https://github.com/peterhinch/micropython-msgpack/tree/master/umsgpack)
   into the same directory.

Data packed by one module unpacks with the other: the formats are the same.

## 10. Differences from umsgpack

Measured by the differential test, which runs both modules on the same random
objects and data (see [TESTING.md](TESTING.md)). Everything not listed here
gives the same bytes, the same objects or the same exception and message.

| | umsgpack | msgpackc |
|---|---|---|
| corrupt length (e.g. a str "of 3 GB" in 10 bytes) | `MemoryError` (allocates the length first), or `OverflowError` on 32-bit ports | `InsufficientDataException` |
| `str` subclass | `TypeError` on MicroPython | packed as its `str` value |
| `loads(memoryview)` | `TypeError` | accepted |
| order of the keys of an unpacked `dict` | insertion into an empty dict | the dict is presized; the order may differ (MicroPython dicts are unordered; use `use_ordered_dict`) |
| `dump()` when packing fails | part of the data may already be written | nothing is written |
| nesting | limited by the Python stack | limited to 32 levels, `RuntimeError` beyond |
| a container changed by an ext `packb` while being packed | wrong data | `RuntimeError` |
| `Unpacker` | - | incremental decoder |
| `ALoader` | reads with `readexactly` | reads chunks into an `Unpacker`; the observer gets each object's bytes in one call |

## 11. Limits and safety

`msgpackc` is meant to decode data from the network, so bad data must never
crash the board:

- every length read from the data is checked against the data available
  before anything is allocated or read;
- nesting is limited to 32 levels (packing and unpacking), and on ports with
  stack checking the C stack is checked at every level;
- strings are validated as UTF-8 (as `str()` does);
- if Python code run by an extension type modifies the data being packed or
  unpacked, the change is detected instead of reading freed memory;
- the module keeps no static state: a soft reset leaves nothing behind.

All of this is exercised by the tests, including on an AddressSanitizer and
UndefinedBehaviorSanitizer build.

## 12. Build-time configuration

| macro | default | |
|---|---|---|
| `MSGPACKC_MAX_DEPTH` | 32 | maximum nesting of arrays and maps |
| `MSGPACKC_REUSE_QSTR` | 1 | 1: a map key that already exists as a qstr is reused instead of copied; 0: always copy |

About `MSGPACKC_REUSE_QSTR`: the keys of the messages an application handles
are usually written in its code as literals (`msg["temp"]`), so they exist as
qstrs, and reusing them saves an allocation per key. Only map keys are looked
up: other strings rarely are qstrs, and a lookup that fails costs more than
the copy.

Set it in your board's `mpconfigboard.h`, or in the compiler flags
(`CFLAGS_EXTRA=-DMSGPACKC_MAX_DEPTH=64` for the unix port). Each level takes
80 to 128 bytes of C stack on an ESP32; the MicroPython task has 16 KiB.
