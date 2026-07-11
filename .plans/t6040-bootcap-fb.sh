#!/usr/bin/env bash
# Boot the t6040 kernel and read the console ON THE LAPTOP'S OWN SCREEN.
#
# WHY this replaces t6040-bootcap.sh's serial approach:
#   On M4 raw-kboot there is NO working kernel serial console:
#     - earlycon=s5l / console=ttySAC0 : the s5l UART is dead on M4 (confirmed by
#       enverbalalic on the sibling t6041 - "dockchannel is the only way to get logs").
#     - the ...YG3 capture : YG3 is m1n1's USB *vuart*, which is only driven by the
#       hypervisor. In raw kboot no m1n1 code runs after handoff, so YG3 is silent.
#     - m1n1 hv relay : impossible on M4 (SPTM blocks the hypervisor).
#   The de-facto console for M4 bring-up is the on-screen FRAMEBUFFER console
#   (simpledrm + fbcon). mischa85 booted t6041 to userspace this way. When fbcon
#   registers (after simpledrm probes) it replays the whole dmesg to the display,
#   so you see the entire boot log up to wherever it dies. READ THE SCREEN / photo.
#
# REQUIRES a kernel built with the fbcon config from t6040-kbuild.sh
# (DRM_SIMPLEDRM + DRM_FBDEV_EMULATION + FRAMEBUFFER_CONSOLE, ARM64_SME off).
#
# Cmdline notes:
#   nohlt                 : CRITICAL. M4 loses CPU state on WFI/WFE; without this
#                           the boot CPU dies on its first idle (before simpledrm)
#                           -> logo, no text. (Asahi kernel honors nohlt on arm64.)
#                           Fallbacks if it still dies early: idle=poll, cpuidle.off=1.
#   maxcpus=1             : only the boot P-core; avoids secondary WFE parking.
#   pd_ignore_unused clk_ignore_unused : mischa85's t6041 recipe; don't gate off
#                           power domains/clocks we haven't modelled yet.
#   console=tty0          : route printk to the VT (fbcon) = the screen.
#   ignore_loglevel       : print everything, so we see the last line before a hang.
#
# The m1n1 build chainloaded here arms the watchdog for ~20s on M4 (see
# src/kboot.c / src/wdt.c): a hung kernel auto-warm-resets back to "Running proxy"
# (DRAM retained), so you don't have to power-cycle by hand to retry.
set -uo pipefail
M1=/dev/cu.usbmodemJ22GYCN4YG1
OUT=/Users/damsleth/Code/linux-build-out
cd /Users/damsleth/Code/m1n1

# Optional arg 1: DTB filename in $OUT (default our full j614s DT). Use
# "t6040-j614s-min.dtb" to boot flokli's MINIMAL DT with the same kernel Image,
# to isolate whether our fuller DT causes an early driver hang.
DTB="${1:-t6040-j614s.dtb}"
echo "== using DTB: $DTB =="

# Optional arg 2: initramfs filename in $OUT (e.g. "initramfs.cpio.gz"). With one,
# the kernel gets a real rootfs and runs /init instead of panicking at VFS root
# mount. NOTE: no keyboard driver in the minimal DT yet, so /init runs a scripted
# proof-of-userspace (banner + uname + cpuinfo) rather than an interactive shell.
INITRAMFS="${2:-}"
RDINIT=""
if [ -n "$INITRAMFS" ]; then
  echo "== using initramfs: $INITRAMFS =="
  RDINIT=" rdinit=/init"
fi

# idle=nop is now FUNCTIONAL: flokli's idle.c patch (applied in t6040-kbuild.sh)
# adds the arm64 idle= early_param and skips wfi()/wfit() when idle=nop, avoiding
# the M4 WFI-state-loss. (Plain mainline ignores idle= on arm64, and nohlt too.)
CMDLINE="maxcpus=1 idle=nop nokaslr pd_ignore_unused clk_ignore_unused console=tty0 ignore_loglevel"

echo "== chainload fresh m1n1 (dapf gate + watchdog auto-reset) =="
M1N1DEVICE=$M1 timeout 60 python3 proxyclient/tools/chainload.py -r build/m1n1.bin 2>&1 \
    | grep -iE "Running proxy" | head

echo
echo "===================================================================="
echo " WATCH THE LAPTOP SCREEN NOW. Console output renders there (fbcon),"
echo " not over USB. When simpledrm probes, the full dmesg flushes to the"
echo " display. If it hangs, the watchdog warm-resets in ~20s -> 'Running"
echo " proxy'; note the LAST line visible before the freeze."
echo " cmdline: $CMDLINE"
echo "===================================================================="
echo

echo "== boot kernel (linux.py raises UartTimeout at handoff; that is expected) =="
BOOTLOG="$OUT/linuxpy-boot.log"
M1N1DEVICE=$M1 timeout 90 python3 proxyclient/tools/linux.py \
    "$OUT/Image" "$OUT/$DTB" ${INITRAMFS:+"$OUT/$INITRAMFS"} --compression none \
    -b "$CMDLINE$RDINIT" 2>&1 | tee "$BOOTLOG" | tail -12 || true

# Persist Kernel_base for the RAM-dump fallback (t6040-ramdump.py needs it).
KBASE=$(grep -oiE "Kernel_base: 0x[0-9a-f]+" "$BOOTLOG" | grep -oiE "0x[0-9a-f]+" | tail -1)
echo "${KBASE:-}" > "$OUT/kernel_base.txt"

echo
echo "== handoff done. Watch the laptop screen. =="
if [ -n "${KBASE:-}" ]; then
  echo "   Kernel_base = $KBASE  (saved to $OUT/kernel_base.txt)"
  echo "   If the screen stayed blank, wait for the watchdog to warm-reset to"
  echo "   'Running proxy' (~20s), then dump the kernel log from RAM:"
  echo "     M1N1DEVICE=$M1 python3 .plans/t6040-ramdump.py $KBASE"
else
  echo "   WARN: could not parse Kernel_base from linux.py output ($BOOTLOG)."
fi
