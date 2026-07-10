#!/usr/bin/env bash
# Boot the t6040 kernel AND capture the kernel serial console independently.
#
# Why: linux.py raises UartTimeout at kboot_boot (the handoff kills the …YG1 proxy
# before the reply) *before* it reaches iface.ttymode(), so it never relays the
# kernel's own console on …YG3. So we run a standalone …YG3 capture in parallel.
#
# Usage: power-cycle the M4 first (proxy must be alive), then run this.
set -uo pipefail
M1=/dev/cu.usbmodemJ22GYCN4YG1
DBG=/dev/cu.usbmodemJ22GYCN4YG3
OUT=/Users/damsleth/Code/linux-build-out
LOG=$OUT/kernel-console.log
cd /Users/damsleth/Code/m1n1

echo "== chainload fresh m1n1 (brings up the USB gadgets incl …YG3) =="
M1N1DEVICE=$M1 timeout 60 python3 proxyclient/tools/chainload.py -r build/m1n1.bin 2>&1 | grep -iE "Running proxy" | head

echo "== start …YG3 capture (background, 150s, retry-open) -> $LOG =="
: > "$LOG"
timeout 160 python3 -c '
import serial,sys,time
dev="'"$DBG"'"; log="'"$LOG"'"
s=None
for _ in range(40):
    try:
        s=serial.Serial(dev,1500000,timeout=2); break
    except Exception: time.sleep(0.25)
if s is None:
    open(log,"a").write("[capture: could not open %s]\n"%dev); sys.exit(0)
f=open(log,"ab",buffering=0); t0=time.time()
while time.time()-t0 < 150:
    try: d=s.read(256)
    except Exception: time.sleep(0.25); continue
    if d: f.write(d)
' &
CAP=$!
sleep 2

echo "== boot kernel (linux.py will raise at handoff; that is expected) =="
M1N1DEVICE=$M1 timeout 90 python3 proxyclient/tools/linux.py \
  "$OUT/Image" "$OUT/t6040-j614s.dtb" --compression none \
  -b "earlycon console=ttySAC0,1500000 maxcpus=1 idle=nop" 2>&1 | tail -8 || true

echo "== waiting for capture to drain =="
wait $CAP 2>/dev/null || true
echo "== kernel console (…YG3) tail =="
tail -60 "$LOG"
echo "== ($(wc -c < "$LOG") bytes captured to $LOG) =="
