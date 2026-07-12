# t6040 (M4 Pro) Linux bring-up — NEXT STEPS / handoff

## DONE (2026-07-12): two-way console/proxy over DebugUSB (KIS) 🎉

**The early-boot console exists.** Full two-way m1n1 proxy + console over the
DP/TB cable in the DFU port, via **DebugUSB/KIS** (NOT SBU analog serial —
see dead-ends below). Verified: p.nop(), ADT fetch, memory reads, and a full
boot-log capture that includes iBoot stage markers (iBoot's own output is
hash-redacted by production fuses; m1n1's is plaintext).

**How to (re)establish:** `bash .plans/t6040-debugusb-console.sh [reboot]`
- Host side: `sudo macvdmtool [reboot] debugusb` (root-owned copy at
  /usr/local/bin/macvdmtool, NOPASSWD sudoers entry, patched source at
  ~/Code/macvdmtool with new cmds: actions/vdm/dven/localserial).
- Host daemon: `~/Code/kisd` (AsahiLinux/kisd, builds & runs on macOS as-is).
  It auto-detects the t6040 KIS base 0x548700000; allocates a pty (printed in
  its log; /dev/m1n1 symlink fails under SIP). kisd uart channel 0 == the
  dock-side of the AP `/arm-io/dockchannel-uart` (AP data block 0x50882c000
  + 0x40004000 = 0x548830000; same +0x40004000 offset holds on t8140).
- Client: `M1N1DEVICE=<pty> python proxyclient/tools/...` — proxy.py has a
  LOCAL UNCOMMITTED patch (Serial: raw pty termios + tolerate baud ioctl
  failure) required for ptys; without it replies get mangled by termios.
- GOTCHA: DebugUSB replaces m1n1's dwc3 gadget on the DFU port (no
  /dev/cu.usbmodem* while active). For fast chainload, put the plain cable
  in ANOTHER target port; DebugUSB console coexists with it.

**SBU analog serial is a DEAD END on M4 (do not retry):** ACE3 (sn2012027)
advertises action 0x306 (Get Action List works — new `macvdmtool actions`)
but REJECTS every enter attempt: host VDM → BUSY reply 0x40030004; target-
side DVEn via SPMI (nub-spmi-a0/hpm0, slave 0xc, unlock key = reversed
target-type "416J", PR #594 protocol reimplemented live in
scratchpad/target_serial_entry.py) → result 0x3 for pin sets 2/7; pin set 0
(0x1810306) is ACCEPTED but no data flows (no HW drain to SBU); pin set 1
(0x1820306) maps UART onto USB D+/D- and KILLS the USB proxy (m1n1 gadget
does not re-enumerate — reboot needed). Action-info for 0306 =
0x0187020c 0x800c0000. The dockchannel FIFO's real consumer is the KIS
debug agent, hence DebugUSB is the supported path.

**NEXT: Linux console on dockchannel UART** (host side now proven):
Import from `origin/dockchannel`: `d2acb86f70a2` (mailbox: apple: DockChannel
FIFO controller) + `b8dcbdcb` (tty: apple: DockChannel serial test driver,
/dev/ttydcN) and use `e46443b` (t8140 J700 DT nodes) as the template —
NOTE: kbuild.sh's DOCKCHANNEL block does NOT currently import these.
t6040 node data from ADT `/arm-io/dockchannel-uart`: reg[0] 0x308828000
(+0x200000000 live) size 0x10004 (config@+0, data@+0x4000), reg[1]
0x30880c000 size 24 (irq block), AIC irq 360, enable-sw-drain=1,
max-aop-clk 288 MHz. Since the KIS agent drains the same FIFO, Linux writes
to this dockchannel should appear in kisd as soon as the driver probes —
add it as a second console= after console=tty0. Then: getty on /dev/ttydcN.


Session 2026-07-11. Written to hand off to a fresh context. Companion docs:
`.plans/2026-07-11-t6040-console-session.md`, memory files
`t6040-stagec-boot-blocker`, `t6040-kernel-build-env`, `t6040-broken-wfi`,
`t6040-smp-topology`, `t6040-pcie-adt-layout`, `t6041-mcc-adt-layout`.

## TL;DR — we boot mainline Linux to userspace on the M4 Pro 🎉

BusyBox `/ #` shell reached on bare-metal t6040 (Mac16,8 / J614s). Console is the
**on-screen framebuffer** (read the laptop display; no serial exists on M4 raw-boot).
The remaining work is a **DT (pmgr) bisection** — see "Active work" below. The base
boot is DONE and reproducible.

