# msgpackc: MessagePack for MicroPython, in C

[msgpackc](https://github.com/Tangerino/micropython-msgpackc) is a MessagePack
serializer for [MicroPython](https://micropython.org), written in C and built
into the firmware. It has the API of Peter Hinch's pure-Python
[umsgpack](https://github.com/peterhinch/micropython-msgpack) and produces
the same bytes, 20 to 120 times faster on an ESP32. Ready-made firmware for
ESP32, ESP32-S3, C3, C6 and P4 is in each
[release](https://github.com/Tangerino/micropython-msgpackc/releases/latest).

```python
import msgpackc

data = msgpackc.dumps({"id": "sensor-01", "temp": 21.5, "raw": b"\x01\x02"})
obj = msgpackc.loads(data)

# incremental decoding, e.g. from a UART
unpacker = msgpackc.Unpacker()
unpacker.feed(data)
for obj in unpacker:
    print(obj)
```
