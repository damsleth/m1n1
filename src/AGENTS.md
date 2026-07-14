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
  `~/Code/wallace/done/2026-07-10-t6040-mcc-plan.md`.
- **pcie.c — T6040 register map DONE; live validation GATED (2026-07-14).** Added
  `regs_t6040` + `apcie,t6040`; ADT verifies 35 regs, #ports=4, shared=reg[0..6]
  then 4×7 port regs, so `shared_reg_count=7`. Static analysis of the paired
  macOS `AppleT6040PCIe::start()` now proves `apcie-cio3pllcore-tunables` targets
  reg[5] (`0x415046200`) and `apcie-pcieclkgen-tunables` targets reg[6]
  (`0x415044000`); the T6040-only path applies both and continues through the
  reused t6031/T8122 PHY sequence. The first approved live attempt reached
  `No common tunables`; a traced retry delivered an asynchronous SError after
  AXI tunable `[70]` and before `[71]`. Offline disassembly proved Apple enables
  clock gates 0–6 before AXI/CIO3/clkgen and gate 7 (`APCIE_PHY_SW`) afterward;
  m1n1 had enabled all eight up front. Main `6efe2d45` matches Apple's gate
  order, logs every T6040 local tunable immediately before and after its RMW,
  and returns after the late gate but before all PHY/port writes. Its approved
  run repeated the same SError after AXI `[70]`, before CIO3/clkgen/the late
  gate, disproving early `APCIE_PHY_SW` enable as the cause. A barrier plus
  read-only L2C-status diagnostic ran at main `88ce1ee3`: it fenced
  before the first and after each traced RMW, samples but never clears status,
  and would abort on a nonzero sample. `[70] done` proved its immediate sample
  was zero before the same delayed SError. All three traced logs stop at the
  identical trace boundary. Main `3e772779` ran a zero-PCIe-write
  trace-volume control: it reads the AXI property from the ADT, prints identical
  trace pairs, and returns before PCIe PMGR or controller MMIO. It still faulted
  after `[70] done`, proving a logging artifact. The 16 KiB log ring occupies
  `0x105ce7a4000..0x105ce7a8000`, exactly to top-of-RAM; its initial 8 KiB
  console backlog makes it wrap during `[61] done`, with the SError delivered
  1,082 bytes later. Main `a61fd099` keeps an unused 16 KiB page above the active
  log ring and retains the zero-write trace. Its approved run completed all 77
  entries and booted base Linux without SError, proving the guard. Main
  `f46d6e35` restores the Apple-ordered 105-operation path with barriers/status
  samples and the hard return before the first PHY write. Its live run is under
  a fresh approval gate.
  **`pcie_init` is kboot-only +
  invasive: do not run it from the proxy, and do not boot this path without
  approval for that exact build.** See
  `~/Code/wallace/done/2026-07-14-t6040-wireless-pcie-map.md`.
- **kboot_atc.c / ATC-USB-DART — AUDITED 2026-07-10 (item 4).** All kboot-only +
  FDT-only (no MMIO). DART done (t6040 = `dart,t8110`, supported). ACIO USB4
  rc/pcie_adapter tunable names present on `acio0` → work as-is. **ATC PHY tunables
  blocked:** `atc-phy,t6040` has new source names (`CIO4PLL`, `AUS40CMN`,
  `ATC_COMMON_CFG`, `LN{0,1}_RX_*`, …); FDT bucket names are stable but the
  per-bucket reg_offset/size (t6040 PHY reg map) must be RE'd — don't invent, don't
  add a `atc_tunables_t6040` guess. Fails gracefully to USB2-only, so it doesn't
  block Stage C. See `~/Code/wallace/done/2026-07-10-t6040-atc-usb-dart-plan.md`.
- **kboot.c FDT (item 5) — AUDITED + display FIXED 2026-07-10.** kboot-only,
  FDT-only (safe), needs a Stage-C kernel DT to run. `dt_set_display` now handles
  t6040 (was "unknown compatible, skip"): reuses the t602x carveout scheme —
  region-id 49/50/57/94/95/157 verified on the live `/chosen/carveout-memory-map`
  (clustered around framebuffer region-id-14) — plus dcpext firmware. Generic parts
  (spin-table/`dt_set_cpus`, DART t8110, ACIO) already work. **Don't** add a
  speculative `dt_fixup_t6040_compat` — wait for a real t6040 DT. dcpext data
  regions (73/74, 88/89) present but not statically carved (t602x pattern) —
  validate at Stage C. See `~/Code/wallace/done/2026-07-10-t6040-kboot-fdt-plan.md`.
- **dapf.c — GATED per SoC (the Stage-C handoff fix).** On t6040 ALL dapf
  entries trap (async L2C SError at kboot handoff — was the first-boot
  blocker); `dapf_skip_entry()` skips them, refined to still program dart-mtp
  (the internal keyboard needs it). t8132 skips only aop/isp.
- **kboot.c / wdt.c — M4 watchdog arm.** `wdt_arm_secs(20)` before handoff on
  M4: a hung kernel warm-resets to "Running proxy" instead of needing a
  power-cycle. Linux `apple_wdt` takes WD1 over once userspace pets it.
- **dockchannel_uart.c — works on t6040 as-is** (console + proxy over the
  dockchannel FIFO; this is what DebugUSB/kisd talks to). Two hardware facts
  discovered 2026-07-12, live-probed from m1n1: the ADT-declared AIC irq 360
  for this FIFO **never asserts** (all 4096 AIC inputs scanned — Linux needs
  the poll-mode patch in `~/Code/wallace/patches/`), and the block maps **only**
  +0xc000 (irq, 24 B) + +0x28000..+0x38004 — reading e.g. +0x20000 async-SErrors
  m1n1 (the sibling dockchannel-mtp block DOES map those offsets; don't
  generalize between them).
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
