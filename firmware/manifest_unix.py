# Unix port with msgpackc: the port's usual frozen modules plus msgpackc_aio.py,
# so that msgpackc.ALoader works as it does on the boards.
include("$(PORT_DIR)/variants/manifest.py")
module("msgpackc_aio.py", base_path="../python")
