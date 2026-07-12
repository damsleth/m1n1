# For each candidate DVEn serial payload: enter serial mode on the target's
# hpm0 ACE (via SPMI over the USB proxy), write a marker to the dockchannel
# UART, and watch /dev/cu.debug-console on the host for it.
# Usage: M1N1DEVICE=<usb proxy> python sbu_matrix.py 1810306 1810306,800c0000 ...

import struct, sys, time
import serial as pyserial

from m1n1.setup import *

VARIANTS = [a for a in sys.argv[1:] if not a.startswith("-")]

# --- SPMI + TPS (same protocol as target_serial_entry.py) ---
STATUS, CMD, REPLY = 0x00, 0x04, 0x08
RX_EMPTY, TX_EMPTY = 1 << 24, 1 << 8

class SPMIBus:
    def __init__(self, u, path):
        self.p = u.proxy
        self.base = u.adt[path].get_reg(0)[0]
    def _st(self):
        return self.p.read32(self.base + STATUS)
    def cmd(self, addr, opc, extra=0, data_in=b"", out_len=0):
        if not (self._st() & TX_EMPTY):
            raise IOError("SPMI TX FIFO not empty")
        while not (self._st() & RX_EMPTY):
            self.p.read32(self.base + REPLY)
        self.p.write32(self.base + CMD, (extra << 16) | (1 << 15) | (addr << 8) | opc)
        for i in range(0, len(data_in), 4):
            blk = (data_in[i:i+4] + b"\0\0\0")[:4]
            self.p.write32(self.base + CMD, struct.unpack("<I", blk)[0])
        for _ in range(1000):
            if not (self._st() & RX_EMPTY):
                break
            time.sleep(0.0005)
        else:
            raise TimeoutError("SPMI RX timeout")
        reply = self.p.read32(self.base + REPLY)
        if (reply & 0xff) != opc or ((reply >> 8) & 0x7f) != addr:
            raise IOError(f"unexpected SPMI reply {reply:#x}")
        out = b""
        while len(out) < out_len:
            if self._st() & RX_EMPTY:
                raise IOError("short reply")
            out += struct.pack("<I", self.p.read32(self.base + REPLY))
        if (reply >> 16) != (1 << out_len) - 1:
            raise IOError(f"frame parity {reply>>16:#x}")
        if out_len == 0 and not (reply & (1 << 15)):
            raise IOError("not acked")
        return out[:out_len]

class TPS:
    def __init__(self, bus, addr):
        self.bus, self.addr = bus, addr
    def _sel(self, reg):
        self.bus.cmd(self.addr, 0x80 | reg, extra=reg << 8)
        for _ in range(200):
            v = self.bus.cmd(self.addr, 0x20, extra=0x00, out_len=1)[0]
            if v == reg:
                return
            if v != (reg | 0x80):
                raise IOError(f"reg select failed: {v:#x}")
            time.sleep(0.001)
        raise TimeoutError("reg select timeout")
    def read(self, reg, n):
        self._sel(reg)
        return self.bus.cmd(self.addr, 0x20 | (n - 1), extra=0x20, out_len=n)
    def write(self, reg, data):
        self._sel(reg)
        self.bus.cmd(self.addr, 0x00 | (len(data) - 1), extra=0x20, data_in=data)
    def command(self, cmd4, data_in=b"", out_len=0):
        if data_in:
            self.write(0x09, data_in)
        self.write(0x08, cmd4)
        for _ in range(2000):
            st = struct.unpack("<I", self.read(0x08, 4))[0]
            if st == 0x444d4321:
                raise IOError(f"cmd {cmd4} invalid")
            if st == 0:
                break
            time.sleep(0.001)
        else:
            raise TimeoutError(f"cmd {cmd4} busy")
        return self.read(0x09, out_len) if out_len else None

bus = SPMIBus(u, "/arm-io/nub-spmi-a0")
t = TPS(bus, 0x0c)  # hpm0 = DFU port, verified connected

key = b"416J"
marker = b"\r\nHELLO_SBU_%04d "

def enter_serial(payload):
    out = t.command(b"LOCK", key, 1)[0]
    if out & 0xf:
        raise IOError(f"LOCK failed {out:#x}")
    t.command(b"DBMa", b"\x01", 1)
    if t.read(0x03, 4) != b"DBMa":
        raise IOError("DBMa entry failed")
    out = t.command(b"DVEn", payload, 1)[0]
    t.command(b"DBMa", b"\x00")
    t.command(b"LOCK", b"\x00\x00\x00\x00")
    return out & 0xf

sbu = pyserial.Serial("/dev/cu.debug-console", 115200, timeout=0.1)
dcbuf = u.malloc(1024)

for i, spec in enumerate(VARIANTS):
    payload = b"".join(struct.pack("<I", int(w, 16)) for w in spec.split(","))
    try:
        res = enter_serial(payload)
    except Exception as e:
        print(f"[{spec}] entry error: {e}")
        continue
    if res:
        print(f"[{spec}] DVEn rejected: {res:#x}")
        continue
    sbu.reset_input_buffer()
    data = (marker % i) * 8
    iface.writemem(dcbuf, data)
    p.iodev_write(1, dcbuf, len(data))
    time.sleep(0.5)
    rx = sbu.read(4096)
    print(f"[{spec}] DVEn OK, host RX {len(rx)} bytes: {rx[:80]!r}")
    if rx:
        print("*** DATA PATH WORKS ***")
        break
