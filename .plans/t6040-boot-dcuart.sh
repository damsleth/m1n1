#!/usr/bin/env bash
# Boot the t6040 kernel ENTIRELY over the DebugUSB (KIS) pty — no plain-cable
# tether, no screen-reading. Requires an attached kisd session (run
# .plans/t6040-debugusb-console.sh first; /tmp/m1n1 -> kisd pty).
#
# Flow:
#   1. chainload fresh m1n1 over the pty (proxy protocol)
#   2. linux.py uploads Image+DTB+initramfs and hands off
#   3. immediately attach a raw reader to the SAME pty: after handoff the
#      kernel's apple_dockchannel_tty owns the AP FIFO, so the pty carries
#      the Linux banner + a busybox shell (t6040-init-dcuart spawns it).
#
# After this script prints the banner, interact with:
#   printf 'uname -a\n' > /tmp/m1n1          # type into the shell
#   tail -f "$OUT/dcuart-console.log"        # watch output
# or attach interactively: screen /tmp/m1n1
#
# On a hung kernel the m1n1 watchdog warm-resets in ~20s; DebugUSB mode may
# need re-entering: sudo -n /usr/local/bin/macvdmtool debugusb
set -uo pipefail
M1=${M1N1DEVICE:-/tmp/m1n1}
OUT=/Users/damsleth/Code/linux-build-out
cd /Users/damsleth/Code/m1n1

PY=/Users/damsleth/Code/m1n1/venv/bin/python
[ -x "$PY" ] || PY=python3

DTB="${1:-t6040-j614s-dcuart.dtb}"
INITRAMFS="${2:-initramfs-dcuart.cpio.gz}"
IMAGE="${IMAGE:-Image}"
echo "== DTB: $DTB  kernel: $IMAGE  initramfs: $INITRAMFS  dev: $M1 =="

KERNEL_LOG_ARGS="${KERNEL_LOG_ARGS:-ignore_loglevel}"
CMDLINE="maxcpus=1 idle=nop nokaslr pd_ignore_unused clk_ignore_unused console=tty0 fbcon=font:TER16x32 $KERNEL_LOG_ARGS${EXTRA_BOOTARGS:+ $EXTRA_BOOTARGS} rdinit=/init"

echo "== chainload fresh m1n1 over $M1 =="
M1N1DEVICE=$M1 timeout 180 "$PY" proxyclient/tools/chainload.py -r build/m1n1.bin 2>&1 \
    | grep -iE "Running proxy|TTY|Signature" | head

echo "== upload kernel + hand off (UartTimeout at handoff is expected) =="
BOOTLOG="$OUT/dcuart-boot.log"
M1N1DEVICE=$M1 timeout 300 "$PY" proxyclient/tools/linux.py \
    "$OUT/$IMAGE" "$OUT/$DTB" "$OUT/$INITRAMFS" --compression none \
    -b "$CMDLINE" 2>&1 | tee "$BOOTLOG" | tail -8 || true

echo "== handoff done; attaching raw console reader to $M1 =="
CONLOG="$OUT/dcuart-console.log"
: > "$CONLOG"
# stty raw so the pty passes bytes through untranslated
stty -f "$M1" raw -echo 2>/dev/null || true
( exec cat "$M1" >> "$CONLOG" ) &
CATPID=$!
echo "console reader pid $CATPID -> $CONLOG"
echo "== first 30s of Linux dockchannel output =="
sleep 30
tail -40 "$CONLOG"
echo
echo "== reader still running. Interact: printf 'cmd\\n' > $M1 ; tail -f $CONLOG =="
