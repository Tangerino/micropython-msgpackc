# _boot.py of the msgpackc test firmware: mount a RAM filesystem at "/".
#
# The flash filesystem is never mounted, so whatever another application
# keeps on this board's flash is not read, not written and not executed.
# Files copied to the board (mpremote cp) live in RAM until the next reset.
import gc
import vfs


class RAMBlockDev:
    def __init__(self, block_size, num_blocks):
        self.block_size = block_size
        self.data = bytearray(block_size * num_blocks)

    def readblocks(self, block_num, buf, offset=0):
        addr = block_num * self.block_size + offset
        buf[:] = memoryview(self.data)[addr : addr + len(buf)]

    def writeblocks(self, block_num, buf, offset=0):
        addr = block_num * self.block_size + offset
        memoryview(self.data)[addr : addr + len(buf)] = buf

    def ioctl(self, op, arg):
        if op == 4:  # block count
            return len(self.data) // self.block_size
        if op == 5:  # block size
            return self.block_size
        if op == 6:  # erase
            return 0


gc.collect()
# 64 KiB with PSRAM, 16 KiB without: the heap is needed for the tests.
_bdev = RAMBlockDev(512, 128 if gc.mem_free() > 1_000_000 else 32)
vfs.VfsLfs2.mkfs(_bdev)
vfs.mount(vfs.VfsLfs2(_bdev), "/")
del _bdev
gc.collect()
