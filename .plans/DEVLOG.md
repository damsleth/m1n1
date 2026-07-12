# t6040 (M4 Pro, Mac16,8 / J614s) Linux bring-up — DEVLOG & operational reference

State of the world, how to operate the rig, solved blockers, investigation
history, and dead ends. Forward-looking work lives in `NEXT_STEPS.md`; the
long-term plan in `roadmap.md`; per-session write-ups in `done/`.

## Current working state (2026-07-12)

| Works | Notes |
|---|---|
| Mainline Linux (7.2-rc2 + 3 small patches) to BusyBox userspace | minimal DT, maxcpus=1, reproducible |
| Two-way m1n1 proxy/console over DebugUSB (KIS) | one DP/TB cable in the DFU port; no second machine-side cable needed |
| Two-way **Linux shell** on `/dev/ttydc0` over the same cable | poll-mode dockchannel driver; full remote dev loop, no screen-reading |
| Internal keyboard (+trackpad registers) at the shell | dockchannel-HID; trackpad events untested |
| Framebuffer console (simpledrm + fbcon) | the early-boot console; dcuart covers post-probe |
| Linux `apple_wdt` takes over m1n1's watchdog | shell survives past the 20 s bite |
| Remote reboot via `macvdmtool` | full autonomous reboot→chainload→boot→shell cycle |

Blocked/active: full-pmgr DT hangs pre-console (see PMGR section). Parked:
USB gadget console (EP0 dies post-enumeration; `done/2026-07-11-t6040-usb-gadget-plan.md`).

## Operating the rig

### The DebugUSB (KIS) link

`bash .plans/scripts/t6040-debugusb-console.sh [reboot]` — starts kisd, enters
DebugUSB via `sudo -n macvdmtool [reboot] debugusb`, symlinks the kisd pty to
`/tmp/m1n1`. `M1N1DEVICE=/tmp/m1n1` for all proxyclient tools; `screen /tmp/m1n1`
for an interactive console. kisd auto-detects the t6040 KIS base 0x548700000;
kisd uart channel 0 = dock side of AP `/arm-io/dockchannel-uart` (AP data block
0x50882c000 + 0x40004000 = 0x548830000; same offset on t8140).

**Hard-won operational rules (skip these and the link "dies"):**
1. **A reader must be attached to the kisd pty at (almost) all times.** With
   nobody reading, ~15 KB of boot output fills the pty buffer, kisd blocks, and
   the KIS stream wedges into an apparently one-way link (writes ACK at the USB
   level, nothing ever returns). Recovery: `pkill kisd`, restart kisd, re-enter
   `sudo -n macvdmtool debugusb`, attach `cat` immediately.
2. **Never leave a `cat` running while a proxyclient tool uses the pty** — it
   steals reply bytes. Sequence: kill reader → run tool → reattach reader.
3. First proxy attempt after a boot often hits `UartCMDError` (desync from
   leftover console bytes) — **just retry once**.
4. Reboot → "Running proxy" takes **<20 s**. Poll every 2–3 s; never wait minutes.
5. DebugUSB replaces m1n1's dwc3 gadget on the DFU port (no `/dev/cu.usbmodem*`
   while active). A plain cable in another target port coexists for fast
   chainload.
6. `t6040-boot-dcuart.sh` runs linux.py with stdin not a tty → miniterm
   traceback AFTER the handoff. Harmless; the kernel is already booting.

Host prerequisites: root-owned `/usr/local/bin/macvdmtool` (patched fork at
`~/Code/macvdmtool`: new cmds `actions`/`vdm`/`dven`/`localserial`) with a
NOPASSWD sudoers entry; `/usr/local/bin/kisd` (AsahiLinux/kisd, builds on macOS
as-is). proxyclient pty support is committed (`proxyclient: support pty devices`).

### Boot recipes

