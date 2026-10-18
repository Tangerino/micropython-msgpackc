# umsgpack compatibility package for msgpackc.
#
# Part of msgpackc. MIT License, Copyright (c) 2026 Carlos Tangerino.
#
# Code written for Peter Hinch's umsgpack
# (https://github.com/peterhinch/micropython-msgpack) runs unchanged on the C
# module: `import umsgpack` now gets msgpackc. The extension modules of
# umsgpack (mpk_complex.py, mpk_set.py, mpk_tuple.py, mpk_bytearray.py,
# mpk_odict.py) also work: copy the ones you need from the umsgpack/ directory
# of that repository into this directory.

from msgpackc import *  # noqa: F403  dumps, loads, ext_serializable, exceptions...
from msgpackc import float_precision  # noqa: F401  used by mpk_complex.py

__version__ = (0, 2, 1)  # the umsgpack API version this package provides


def __getattr__(attr):
    # custom, builtins, packers and ALoader are provided lazily by msgpackc.
    import msgpackc

    return getattr(msgpackc, attr)
