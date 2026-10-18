#!/usr/bin/env python3
"""Read the partition table of an ESP32 flash image (or of a board).

  partitions.py app IMAGE.bin    print "offset size" of the application
                                 partition (factory, else ota_0)
  partitions.py show IMAGE.bin   print the whole table

The table is at 0x8000 on every ESP32 chip (the default
CONFIG_PARTITION_TABLE_OFFSET). Entries: 32 bytes, magic 0xAA50.
"""

import struct
import sys

TABLE_OFFSET = 0x8000


def parse(blob):
    parts = []
    for i in range(0, 0xC00, 32):
        entry = blob[i : i + 32]
        if entry[:2] != b"\xaa\x50":
            break
        _, ptype, subtype, offset, size, label, _flags = struct.unpack("<HBBII16sI", entry)
        parts.append((label.rstrip(b"\0").decode(), ptype, subtype, offset, size))
    return parts


def read_table(image):
    with open(image, "rb") as f:
        f.seek(TABLE_OFFSET)
        return parse(f.read(0xC00))


def app_partition(parts):
    apps = [p for p in parts if p[1] == 0]  # type 0: app
    for want in (0x00, 0x10):  # factory, then ota_0
        for p in apps:
            if p[2] == want:
                return p
    raise SystemExit("no application partition in the table")


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("app", "show"):
        raise SystemExit(__doc__)
    parts = read_table(sys.argv[2])
    if not parts:
        raise SystemExit("no partition table at 0x8000")
    if sys.argv[1] == "app":
        p = app_partition(parts)
        print(p[3], p[4])
    else:
        for label, ptype, subtype, offset, size in parts:
            kind = "app" if ptype == 0 else "data"
            print(f"{label:16} {kind:4} 0x{subtype:02x} 0x{offset:06x} {size // 1024:6d} KiB")


if __name__ == "__main__":
    main()