**Linux with the DockChannel shell (the standard loop):** target at m1n1
"Running proxy" with kisd attached →
`bash .plans/scripts/t6040-boot-dcuart.sh` (defaults:
`t6040-j614s-dcuart.dtb` + `initramfs-dcuart.cpio.gz`). Chainloads
`build/m1n1.bin`, uploads over the pty, hands off, attaches a reader. Console
tails to `~/Code/linux-build-out/dcuart-console.log`; type with
`printf 'cmd\n' > /tmp/m1n1`.

**Framebuffer-console variant (for pre-userspace debugging):**
`bash .plans/scripts/t6040-bootcap-fb.sh <dtb> <initramfs>` over a plain-cable
proxy (`/dev/cu.usbmodemJ22GYCN4YG1`). Output on the laptop panel. Cmdline:
`maxcpus=1 idle=nop nokaslr pd_ignore_unused clk_ignore_unused console=tty0
fbcon=font:TER16x32 ignore_loglevel`. `EXTRA_BOOTARGS=initcall_debug` to trace
init hangs. A hung kernel warm-resets in ~20 s (m1n1 arms WD1 before handoff).

**Initramfs:** `bash .plans/scripts/t6040-make-initramfs.sh` (defaults:
INIT_SOURCE=`scripts/t6040-init-dcuart`, DEST=`initramfs-dcuart.cpio.gz`).
The init holds an fd open on ttydc0 for the life of init (the tty driver does
not enjoy full close/reopen cycles), prints a `[dcuart] spawning shell` marker,
respawns `busybox sh -i <>/dev/ttydc0` via setsid, pets `/dev/watchdog0`, and
keeps the fbcon shell as before.

### Kernel build

Native mac builds are impossible (case-insensitive FS corrupts the tree);
everything builds arm64-natively in the podman container `kbuild`
(see memory `t6040-kernel-build-env`). Kernel tree: `~/Code/linux`, branch
`feature/m4-m5-minimal-device-trees` (yuka's remote; mainline 7.2-rc2 + DT
commits). Working build dir inside the container: `/build/linux-keyboard`.

```
cp .plans/scripts/t6040-kbuild.sh .plans/patches/*.patch ~/Code/linux-build-out/
podman exec -e DOCKCHANNEL=1 -e BUILD_DIR=/build/linux-keyboard kbuild \
    bash /out/t6040-kbuild.sh image
```

kbuild.sh clones committed state, copies in the t6040 DT files from `/src`,
applies `/out/flokli-code.patch` (aic locked-sysreg skip + arm64 `idle=` param),
imports the DockChannel series (`origin/dockchannel`: mailbox `d2acb86f70a2`,
tty `b8dcbdcb`, HID transport) with `DOCKCHANNEL=1`, applies
`t6040-dockchannel-fixes.patch` (hid .stop) and `t6040-dockchannel-poll.patch`
(apple,poll-mode), forces the fbcon config, and builds Image + DTBs to `/out`.

- **BUILD GOTCHA:** the build uses COMMITTED kernel code + copies only DT
  files. Uncommitted host code edits are silently dropped — put code changes
  in a patch applied by kbuild.sh.
- `PMGR_FUNCTIONAL=1` additionally applies `t6040-pmgr-functional.patch` for
  the full-pmgr experiments.
- Fast DTB-only rebuild: `podman exec kbuild bash -c 'cd /build/linux-keyboard
  && make ARCH=arm64 apple/<name>.dtb && cp arch/arm64/boot/dts/apple/<name>.dtb /out/'`
  (explicit dtb targets build without a Makefile `dtb-y` entry).
- **zsh gotcha:** unquoted `$var` does not word-split.

DT sources: `t6040.dtsi` / `t6040-j614s*.dts` / `t6040-pmgr.dtsi` in
`~/Code/linux` (partly uncommitted); the dcuart board variant is preserved at
`.plans/dts/t6040-j614s-dcuart.dts` (self-contained: defines the
dockchannel-uart nodes under &soc itself).

