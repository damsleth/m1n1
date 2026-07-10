# AGENTS.md — src (m1n1 firmware C, T6040 bring-up)

Bare-metal C running on the M4. Build/chainload/safety in the root `AGENTS.md`.

## The porting pattern (how nearly every gap here is closed)

1. Boot log names a gap (e.g. `cpufreq: Chip 0x6040 is unsupported`).
2. Find the nearest existing chip's code path. **T6040 ≈ t6031 (M3 Max)** — same
   cluster shape (1×E + 2×P), same MMIO cluster window layout. `t6041` ADT nodes
   often map to t6031/t602x handlers.
3. Add a `case T6040:` / compatible branch reusing that template.
4. **Verify against the live machine before trusting it** — bases/offsets/counts
   from the ADT, then a careful read. M3 magic offsets do NOT always port (see
   cpufreq below).
5. Rebuild → chainload → confirm boot log. Gate any MMIO writes with the maintainer.

## T6040 chip facts (verified)

- `T6040 = 0x6040` (`soc.h:33`); `EARLY_UART_BASE = 0x429200000` (`soc.h`).
- MIDR E/P parts 0x54/0x55 "Brava Chop" (`midr.h`).
- `CPU_START_OFF_T6031` (0x88000) is **correct** for Brava (`smp.c:296`).
- Clusters: E=cluster0 window `0x210000000`, P0=cluster1 `0x211000000`,
  P1=cluster2 `0x212000000`; CLUSTER_PSTATE = window + `0xe00000`
  (`0x210e00000/0x211e00000/0x212e00000`) — identical to t6031.
- 14 cores: E smp_id 0-3, P0 4-8 (boot=4), P1 10-14 (smp_id 9 gap).

## Per-area status & gotchas

- **cpufreq.c — DONE (minimal).** T6040 reuses `t6031_clusters`; `t6040_features`
  = {cpu-apsc, cpu-fixed-freq-pll-relock} only (both on CLUSTER_PSTATE 0x20020).
  ⚠️ **The t6030 throttle offsets (ppt 0x48400/0x48408, llc 0x40270, amx 0x40250)
  do NOT map to T6040 P-clusters — reads there raise SError.** They're dropped
  pending an RE'd T6040 register map. Boot path is `cpufreq_fixup()` (main.c),
  which no-ops for T6040; `cpufreq_init()` (payload/proxy op) does the real work.
- **mcc.c — Phases 1+2 DONE (2026-07-10); TZ offset open (Stage C).** Added
  `mcc_init_t6041()` (t6031 reuse does NOT work — reg map differs). ADT-driven:
  `amcc-reg-idx=12`, `amcc-count=4` (**64-bit** prop → `u64`), 4× 32 MB AMCC windows
  at `reg[12..15]`, `dcs-count-per-amcc=4`. Phase 2 hardware-verified: **1 plane per
  AMCC** (`T6041_PLANE_COUNT=1` — plane-1 offset 0x40000 is unbacked, SError'd the
  proxy), and SLC status = `0x00010101` (`T6041_CACHE_STATUS_MASK/VAL`; the T6031
  12-way decode is wrong). Boots "4 instances, 1 planes, 4 channels", no MMIO at
  init. **Open:** TZ/carveout offset (t603x regs read 0 despite real region-id-2/4
  carveouts) — Stage-C-only, resolve via bounded value-search or macOS dump. Do NOT
  blind-sweep MCC offsets (async SError → power-cycle). See
  `.plans/2026-07-10-t6040-mcc-plan.md`.
- **chickens.c — leave M4 init fns NULL** (raw-boot locks Apple sysregs; writing
  traps). `features_m4` carries the local `broken_wfi=true`.
- **smp.c — `broken_wfi`** gates wfe-park vs `deep_wfi()`. Don't remove.

## Gotchas

- After editing, `PATH="$HOME/.cargo/bin:$PATH" make -j8` (nightly rust required).
- A freshly built `m1n1.elf` only matches the running image **after** you chainload
  that build. It's a PIE: `.text` has ~1769 R_AARCH64_RELATIVE relocs, so a raw
  byte-compare vs the running image "differs" at every relocated pointer — that's
  expected, not a mismatch.
- MMIO writes at boot are the SError trap. Prefer paths that only touch registers
  validated safe on **all** clusters (E and P differ on M4).
