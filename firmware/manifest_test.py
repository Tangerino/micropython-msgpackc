# Test and benchmark firmware for msgpackc. It differs from manifest.py in:
#
#  - _boot.py mounts a small RAM filesystem at "/" instead of the flash
#    filesystem. The firmware never reads or writes the flash data partitions,
#    so it can be tried on a board whose flash holds another application:
#    that application's files stay intact and its boot.py/main.py do not run.
#  - Peter Hinch's umsgpack is frozen in, as the reference for the
#    differential tests and the benchmarks.
#
# Only for testing: a normal application wants manifest.py.

# The port's manifest (ports/esp32/boards/manifest.py), minus its _boot.py.
freeze(
    "$(PORT_DIR)/modules", ("apa106.py", "espnow.py", "flashbdev.py", "inisetup.py", "machine.py")
)
include("$(MPY_DIR)/extmod/asyncio")
require("bundle-networking")
require("aioespnow")
require("dht")
require("ds18x20")
require("neopixel")
require("onewire")
require("umqtt.robust")
require("umqtt.simple")
require("upysh")

module("_boot.py", base_path="testboot")
module("msgpackc_aio.py", base_path="../python")
package("umsgpack", base_path="../third_party/micropython-msgpack")