## SESSION 3 UPDATE — full PMGR reaches userspace reproducibly

The PMGR blocker below is now solved well enough for bring-up. The full generated
four-controller/214-domain DT reached BusyBox userspace twice with the diagnostic
kernel, and a fresh clean kernel containing only the functional PMGR changes reached
userspace again.

The functional policy is:

- `apple,preserve-active` on each PMGR controller: domains found active at probe are
  marked always-on, so genpd registration does not immediately power off firmware-
  active core resources.
- `apple,skip-auto-enable` on the locked dispext0/dispext1 sys/fe/cpu domains.
- Disable the five ANE domains for now; target-state writes completed but caused a
  delayed asynchronous SError during raw-boot bring-up.
- Disable `disp_cpu@10000` for now; its first register access traps before a read can
  complete. The simple framebuffer is deliberately independent of this domain.

Minimal kernel change: `.plans/t6040-pmgr-functional.patch`. Clean build invocation
uses `.plans/t6040-kbuild.sh` with `BUILD_DIR=/build/linux-functional` and
`PMGR_FUNCTIONAL=1`. Known-good clean artifacts:

- `Image`: `b38f44ebee617e93342b50f58f3e6680d3baf38c18175f9958566f2e56b5104d`
- `t6040-j614s-fv.dtb`:
  `7bddc211d9c6ca7c374a55d23cf484301c58f8e34d64a8614cc1480e6825517c`

Next priority order:

1. **DONE 2026-07-11:** Linux `apple_wdt` takes over m1n1's WD1 and BusyBox
   pings `/dev/watchdog0` every 10 seconds. The shell remained alive beyond the
   30-second bite. Watchdog-enabled Image:
   `9fadaea08be9ae4ae0e8c4ae35aca3ec7bf8116cd6db530e2068648a9c2626b5`;
   initramfs: `81f74d3782d14e21ed9e3bbe04a1b53feb44afe9965f180e290d903cd3e0cae2`.
2. Add a Linux USB2 gadget callback on the same physical tether (new enumeration;
   gadget Ethernet + SSH preferred, ACM/getty fallback).
3. **DONE 2026-07-11 (session 4): the internal KEYBOARD WORKS at the BusyBox
   shell** (trackpad registers as input0 too, untested interactively). Three
   independent bugs were fixed — full story in
   `.plans/2026-07-11-t6040-mtp-wake-findings.md`:
   (a) m1n1 skipped dart-mtp DAPF programming on t6040 (misattributed async
   SError; src/dapf.c fixed, uncommitted); (b) t6040.dtsi ASC mailbox IRQs
   were pairwise swapped — Apple ADT lists not-empty first, binding wants
   ascending (kbd DTB 101611f1…); (c) dockchannel-hid lacked hid_ll_driver
   .stop → NULL-branch oops (Image cc2b3de1…,
   `.plans/t6040-dockchannel-fixes.patch`, applied by kbuild.sh).
4. Move from the proof initramfs to a fuller initramfs/rootfs, then NVMe.

TODO (quick, next boot): verify the trackpad delivers events — at the BusyBox
shell run `cat /dev/input/event0 | hexdump | head` and swipe on the trackpad
(keyboard is likely event1; if event0 shows nothing, try
`cat /dev/input/event1 | hexdump | head`). Registered devices:
input0 = Apple DockChannel Multi-touch, input1 = Apple DockChannel Keyboard.

## How to boot it RIGHT NOW

The M4 is tethered over USB (`/dev/cu.usbmodemJ22GYCN4YG1` = proxy, `...YG3` = vuart
dead). When it shows "Running proxy", run (from `~/Code/m1n1`):
```
bash .plans/t6040-bootcap-fb.sh t6040-j614s-nopmgr.dtb initramfs.cpio.gz
```
→ boots to `USERSPACE IS ALIVE ON THE M4 PRO` + BusyBox shell on the screen.
The script chainloads `build/m1n1.bin`, then `linux.py Image <dtb> <initramfs>` with
cmdline `maxcpus=1 idle=nop nokaslr pd_ignore_unused clk_ignore_unused console=tty0
ignore_loglevel`. Watch the SCREEN (output is fbcon, not USB). A hung kernel
warm-resets in ~20s (m1n1 watchdog). `EXTRA_BOOTARGS=initcall_debug bash ...` to trace
init hangs.

