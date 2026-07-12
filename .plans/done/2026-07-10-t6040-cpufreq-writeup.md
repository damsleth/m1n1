# m1n1 cpufreq bring-up on M4 Pro (t6040 "Brava Chop")

*Draft for #asahi-dev — 2026-07-10. Review before posting.*

Follow-up to the SMP/first-light work on the tethered t6040 (Mac16,8 / J614s,
chip-id 0x6040, raw-boot, macOS 26.x / mBoot-18000.121.3). Got `src/cpufreq.c`
working for T6040, with one caveat worth flagging for anyone with M4 register-map
knowledge.

## What works

**Clusters: T6040 reuses `t6031_clusters` unchanged.** Verified the three cluster
PSTATE bases against the live machine three ways:
- ADT `/cpus`: cluster-id 0 (type E) at MMIO window `0x210000000`, cluster-id 1
  (P) at `0x211000000`, cluster-id 2 (P) at `0x212000000`. CLUSTER_PSTATE =
  window + `0xe00000` → `0x210e00000 / 0x211e00000 / 0x212e00000`, i.e. exactly
  the t6031 values.
- Matches the measured MPIDR topology (E=cl0 Aff1=0, P0=cl1 Aff1=1, P1=cl2
  Aff1=2; 4E + 5P + 5P = 14, smp_id 9 gap on the P0→P1 boundary).
- Guarded reads of all three `+0x20020` regs return sane `0x400101` (DESIRED1=1).

Added `case T6040:` alongside `T6031` in the four pstate/cluster switches
(`pstate_reg_to_pstate`, `set_pstate`, `cpufreq_get_clusters`) and it drives
correctly: `cpufreq_init()` returns 0, enables APSC, and the clusters settle at
their nominal pstates (E→5, P→6), CLUSTER_PSTATE BUSY clears with no switch
timeout. Boot-path `cpufreq_fixup()` correctly no-ops (unknown fw → default
return). No more `cpufreq: Chip 0x6040 is unsupported`.

## The caveat — t6030 throttle register offsets do NOT port to T6040 P-clusters

`t6030_features` includes ppt/llc/amx-thrtl at cluster offsets `0x48400`,
`0x48408`, `0x40270`, `0x40250`. On T6040:
- E-cluster: `0x40250` (amx-thrtl) faults; `0x40270`/`0x48400`/`0x48408` read 0.
- **P-cluster: a plain read of `0x40250` OR `0x40270` raises an SError** (async —
  the m1n1 exception guard only catches synchronous aborts, so this wedges the
  proxy and needs a power-cycle).

All five features ARE declared enabled in the T6040 ADT `/arm-io/pmgr`
(cpu-apsc=1, ppt-thrtl=1, llc-thrtl=1, amx-thrtl=1, cpu-fixed-freq-pll-relock=0),
so the features exist — but the `0x40xxx` register offsets differ on T6040
P-clusters vs M3. The ADT exposes `cluster-ctl-offset=0x20000`,
`misc-cores-offset=0x88000`, `misc-acg-offset=0x98000`, `apsc-snooze=0`, but not
the throttle-register layout.

**Question for the channel:** does anyone have the T6040/M4 throttle register map
(ppt/llc/amx-thrtl offsets), or a pointer to where macOS programs these? Since the
mask64 read-modify-write in `cpufreq_init_cluster` hits these unconditionally,
reusing t6030's offsets SErrors at boot on P-clusters.

## What I did about it (interim)

Minimal, safe patch that touches only the validated CLUSTER_PSTATE (`+0x20020`):
- New `t6040_features[] = { cpu-apsc, cpu-fixed-freq-pll-relock }` (both on
  CLUSTER_PSTATE); drop ppt/llc/amx-thrtl until the T6040 offsets are known.
- Dedicated `case T6040:` in `cpufreq_init_cluster`'s misc switch that no-ops
  (skips the t6030 `write64(base+0x440f8, 1)`, unverified on T6040 P-clusters).

Result: pstate/APSC management works; throttle configuration deferred. Happy to
send this as a PR framed as "T6040 cpufreq: pstate/APSC only, throttles TODO", or
hold for the real throttle map if someone has it.

## Environment note

Guarded proxy reads (`GUARD.SKIP`) are safe for probing *synchronous*-abort
registers but NOT for these — the throttle regs raise asynchronous SError, which
sails past the guard and drops the USB gadget. Cost two power-cycles to pin down;
flagging so others don't repeat it.
