# Enter SBU serial mode on the t6040 from the TARGET side, via the live m1n1
# proxy: talks to the sn201202x ACE over SPMI (protocol from m1n1 PR #594 /
# src/spmi.c + src/tps6598x.c), issuing the same DVEn action macvdmtool uses.
#
# Usage: M1N1DEVICE=/dev/cu.usbmodemJ22GYCN4YG1 python target_serial_entry.py [--kis] [--no-act]
#   --no-act: probe/report only, don't change ACE state
#   --kis:    use the debugusb action (0x01824606) instead of serial (0x01840306)

import struct, sys, time

from m1n1.setup import *

NO_ACT = "--no-act" in sys.argv
ACTION = 0x01824606 if "--kis" in sys.argv else 0x01840306

# each non-flag argv is one DVEn payload: comma-separated hex words,
# concatenated LE (action word + optional argument words)
PAYLOADS = [b"".join(struct.pack("<I", int(w, 16)) for w in a.split(","))
            for a in sys.argv[1:] if not a.startswith("-")] or None

# ---- SPMI controller access (mirrors src/spmi.c exactly) ----

STATUS, CMD, REPLY = 0x00, 0x04, 0x08
RX_EMPTY, TX_EMPTY = 1 << 24, 1 << 8

class SPMIBus:
    def __init__(self, u, path):
        self.p = u.proxy
        self.base = u.adt[path].get_reg(0)[0]

    def _st(self):
        return self.p.read32(self.base + STATUS)

    def cmd(self, addr, opc, extra=0, data_in=b"", out_len=0):
        assert addr < 16 and out_len <= 16
        if not (self._st() & TX_EMPTY):
            raise IOError("SPMI TX FIFO not empty")
        while not (self._st() & RX_EMPTY):
            print(f"  leftover RX: {self.p.read32(self.base + REPLY):#x}")
        self.p.write32(self.base + CMD,
                       (extra << 16) | (1 << 15) | (addr << 8) | opc)
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
                raise IOError("reply shorter than expected")
            out += struct.pack("<I", self.p.read32(self.base + REPLY))
        if (reply >> 16) != (1 << out_len) - 1:
            raise IOError(f"frame parity {reply >> 16:#x} for len {out_len}")
        if out_len == 0 and not (reply & (1 << 15)):
            raise IOError("command not acked")
        return out[:out_len]

# ---- TPS-over-SPMI register protocol (mirrors PR #594 tps6598x.c) ----

class TPS:
    def __init__(self, bus, addr, name):
        self.bus, self.addr, self.name = bus, addr, name

    def wakeup(self):
        self.bus.cmd(self.addr, 0x13)          # SPMI_OPC_WAKEUP
        time.sleep(0.02)

    def _sel(self, reg):
        assert reg < 0x80
        self.bus.cmd(self.addr, 0x80 | reg, extra=reg << 8)  # reg0 write
        for _ in range(200):
            v = self.bus.cmd(self.addr, 0x20, extra=0x00, out_len=1)[0]
            if v == reg:
                return
            if v != (reg | 0x80):
                raise IOError(f"{self.name}: reg select failed, got {v:#x}")
            time.sleep(0.001)
        raise TimeoutError(f"{self.name}: reg select timeout")

    def read(self, reg, n):
        self._sel(reg)
        return self.bus.cmd(self.addr, 0x20 | (n - 1), extra=0x20, out_len=n)

    def write(self, reg, data):
        self._sel(reg)
        self.bus.cmd(self.addr, 0x00 | (len(data) - 1), extra=0x20,
                     data_in=data)

    def command(self, cmd4, data_in=b"", out_len=0):
        assert len(cmd4) == 4
        if data_in:
            self.write(0x09, data_in)          # DATA1
        self.write(0x08, cmd4)                 # CMD1
        for _ in range(2000):
            st = struct.unpack("<I", self.read(0x08, 4))[0]
            if st == 0x444d4321:               # '!CMD'
                raise IOError(f"{self.name}: cmd {cmd4} invalid")
            if st == 0:
                break
            time.sleep(0.001)
        else:
            raise TimeoutError(f"{self.name}: cmd {cmd4} still busy")
        return self.read(0x09, out_len) if out_len else None

# ---- discover HPMs from the live ADT ----

hpms = []
for buspath in ("/arm-io/nub-spmi-a0", "/arm-io/nub-spmi-a1"):
    try:
        busnode = u.adt[buspath]
    except KeyError:
        continue
    bus = SPMIBus(u, buspath)
    for child in busnode:
        compat = getattr(child, "compatible", None) or []
        if not any("sn201202x" in c for c in compat):
            continue
        raw = child.reg
        slave = raw[0] if isinstance(raw, (bytes, bytearray)) else raw[0].addr
        hpms.append(TPS(bus, int(slave), f"{buspath}/{child.name}"))

print(f"Found {len(hpms)} HPM(s)")

# ---- probe: mode + connection status on each ----

connected = []
for t in hpms:
    try:
        t.wakeup()
        mode = t.read(0x03, 4).decode("ascii", "replace")
        conn = t.read(0x3f, 1)[0]
        state = "none" if not (conn & 1) else ("sink" if conn & 2 else "source")
        print(f"{t.name}: slave={t.addr:#x} mode='{mode}' conn={conn:#04x} ({state})")
        if conn & 1:
            connected.append(t)
    except Exception as e:
        print(f"{t.name}: probe failed: {e}")

if NO_ACT:
    sys.exit(0)

if not connected:
    print("No connected port found — is the cable plugged in?")
    sys.exit(1)
if len(connected) > 1:
    print("NOTE: multiple connected ports; using the first (re-run with edits if wrong)")

t = connected[0]
print(f"\nEntering serial mode via {t.name} (action {ACTION:#010x})")

# unlock key: reversed first 4 bytes of target-type (tps6598x_enter_kis)
target = u.adt.target_type
if isinstance(target, str):
    target = target.encode()
key = bytes(target[:4][::-1])
print(f"target-type={target!r} key={key!r}")

# check LOCK cmd status; m1n1 would Gaid(soft reset) on failure — we DON'T,
# since this ACE drives the port carrying our proxy session. Bail instead.
st = struct.unpack("<I", t.read(0x08, 4))[0]
if st not in (0,):
    print(f"CMD1 status {st:#x} — would need Gaid soft reset; aborting to protect proxy link")
    sys.exit(1)

out = t.command(b"LOCK", key, 1)[0]
if out & 0xf:
    print(f"LOCK failed: result {out:#x}")
    sys.exit(1)
print("Unlocked")

t.command(b"DBMa", b"\x01", 1)
mode = t.read(0x03, 4)
if mode != b"DBMa":
    print(f"Failed to enter DBMa mode: {mode!r}")
    sys.exit(1)
print("DBMa mode entered")

for payload in (PAYLOADS or [struct.pack("<I", ACTION)]):
    words_str = " ".join(f"{struct.unpack('<I', payload[i:i+4])[0]:08x}"
                         for i in range(0, len(payload), 4))
    out = t.command(b"DVEn", payload, 1)[0]
    if out & 0xf:
        print(f"DVEn [{words_str}] failed: result {out:#x}")
    else:
        print(f"DVEn [{words_str}] OK — target end is in serial mode")
        break

t.command(b"DBMa", b"\x00")
t.command(b"LOCK", b"\x00\x00\x00\x00")
print("DBMa exited, ACE re-locked. Done.")
