# Standard firmware with msgpackc: the port's usual frozen modules, plus
# msgpackc_aio.py so that msgpackc.ALoader works out of the box.
# Used with FROZEN_MANIFEST=<this file> (see the top-level Makefile).
include("$(PORT_DIR)/boards/manifest.py")
module("msgpackc_aio.py", base_path="../python")