Artifacts (all in `~/Code/linux-build-out/` = `/out` in the container):
- `Image` (50M, mainline 7.2-rc2 + flokli patches + fbcon config), `System.map`
- `initramfs.cpio.gz` (busybox-static, `/init` prints proof-of-userspace then `sh`)
- `*.dtb` (bisection variants); `t6040-dts/` (their `.dts` sources + flokli patch)
- `flokli-code.patch` (the 2 kernel code patches applied by the build)

## The 5 solved M4 blockers (all same root cause: SPTM/firmware-locked resources trap)

1. **m1n1 async L2C SError** (`STS 0x82`, `ADR 0x283640500578190`) at kboot handoff:
   the **dapf** (DART page-fault filter) init. On t6040 ALL dapf entries trap
   (dart-mtp too, not just dart-aop like t8132). Fix in tree: `src/dapf.c`
   `dapf_skip_entry()` — t6040 skips every entry, t8132 skips aop/isp.
2. **AIC locked-sysreg trap**: `aic_init_cpu` writes `SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2`
   + `SYS_ICH_HCR_EL2` in hyp mode → traps on M4 → hang before console. Fix: flokli
   patch comments out BOTH (patch1 in `flokli-code.patch`).
3. **WFI state-loss**: M4 loses CPU state on WFI/WFE; boot CPU dies on first idle.
   Fix: flokli patch adds arm64 `idle=[wfi|nop]` param (skips wfi()/wfit()); boot with
   `idle=nop`. (Plain mainline ignores `idle=` on arm64; `nohlt` is also a no-op.)
4. **No fbcon in build**: needed `DRM_SIMPLEDRM`+`DRM_FBDEV_EMULATION`+
   `FRAMEBUFFER_CONSOLE`, `ARM64_SME` off. Now forced in `t6040-kbuild.sh`.
5. **Fuller-DT hang = pmgr** (active work, below).

## Console/debug reality (do not re-investigate — these are dead ends)

