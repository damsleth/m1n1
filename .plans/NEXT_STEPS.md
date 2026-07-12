# t6040 Linux bring-up — NEXT STEPS

Handoff state (2026-07-12): mainline Linux boots to a BusyBox shell on the
M4 Pro with working internal keyboard, watchdog, and a **fully remote dev
loop** — two-way m1n1 proxy AND Linux shell (`/dev/ttydc0`) over one DebugUSB
cable; reboot via `macvdmtool`. No screen-reading or physical access needed.
Operational details, recipes, and history: `DEVLOG.md`. Long-term: `roadmap.md`.
Read the DebugUSB link rules in DEVLOG before touching the rig.

## 1. Trackpad events (quick, first boot of the next session)
At the shell: `cat /dev/input/event0 | hexdump | head` and swipe (keyboard is
likely event1; try both). input0 = Apple DockChannel Multi-touch,
input1 = Apple DockChannel Keyboard. Now trivial over the dcuart shell.

## 2. Full-pmgr DT bring-up (the active blocker)
The 214-domain autogen pmgr hangs pre-console without the functional-policy
patch. The blindness that stalled session 2 is half-solved (dcuart shell =
post-userspace visibility). In leverage order:
1. **Ask flokli** — owns a J773s (same die), has m1n1 PR #597 + a minimal DT
   booting maxcpus=1; has almost certainly solved pmgr. Get his pmgr dtsi.
2. **Determinism first**: re-run the SAME hanging DTB 2–3× before trusting any
   new bisection data point (never established in session 2).
3. **One-variable isolations**: autogen pmgr with ONLY amcc/dcs/fab/soc_dpe
   removed+reparented (tests core-infra claim without the pmgr1 confound);
   autogen pmgr1 reparented-only vs removed-only (splits the reparent confound).
4. **Apple ground truth**: macOS `ioreg -p IODeviceTree -l` or a live ADT dump
   → validate generated reg offsets/parents/always-on. Fix `pmgr_adt2dt.py`'s
   always-on derivation (known wrong vs yuka's t8132: over-marks pmc/pms_*,
   misses aic) regardless.
5. **Pre-console visibility** (if still needed): a tiny printk/earlycon poller
   writing raw bytes into the dockchannel FIFO (regs usable from the first
   kernel instruction; m1n1-style TX needs no IRQ). Also worth doing properly:
   register a real console in the dockchannel tty driver so `console=ttydc0`
   works.

## 3. Persist userspace comfort
- Fuller initramfs (real busybox userland, mount tools), then rootfs on NVMe
  (needs pmgr + dart + ans2 — sequenced after step 2).

## 4. Upstream / share
- Post the drafted writeups: `done/2026-07-10-t6040-smp-writeup.md`,
  `done/2026-07-10-t6040-cpufreq-writeup.md` (#asahi-dev).
- Keep the curated code-only branch `t6040-bringup` (worktree
  `~/Code/m1n1-clean`) in sync with any new src/ changes on main.
- Report the dockchannel-uart dead-IRQ finding + poll-mode patch to the
  dockchannel-branch authors (yuka / Michael Reeves) — t8140 may differ.

## Parked (revisit after pmgr)
- USB gadget console → gadget-Ethernet + SSH (EP0 dies post-enumeration;
  `done/2026-07-11-t6040-usb-gadget-plan.md`).
- cpufreq throttle offsets (t6030 offsets SError on t6040 P-clusters; needs RE
  or #asahi-dev answer).
- ATC PHY tunables (USB3/TB) — blocked on t6040 PHY reg-bucket offsets;
  USB2-only fallback is fine for now.
