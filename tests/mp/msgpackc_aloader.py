# ALoader: asynchronous decoding from an asyncio StreamReader-like object.
try:
    import msgpackc
    import asyncio
    from msgpackc import ALoader
except ImportError:
    print("SKIP")
    raise SystemExit

m = msgpackc


class FakeReader:
    """Delivers data in small chunks, yielding to the scheduler in between."""

    def __init__(self, data, chunk=3):
        self.data = data
        self.chunk = chunk

    async def read(self, n):
        await asyncio.sleep_ms(0)
        n = min(n, self.chunk)
        out, self.data = self.data[:n], self.data[n:]
        return out


objs = [{"temp": 21.5}, [1, 2, 3], "x" * 100, None]
data = b"".join(m.dumps(o) for o in objs)


async def main():
    out = []
    async for obj in ALoader(FakeReader(data)):
        out.append(obj)
    print(out == objs)

    # load() one by one, with load options
    ld = ALoader(FakeReader(m.dumps([1, [2]]) + m.dumps(5)), use_tuple=True)
    print(await ld.load(), await ld.load())
    try:
        await ld.load()
    except EOFError:
        print("EOFError")

    # the observer gets the raw bytes of each object, then b""
    log = []
    ld = ALoader(FakeReader(data, chunk=5), observer=log.append)
    got = []
    for _ in objs:
        got.append(await ld.load())
    print(got == objs, log[0] == m.dumps(objs[0]), log[1] == b"", len(log))

    # the stream ending inside an object is an error, not the end of iteration
    try:
        async for obj in ALoader(FakeReader(m.dumps([1, 2, 3])[:-1])):
            pass
    except EOFError:
        print("EOFError inside an object")


asyncio.run(main())