- **No serial console on M4 raw-boot**: `earlycon=s5l`/`ttySAC0` dead; `...YG3` is the
  m1n1 vuart (only the hv drives it → dead after handoff); m1n1 **hv is SPTM-blocked**
  (Linux can't run under SPTM). The **framebuffer** (simpledrm+fbcon) is the console.
- **RAM-dump post-mortem is DEAD**: iBoot **scrubs DRAM** on the watchdog reset
  (verified: Image bytes read back all-zero). `.plans/t6040-ramdump.py` is kept but
  useless here.
- **The only future real serial = debugusb/KIS**: needs a DP-capable USB-C cable
  (SBU pins wired — a plain charge cable won't do; user only has plain tether) +
  `AsahiLinux/kisd` on host + m1n1 self-enter-KIS (m1n1 PR #594 SPMI). Not set up.

## Build environment

- **Kernel**: `~/Code/linux`, remote = yuka's `cyberchaos.dev/yuka/linux`. Branch
  `feature/m4-m5-minimal-device-trees` = **mainline 7.2-rc2 + DT commits only** (NOT
  asahi). Mainline+flokli's 3 patches boots t6040 (flokli's proven recipe; his tree =
  `github.com/torvalds/linux compare master...flokli:linux:j773s`). Native mac build
  impossible (case-insensitive FS) → **podman container `kbuild`** builds arm64
  natively. Build: `podman exec kbuild bash /kbuild.sh image` (script =
  `.plans/t6040-kbuild.sh`, bind-mounted). It clones committed state, copies in our DT
  files from `/src`, **`git apply`s `/out/flokli-code.patch`**, forces fbcon config,
  builds Image+dtb+System.map to `/out`.
  - **BUILD GOTCHA**: it builds from COMMITTED code + copies only DT files. Uncommitted
    code edits on the host are SILENTLY DROPPED (this bit us — the host aic edit never
    reached the build). Put code changes in a patch applied by kbuild.sh.
  - Fast DTB-only rebuild for bisection: `podman exec kbuild bash -c 'cd /build/linux
    && make ARCH=arm64 apple/<name>.dtb && cp .../<name>.dtb /out/'` (add to that dir's
    Makefile first). Container/tree persist between runs.
  - **zsh gotcha**: unquoted `$var` does NOT word-split. Use `echo $v | tr ' ' '\n' |
    while read` to generate per-item lines.
- **m1n1**: `~/Code/m1n1`, build `export PATH="$(brew --prefix llvm)/bin:$PATH"; make
  -j8` → `build/m1n1.bin`. Uncommitted src changes: `dapf.c`, `kboot.c`
  (dapf gate + `wdt_arm_secs(20)` on M4 before handoff), `wdt.c/.h` (`wdt_arm_secs`).
  KEEP the PCIe PHY-defer (commit 8a547971). All build-verified; NOT committed.

## ACTIVE WORK — pmgr DT bisection (SESSION 2 2026-07-11: prior hypotheses OVERTURNED)

Our full `t6040.dtsi` hangs the kernel; the culprit is **pmgr** (apple genpd driver,
`drivers/pmdomain/apple/pmgr-pwrstate.c`, probing the 214 ADT-auto-generated domains
in `t6040-pmgr.dtsi`, across controllers pmgr0-3). Console decoupled by dropping the
fb `power-domains` + not enabling s5l (the `-fv`/`-safe`/`-curated` variants).

### What session 2 found (mix of solid and unproven — see the confidence table below)
- **Session-1's "pmgr2 peripheral traps (pmp/ap_tmm)" and "SPMI/nub" hypotheses look
  wrong.** `initcall_debug` on safe2 showed many "power controller returned -517"
  (`-EPROBE_DEFER`) — safe2 `status=disabled`s parent domains (fab*/amcc*) while
  KEEPING children that `power-domains=<&that_parent>` → dangling phandle → deferrals.
  (Whether those deferrals are the actual hang vs benign noise was NOT established.)
- **pmgr01 (autogen pmgr0+pmgr1, pmgr2+3 off) BOOTS to BusyBox** (N=1). Suggests
  autogen pmgr0/1 are usable; not stress-tested.
- **adt2dt.py always-on flags disagree with yuka's t8132** (SOLID, file comparison):
  `pmgr_adt2dt.py` sets `apple,always-on` from the ADT `critical` flag; vs yuka we
  OVER-mark pmc/pms_c1ppt/pms_fpwm0-4 and MISS aic. A real generator bug; not the
  pre-console blocker.
- **An earlier session-2 write-up here claimed "a pmgr2 peripheral genuinely FAULTS
  on register access" and bisected it to `venc0_me1` — THAT WAS WRONG.** The
  bisection was logically invalid and the "culprit" evaporated on the isolation test
  (disabling only venc0_me1 still hung). See the confidence table; there is no known
  single faulting domain.
- Mature Asahi Pro pmgr (t8132, t602x) exclude CPU/mem/fabric, so the class-exclusion
  IDEA is sound — but our attempt to apply it (curated/reparented) hung pre-console
  for reasons not yet isolated (removal vs reparenting confounded).

### The curated pmgr (proper fix, built this session)
`scratchpad/prune_pmgr.py` prunes `t6040-pmgr.dtsi` → `t6040-pmgr-curated.dtsi`:
removes CPU (ecpu/pcpu/ecpm/pcpm), memory (amcc/dcs), fabric (fab<N>_soc/fab_gw/
fab_afr) and the extras yuka omits (pms/afi/afc/rom/sbr); strips every
`power-domains=<&removed>` so survivors become ROOT (flat, like curated t8132).
147 domains kept (pmgr0:3, pmgr1:58, pmgr2:53, pmgr3:33), 0 dangling refs.
Container `kbuild` has it installed as `t6040-pmgr.dtsi` (autogen backed up as
`t6040-pmgr.dtsi.autogen`).

### SESSION-2 RESULTS — with honest confidence (NOT "proved"; all HW tests are N=1, blind, never repeated)
CAVEAT FIRST: every hardware result below is a SINGLE observation of a pre-console
hang (user reading the laptop screen). **Determinism was never checked — no DTB was
re-run to confirm it gives the same result.** If the hang is even partly
non-deterministic (probe-order race, USB/power timing), most "logo-only" data points
are unreliable and the conclusions drop toward 50/50. Treat the confidence numbers as
real. Truth table (autogen = unmodified 214-domain hierarchical dtsi; curated =
pruned+reparented-flat):

| variant | pmgr config | result (N=1) |
|---|---|---|
| `pmgr01` | autogen pmgr0+1 (hierarchical), pmgr2+3 OFF | BOOTS userspace |
| `bis-nocpu` | autogen pmgr0+1+2, pmgr3 OFF, only CPU domains (ecpu/pcpu/ecpm/pcpm) disabled | logo-only |
| `safe2` | autogen, pmgr2 core-infra `status=disabled` (orphans children), pmgr3 off | `-517` defer messages, no userspace |
| `cur-pmgr01` | curated (reparented) pmgr0+1, pmgr2+3 OFF | logo-only |
| `curated`/`bis-*` | curated pmgr, pmgr3 off, various pmgr2 subsets off | logo-only |

**SOLID (not hardware-dependent, ~90-95%):**
- The pmgr2 bisection was LOGICALLY INVALID: `bisect_build.sh` rebuilds each variant
  disabling ONLY the passed set, re-enabling domains prior tests disabled. A single
  culprit would sit in the INTERSECTION of all hung tests' enabled sets; that came out
  EMPTY. So there is no single-pmgr2-domain culprit (given the results are
  deterministic — the one unproven premise). Don't repeat the per-domain hunt.
- `pmgr_adt2dt.py` derives `apple,always-on` from the ADT `critical` flag, which does
  NOT match yuka's curated t8132 (we over-mark pmc/pms_c1ppt/pms_fpwm0-4, miss aic).
  Direct file comparison, no HW. Real generator bug worth fixing regardless.

**PLAUSIBLE but NOT isolated (~50-70%, each rests on N=1 blind tests):**
- (~80%) pmgr present → hang; pmgr absent (`min`/`nopmgr`) → boots. Consistent across
  many tests but all single-shot.
- (~50%) "The killer is pmgr2 core-infra amcc/dcs/fab/soc_dpe." NOT isolated —
  `bis-nocpu` only shows "pmgr2 with CPU domains off still hangs"; it never points at
  those specific domains. Leftover session-1 hypothesis, not a session-2 result.
- (~50%) "Reparenting to root is itself fatal." CONFOUNDED — curated pmgr1 both
  REMOVED core-infra AND reparented; `cur-pmgr01` vs `pmgr01` can't separate the two.
- (~55%) "safe2's stall WAS the −517 defer storm." Saw the storm, but never
  distinguished livelock-hang from benign defer-noise (`pmgr01` also spewed defers and
  still booted). Could be defers + a separate hang.

**Almost certain (~90%): the real obstacle is BLINDNESS.** Every pmgr2 failure except
the defer messages is pre-console (inside `apple-pmgr-pwrstate` probe, before
simpledrm) → zero output → we were guessing.

**What would actually raise confidence (cheap, boring):** (a) re-run the SAME dtb 2-3×
to establish determinism; (b) clean one-variable isolation — e.g. autogen pmgr with
ONLY amcc/dcs/fab/soc_dpe removed+children-reparented (tests the core-infra claim
without the pmgr1 confound), and autogen pmgr1 reparented-only vs removed-only (splits
the reparenting confound).

### THE ACTUAL BLOCKER IS VISIBILITY, NOT DT GUESSING — next moves (do NOT resume blind boots)
1. **Ask flokli.** flokli owns a t6040 (J773s), has m1n1 **PR #597** + a minimal DT
   booting maxcpus=1. He has almost certainly already solved pmgr for t6040 — get his
   pmgr dtsi / how he handles core-infra + hierarchy. HIGHEST leverage by far.
2. **Get a real early console** so pmgr-probe hangs are debuggable: debugusb/KIS
   (needs a DP-capable USB-C cable w/ SBU pins + `AsahiLinux/kisd`). Without this,
   pmgr bring-up stays guesswork.
3. **Apple ground truth** (user offered): macOS `ioreg -p IODeviceTree -l` OR dump the
   live ADT via m1n1 — validate our reg offsets/parents/always-on vs Apple's real set.
4. Study how mature Asahi (t602x/t8132) flattens pmgr and WHY reparent-to-root works
   there but not here (die/fabric power-on-order difference on the Pro part?).

NOTE: we did NOT regress the working baseline — `min`/`nopmgr`/`pmgr01` all still boot
to userspace. What stalled is *full-pmgr* bring-up, which needs visibility or flokli's
DT, not more blind DT permutations. All scratchpad artifacts (prune_pmgr.py,
t6040-pmgr-curated.dtsi, bisect_build.sh, *_domains.txt, variant .dts) preserved.
Container `kbuild` currently has the AUTOGEN pmgr restored as t6040-pmgr.dtsi.

## Bigger-picture next steps (after pmgr)
1. **Persist userspace**: the m1n1 watchdog resets at 20s and the minimal DTs have no
   wdt driver petting it. The `wdt` node IS safe (bisected) — a DT with wdt + the
   apple_wdt driver taking over would stop the reset. Or bump/remove the m1n1 arm.
2. **Keyboard input** (interactive shell): Apple SPI/dockchannel HID — needs pmgr power
   domains + those drivers. On the critical path after pmgr.
3. **Real rootfs**: NVMe (needs pmgr + dart + ans2). Until then, initramfs only.
4. **Commit the m1n1 changes** (dapf gate, watchdog) — currently uncommitted on `main`.
5. **debugusb** if a DP-capable cable is obtained — ends the framebuffer-only blindness.