Known-good artifacts (in `~/Code/linux-build-out/`), kernel build #11:
- `Image` `3f2eab6dc3c46e0df19e954f026865d3203acb03c73cbe608edb9001f35fd867`
- `t6040-j614s-dcuart.dtb` `f3f595dab17a1e536540ac8c82ed2b25442bfd37491137fdad9ef0190415cde8`
- `initramfs-dcuart.cpio.gz` `512c69da94884f3ea83f9a6a4ea0731dcad6b5aaa87eb875ca5a6d7b24c317ca`

m1n1: `export PATH="$(brew --prefix llvm)/bin:$PATH"; make -j8` →
`build/m1n1.bin`. All t6040 changes are committed on `main`; the curated
code-only series lives on branch `t6040-bringup` (worktree `~/Code/m1n1-clean`).

## Solved blockers

### The 5 original M4 raw-boot blockers (common root: SPTM/firmware-locked resources trap)
1. **m1n1 async L2C SError at kboot handoff** — the dapf init; on t6040 ALL
   dapf entries trap. Fixed in `src/dapf.c` (`dapf_skip_entry()`), refined to
   still allow dart-mtp programming (keyboard needs it).
2. **AIC locked-sysreg trap** — `aic_init_cpu` writes
   `SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2` + `SYS_ICH_HCR_EL2` in hyp mode → traps →
   hang before console. flokli patch comments out both (in `flokli-code.patch`).
3. **WFI state-loss** — M4 loses CPU state on WFI/WFE; flokli patch adds arm64
   `idle=[wfi|nop]`; boot with `idle=nop` (plain mainline ignores `idle=`).
4. **No fbcon in defconfig** — DRM_SIMPLEDRM + DRM_FBDEV_EMULATION +
   FRAMEBUFFER_CONSOLE + ARM64_SME=off, forced by kbuild.sh.
5. **Fuller-DT hang = pmgr** — see PMGR section below; still the active blocker
   for the full DT.

### Internal keyboard (2026-07-11, session 4) — three independent bugs
(a) m1n1 skipped dart-mtp DAPF programming on t6040 (src/dapf.c);
(b) t6040.dtsi ASC mailbox IRQs were pairwise swapped — Apple's ADT lists
not-empty first per pair, the binding wants ascending;
(c) dockchannel-hid lacked hid_ll_driver `.stop` → NULL-deref oops
(`patches/t6040-dockchannel-fixes.patch`). Full story:
`done/2026-07-11-t6040-mtp-wake-findings.md`.

### DockChannel-UART Linux console (2026-07-12)
Kernel side: `origin/dockchannel` mailbox + tty drivers + a t6040 board DT
variant. **The t6040-specific discovery: the ADT-declared AIC irq 360 for the
dockchannel-uart AP FIFO NEVER fires.** Probed live from m1n1: the FIFO irq
block (+0xc000) latches flags and takes mask writes fine, but with all 4096
AIC inputs unmasked, no HW_STATE bit tracks the FIFO mask toggle. Without an
IRQ the stock driver TX-stalls at exactly one 2 KiB FIFO fill (send_data
completes only from the IRQ handler) and RX is dead — the "banner then
silence" signature. Fix: `patches/t6040-dockchannel-poll.patch` adds an
`apple,poll-mode` DT property (5 ms delayed-work poll; TX-done on FIFO-drain,
RX via RX_COUNT). m1n1 and the KIS dock-side agent poll this FIFO too.

Open question (not blocking): where does that irq line actually go —
fused off on the chopped die, routed to AOP, or KIS-agent-only? XNU's
pe_serial dockchannel path may answer (ADT has `enable-sw-drain=1`).

MMIO caution: the dockchannel-uart block maps ONLY +0xc000 (irq, 24 B) and
+0x28000..+0x38004 (config/data). Reading other offsets (e.g. +0x20000) raises
an async SError that kills m1n1 — unlike dockchannel-mtp, which maps
+0x0/+0x14000/+0x28000../+0x30000..

Note: the tty driver registers no printk console — `console=ttydc0` does
nothing yet; the shell + dmesg cover post-userspace, fbcon covers early boot.

