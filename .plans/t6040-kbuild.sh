#!/usr/bin/env bash
# T6040 kernel build harness (runs INSIDE the arm64 Linux build container).
# The mac host FS is case-insensitive, which corrupts kernel files (xt_CONNMARK.h
# vs xt_mark.h etc.), so we clone locally onto the container's case-sensitive FS
# (git objects are fine; only the mac working-tree checkout is corrupt), then copy
# in our uncommitted t6040 DT files.
#
#   /src : host ~/code/linux bind-mounted read-only (source of the clone + DT files)
#   /out : host artifacts dir bind-mounted read-write (Image + dtb land here)
#   /build : container-local (case-sensitive, fast)
set -euo pipefail

BRANCH=feature/m4-m5-minimal-device-trees
APPLE=arch/arm64/boot/dts/apple

echo "== deps =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq build-essential bc bison flex libssl-dev libelf-dev \
    python3 cpio kmod git >/dev/null

if [ ! -d /build/linux/.git ]; then
    echo "== clone (case-correct checkout) =="
    git clone --local --shared /src /build/linux
fi
cd /build/linux
git checkout -q "$BRANCH"

echo "== copy in our t6040 DT files (uncommitted on host) =="
cp /src/$APPLE/t6040.dtsi        $APPLE/
cp /src/$APPLE/t6040-j614s.dts   $APPLE/
cp /src/$APPLE/t6040-pmgr.dtsi   $APPLE/
cp /src/$APPLE/Makefile          $APPLE/

echo "== apply flokli's t6040 CODE patches (aic locked-sysreg skip + idle=nop) =="
# CRITICAL: the build checks out COMMITTED code and only copies in DT files, so any
# uncommitted code edits on the host (e.g. the irq-apple-aic.c hyp-mode sysreg
# comment-out) are NOT in the build. Apply flokli's proven t6040 bring-up code
# patches here so they actually land. Patch disables BOTH the
# SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2 and SYS_ICH_HCR_EL2 writes in aic_init_cpu (they
# trap on M4 raw-boot) and adds a working arm64 idle=[wfi|nop] param.
if git apply --check /out/flokli-code.patch 2>/dev/null; then
    git apply /out/flokli-code.patch
    echo "flokli-code.patch applied OK"
else
    echo "ERROR: flokli-code.patch does not apply cleanly to this tree:"
    git apply --check /out/flokli-code.patch || true
    echo "-- current aic_init_cpu hyp block (adapt the patch to match) --"
    sed -n '/EL2-only (VHE mode)/,/PMC FIQ/p' drivers/irqchip/irq-apple-aic.c
    exit 1
fi
echo "-- verify the two traps are gone from aic_init_cpu --"
if sed -n '/static int aic_init_cpu/,/PMC FIQ/p' drivers/irqchip/irq-apple-aic.c | grep -qE "^\s*sysreg_clear_set_s\(SYS_(IMP_APL_VM_TMR_FIQ_ENA|ICH_HCR)_EL2"; then
    echo "WARN: a locked-sysreg write is still active in aic_init_cpu!"
else
    echo "aic_init_cpu locked-sysreg writes disabled OK"
fi

echo "== verify netfilter case-collision is healed in the clone =="
git status --short include/uapi/linux/netfilter/xt_mark.h || true

echo "== config (arm64 defconfig enables CONFIG_ARCH_APPLE) =="
make ARCH=arm64 defconfig >/dev/null
grep -q "CONFIG_ARCH_APPLE=y" .config && echo "ARCH_APPLE=y OK" || echo "WARN: ARCH_APPLE not set"

echo "== force on-screen framebuffer console (the only working kernel console on"
echo "   M4 raw-boot: no serial earlycon, no hv relay). Read output on the laptop"
echo "   display. Mirrors mischa85's t6041 baremetal boot-to-userspace recipe. =="
# simpledrm binds /chosen/framebuffer (m1n1 fills it in), FBDEV_EMULATION gives it
# an fbdev, and FRAMEBUFFER_CONSOLE (fbcon) renders printk onto that fbdev. Without
# all three you get the m1n1 logo and no text (defconfig ships DRM=m, simpledrm off).
# ARM64_SME must be OFF on M4 (chaos_princess/StanfordAppliedCyber: SME breaks M4 boot).
./scripts/config --file .config \
    -e DRM -e DRM_SIMPLEDRM -e DRM_FBDEV_EMULATION \
    -e FB -e VT -e VT_CONSOLE \
    -e FRAMEBUFFER_CONSOLE -e FRAMEBUFFER_CONSOLE_DETECT_PRIMARY \
    -e LOGO \
    -d ARM64_SME
make ARCH=arm64 olddefconfig >/dev/null
echo "-- resulting fbcon-relevant config --"
grep -E "CONFIG_(DRM_SIMPLEDRM|DRM_FBDEV_EMULATION|FRAMEBUFFER_CONSOLE|ARM64_SME)=" .config || true
grep -qE "CONFIG_ARM64_SME=y" .config && echo "WARN: SME still enabled!" || echo "SME disabled OK"

NPROC=$(nproc)
echo "== build DTB first (validates our DT in the real kbuild) =="
make ARCH=arm64 -j"$NPROC" apple/t6040-j614s.dtb
cp $APPLE/t6040-j614s.dtb /out/ && echo "DTB -> /out/t6040-j614s.dtb"

if [ "${1:-}" = "image" ]; then
    echo "== build kernel Image (slow) =="
    make ARCH=arm64 -j"$NPROC" Image
    cp arch/arm64/boot/Image /out/ && echo "Image -> /out/Image ($(du -h arch/arm64/boot/Image | cut -f1))"
    # System.map lets t6040-ramdump.py locate __log_buf for a post-mortem console
    # dump when the framebuffer stays blank (hang before simpledrm probes).
    cp System.map /out/ && echo "System.map -> /out/System.map"
fi
echo "== done =="
