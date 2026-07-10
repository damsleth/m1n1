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
4. **USB gadget is not hot-plug safe** — never suggest unplugging. To recover a
   wedged proxy, the maintainer power-cycles the M4 (button → "Running proxy…");
   the device node returns with the same name. Don't reboot the M4 without asking.
5. **Don't post anything externally** (GitHub, IRC/#asahi-dev). Draft only; the
   maintainer reviews and posts.
6. If the proxy stops responding: **say so and stop.** Don't retry into a wedge.

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

## Where the knowledge lives (don't re-derive it)

- `.plans/roadmap.md` — **current state**: what works, what doesn't, what's next.
- `.plans/*-plan.md` — detailed active plans (cpufreq, mcc, …) with hardware-verified findings. `.plans/done/` = finished.
- `.plans/*-session.log` — raw proxy session transcripts (evidence).
- `proxyclient/AGENTS.md` — how to talk to the M4 (connect, run code, safe probing).
- `src/AGENTS.md` — m1n1 firmware C: T6040 chip constants, per-driver status & gotchas.
- Host-local agent memory (not committed): `~/.claude/projects/-Users-damsleth-Code-m1n1/memory/` — SMP topology, broken_wfi, build toolchain. Verify facts still hold before acting on them.

## Local fork deltas vs upstream

- `broken_wfi` flag on `features_m4`: M4 secondaries lose architectural state on
  wfi/wfit, so they park in `wfe` instead of `deep_wfi()` (`src/chickens.c`,
  `src/smp.c`). Proxyclient `CPUFeatures` parses it. Keep this — do not "clean it up".
- Chicken-bit init fns are **NULL on M4 by design** (raw-boot locks Apple sysregs;
  writing them traps). Leave them NULL.