### Watchdog (2026-07-11)
Linux `apple_wdt` takes over m1n1's WD1; BusyBox pings `/dev/watchdog0` every
10 s. m1n1 arms WD1 for ~20 s on M4 before handoff (`src/kboot.c`,
`src/wdt.c: wdt_arm_secs`) so hung kernels warm-reset back to "Running proxy".

## PMGR investigation (sessions 2–3, 2026-07-11) — the active blocker's history

The full generated four-controller/214-domain `t6040-pmgr.dtsi` hangs the
kernel pre-console (inside apple-pmgr-pwrstate probe, before simpledrm).
Session 3 got the full DT to userspace with a **functional policy**
(`patches/t6040-pmgr-functional.patch`, build with `PMGR_FUNCTIONAL=1`):
- `apple,preserve-active` per controller (domains found active at probe are
  marked always-on);
- `apple,skip-auto-enable` on the locked dispext0/1 sys/fe/cpu domains;
- five ANE domains disabled (delayed async SError on raw boot);
- `disp_cpu@10000` disabled (first register access traps).

**Session-2 findings, with honest confidence** (all HW results are N=1 blind
pre-console hangs; determinism was never established by re-running a DTB):

| variant | pmgr config | result (N=1) |
|---|---|---|
| `pmgr01` | autogen pmgr0+1 (hierarchical), pmgr2+3 OFF | BOOTS userspace |
| `bis-nocpu` | autogen 0+1+2, pmgr3 OFF, only CPU domains disabled | logo-only |
| `safe2` | autogen, pmgr2 core-infra disabled (orphans children) | −517 defer storm, no userspace |
| `cur-pmgr01` | curated/reparented pmgr0+1, pmgr2+3 OFF | logo-only |
| `curated`/`bis-*` | curated, various pmgr2 subsets off | logo-only |

SOLID (~90–95%): the per-domain pmgr2 bisection was logically invalid (the
intersection of all hung tests' enabled sets came out empty — no single
culprit domain exists, assuming determinism); `pmgr_adt2dt.py` derives
`apple,always-on` from the ADT `critical` flag, which disagrees with yuka's
curated t8132 (over-marks pmc/pms_c1ppt/pms_fpwm0-4, misses aic) — a real
generator bug. PLAUSIBLE-not-isolated (~50–80%): pmgr-present→hang;
"killer is pmgr2 core-infra"; "reparent-to-root is fatal" (confounded);
"safe2's stall was the defer storm". The real obstacle was BLINDNESS —
which the DockChannel console now removes for everything post-userspace
(a pre-console printk poller into the FIFO would close the rest).

Curated-pmgr tooling from session 2 (prune_pmgr.py, bisect_build.sh, variant
dtsi/dts) lived in that session's scratchpad; the method is documented in
`done/`-era NEXT_STEPS history in git if needed.

## Dead ends (do not re-investigate)

- **SBU analog serial on M4/ACE3:** ACE3 advertises action 0x306 but rejects
  every enter attempt (host VDM → BUSY 0x40030004; target-side DVEn via SPMI →
  result 0x3 for pin sets 2/7; pin set 0 accepted but no HW drain to SBU; pin
  set 1 maps UART onto D+/D− and kills the USB proxy). The dockchannel FIFO's
  real consumer is the KIS debug agent → DebugUSB is the supported path.
  Details in `done/2026-07-11-t6040-console-session.md` and memory.
- **No s5l serial console on M4 raw-boot;** the `...YG3` device is m1n1's
  vuart (hv-only → dead after handoff); m1n1 hv is SPTM-blocked entirely.
- **RAM-dump post-mortem:** iBoot scrubs DRAM on watchdog reset (verified:
  bytes read back all-zero). The ramdump script was deleted with the refactor.
- **USB gadget console (PARKED, not dead):** gadget enumerates but EP0 dies
  post-enumeration (raw + glue variants). Revisit for gadget-Ethernet+SSH
  after pmgr. `done/2026-07-11-t6040-usb-gadget-plan.md`. Gotchas recorded in
  memory: the ChatGPT desktop app squats USB devices; one enumeration per boot.
