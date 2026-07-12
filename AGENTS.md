# AGENTS.md — m1n1 (T6040 / M4 Pro bring-up fork)

This is a fork of upstream m1n1 used to bring up **Apple M4 Pro (T6040 "Brava
Chop", chopped t6041; Mac16,8 / J614s)**, tethered over USB from an M1 host. Most
work is: read a gap in the boot log → reuse the closest M3/M4 (`t60xx`) template
in `src/` → verify against the live machine → chainload → upstream.

**Read this before touching anything. It is the map, not the manual — drill into
the linked docs for depth (progressive disclosure).**

## 🛑 Hard rules when the M4 is attached (a real, tethered daily-driver machine)

1. **Never write SPMI / PMU / charger** registers or nodes. Never write NVRAM.
2. **pmgr / cluster / any MMIO write outside a known-safe path is GATED**: show the
   maintainer the exact address+value and wait. Reads of unrelated subsystems: ask.
3. **Wrong-offset MMIO on M4 raises an async SError** that the proxy's exception
   guard (`GUARD.SKIP`, which only catches *synchronous* aborts) does NOT catch —
   it wedges the proxy and needs a power-cycle. Do **not** blind-probe unknown
   register offsets. Derive from the ADT; if you must probe, one guarded read at a
   time, ready to power-cycle. (Learned the hard way — see `src/AGENTS.md`.)
4. **USB gadget is not hot-plug safe** — never suggest unplugging. Recovery no
   longer needs a hand on the button: `bash
   ~/Code/wallace/scripts/t6040-debugusb-console.sh reboot` warm-reboots the M4 over the
   DebugUSB cable and re-attaches (→ "Running proxy…" in <20 s). Reboots for the
   bring-up loop are fine; still coordinate if the machine might be in use.
5. **Don't post anything externally** (GitHub, IRC/#asahi-dev). Draft only; the
   maintainer reviews and posts.
6. If the proxy stops responding: work the documented recovery first (pty-reader
   discipline + kisd restart + remote reboot — DEVLOG "DebugUSB link" rules). If
   that doesn't bring it back, **say so and stop** — don't retry into a wedge.

## Build & run loop (host = this M1 Mac)

```sh
PATH="$HOME/.cargo/bin:$PATH" make -j8            # → build/m1n1.{bin,elf,macho}
M1N1DEVICE=/dev/cu.usbmodemJ22GYCN4YG1 \
  python3 proxyclient/tools/chainload.py -r build/m1n1.bin   # reload over USB, ~seconds
make proxy                                        # connect to the M4 proxy shell
```
Toolchain needs **rustup nightly** + LLVM — see `rust/AGENTS.md`. Chainloading a
fresh build makes `build/m1n1.elf` symbols valid against the live image
(`runtime = u.base + elf_vaddr`).

**DebugUSB transport (the default since 2026-07-12):** with a DP/TB cable in the
DFU port, `bash ~/Code/wallace/scripts/t6040-debugusb-console.sh [reboot]` gives the same
proxy on a kisd pty — `M1N1DEVICE=/tmp/m1n1` — plus remote reboot, with no plain
tether needed. It replaces m1n1's USB gadget on that port (no `/dev/cu.usbmodem*`
while active). **Read the pty-discipline rules in `~/Code/wallace/DEVLOG.md` first** —
mis-handling the pty makes the link look dead.

**Linux boot loop:** `bash ~/Code/wallace/scripts/t6040-boot-dcuart.sh` chainloads m1n1
and boots the kernel to a two-way BusyBox shell on `/dev/ttydc0` over the same
cable (console log + `printf 'cmd\n' > /tmp/m1n1`). Kernel builds run in the
`kbuild` podman container via `~/Code/wallace/scripts/t6040-kbuild.sh` — recipes in
`~/Code/wallace/DEVLOG.md`.

## Where the knowledge lives (don't re-derive it)

- `~/Code/wallace/NEXT_STEPS.md` — **the handoff doc**: what to do next, nothing else.
- `~/Code/wallace/DEVLOG.md` — operational reference: boot/build recipes, DebugUSB link
  rules, solved blockers, investigation history, dead ends.
- `~/Code/wallace/roadmap.md` — the long game (stages A–H), current snapshot.
- `~/Code/wallace/done/` — finished per-topic plans, session write-ups, drafts.
- `~/Code/wallace/scripts/` — the live harnesses (debugusb-console, boot-dcuart,
  bootcap-fb, kbuild, make-initramfs, init-dcuart).
- `~/Code/wallace/patches/` + `~/Code/wallace/dts/` — kernel patches and the dcuart board DT the
  kbuild container applies (copy to `~/Code/linux-build-out/` before building).
- `proxyclient/AGENTS.md` — how to talk to the M4 (connect, run code, safe probing).
- `src/AGENTS.md` — m1n1 firmware C: T6040 chip constants, per-driver status & gotchas.
- Host-local agent memory (not committed): `~/.claude/projects/-Users-damsleth-Code-m1n1/memory/` — SMP topology, broken_wfi, build toolchain, DebugUSB console. Verify facts still hold before acting on them.

## Local fork deltas vs upstream

- `broken_wfi` flag on `features_m4`: M4 secondaries lose architectural state on
  wfi/wfit, so they park in `wfe` instead of `deep_wfi()` (`src/chickens.c`,
  `src/smp.c`). Proxyclient `CPUFeatures` parses it. Keep this — do not "clean it up".
- Chicken-bit init fns are **NULL on M4 by design** (raw-boot locks Apple sysregs;
  writing them traps). Leave them NULL.
- `src/dapf.c` gates DAPF init per SoC (all t6040 entries trap → async L2C SError
  at kboot handoff); `src/kboot.c` arms WD1 for ~20 s on M4 before handoff
  (`src/wdt.c: wdt_arm_secs`) so hung kernels warm-reset to "Running proxy".
- `proxyclient/m1n1/proxy.py` supports pty devices (raw termios, tolerant baud
  ioctl) — required for the kisd DebugUSB bridge.
- The curated, upstream-shaped code-only series lives on branch `t6040-bringup`
  (worktree `~/Code/m1n1-clean`); keep it in sync with src/ changes on main.
