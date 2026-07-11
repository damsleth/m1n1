#!/usr/bin/env python3
# Post-mortem kernel console recovery for M4 raw-kboot, when the on-screen
# framebuffer console (t6040-bootcap-fb.sh) shows nothing because the kernel hung
# BEFORE simpledrm/fbcon came up (very early arch/irq/timer).
#
# How it works:
#   The m1n1 build arms the watchdog before handoff (src/kboot.c on M4). A hung
#   kernel -> watchdog WARM reset -> DRAM is RETAINED -> the M4 lands back on stock
#   m1n1 "Running proxy". DO NOT re-chainload/re-boot (that overwrites DRAM). Just
#   run this against the running proxy: it reads the kernel's printk buffer
#   (__log_buf) straight out of physical RAM and strings it.
#
# Usage (from the m1n1 checkout, after the watchdog reset lands on "Running proxy"):
#   M1N1DEVICE=/dev/cu.usbmodemJ22GYCN4YG1 \
#       python3 proxyclient/tools/../../.plans/t6040-ramdump.py 0x<KERNEL_BASE>
#   where <KERNEL_BASE> is the "Kernel_base: 0x..." that linux.py printed on the
#   boot that hung. System.map is read from the build-out dir.
#
# Caveat: relies on warm-reset DRAM retention AND on stock m1n1's restart not
# clobbering the kernel region (kernel is loaded high, m1n1 lives low, so it
# usually survives). If the strings look like garbage, DRAM did not survive - fall
# back to getting a DP-capable USB-C cable + kisd (debugusb), the only other path.
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxyclient"))

OUT = "/Users/damsleth/Code/linux-build-out"
SYSMAP = os.path.join(OUT, "System.map")
DUMP = os.path.join(OUT, "logbuf.bin")


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


if len(sys.argv) < 2:
    die("usage: t6040-ramdump.py 0x<KERNEL_BASE> [dump_bytes]")

kernel_base = int(sys.argv[1], 0)
dump_len = int(sys.argv[2], 0) if len(sys.argv) > 2 else 1 << 20  # 1 MiB default

if not os.path.exists(SYSMAP):
    die("no System.map at %s (build with t6040-kbuild.sh 'image')" % SYSMAP)

syms = {}
with open(SYSMAP) as f:
    for line in f:
        m = re.match(r"^([0-9a-fA-F]+)\s+\S\s+(\S+)$", line.strip())
        if m:
            syms[m.group(2)] = int(m.group(1), 16)

text = syms.get("_text") or syms.get("_stext")
logbuf = syms.get("__log_buf")
if text is None:
    die("_text/_stext not found in System.map")
if logbuf is None:
    # Fall back to dumping from the image base; strings will still catch the log.
    print("warn: __log_buf not in System.map; dumping from kernel base instead")
    off = 0
else:
    off = logbuf - text

phys = kernel_base + off
print("System.map: _text=0x%x __log_buf=%s -> offset 0x%x" %
      (text, ("0x%x" % logbuf) if logbuf else "n/a", off))
print("reading %d bytes of phys RAM at 0x%x (nokaslr assumed)..." % (dump_len, phys))

# Connect to the *running* m1n1 proxy with the MINIMAL bootstrap: just the
# UartInterface + proxy handshake. Deliberately NOT `from m1n1.setup import *` —
# that also builds ProxyUtils (heap allocs) and pokes the PMU, which we want to
# avoid while reading untouched DRAM.
from m1n1.proxy import UartInterface, M1N1Proxy
from m1n1.proxyutils import bootstrap_port

iface = UartInterface()
p = M1N1Proxy(iface, debug=False)
bootstrap_port(iface, p)

# DRAM-retention check: linux.py wrote the arm64 Image to kernel_base before boot.
# If those bytes survived the watchdog/iBoot reset, DRAM is retained (and empty
# __log_buf means the kernel didn't log). If they're zeros too, iBoot scrubbed
# DRAM on reset and no post-mortem RAM dump can ever work here.
hdr = iface.readmem(kernel_base, 64)
magic = hdr[0x38:0x3C]
nz = sum(1 for b in hdr if b)
print("\n----- DRAM retention check @ kernel_base 0x%x -----" % kernel_base)
print("first 64 bytes: %s" % hdr.hex())
print("arm64 Image magic @0x38: %s (%s)" %
      (magic.hex(), "PRESENT - DRAM retained, kernel just didn't log"
       if magic == b"ARM\x64" else
       "MISSING - %d/64 non-zero" % nz))
print("verdict: %s\n" % ("DRAM RETAINED (fix the kernel hang / find real log buffer)"
                         if magic == b"ARM\x64" or nz > 8 else
                         "DRAM SCRUBBED on reset -> ramdump path is dead, use debugusb"))

data = iface.readmem(phys, dump_len)
with open(DUMP, "wb") as f:
    f.write(data)
print("wrote %d bytes -> %s" % (len(data), DUMP))

# Print readable runs (>=4 printable chars) - the printk records show up as text.
print("\n===== strings(__log_buf) =====")
run = bytearray()
for b in data:
    if 0x20 <= b < 0x7F or b in (0x09,):
        run.append(b)
    else:
        if len(run) >= 4:
            sys.stdout.write(run.decode("ascii", "replace") + "\n")
        run = bytearray()
if len(run) >= 4:
    sys.stdout.write(run.decode("ascii", "replace") + "\n")
