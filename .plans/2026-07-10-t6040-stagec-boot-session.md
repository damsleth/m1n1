# Stage C — first t6040 Linux boot attempts (2026-07-10 session log)

First real kernel boots on the M4 Pro with our from-scratch DT. Kernel + DT build
(podman container, see `t6040-kernel-build-env` memory + `t6040-kbuild.sh`);
booted via `proxyclient/tools/linux.py` (raw kboot, no initramfs, `maxcpus=1
idle=nop`, fb console). Boot/capture harness: `t6040-bootcap.sh`.

## How far we get: m1n1 kboot handoff, blocked by an async L2C SError

The kernel Image (49 MB, arm64) + `t6040-j614s.dtb` load fine. `kboot_prepare_dt`
runs to completion and `kboot_boot` gets almost to the kernel jump, then m1n1
takes an **imprecise async SError** and reboots — Linux itself never starts.

### Validated on real hardware this session
- **CPU DT fix works.** The slot-9 placeholder (`cpu@10105`, disabled 6th P-cl0
  core on the chopped die) makes `dt_set_cpus` match all MPIDRs (0x0-3, 0x10100-4,
  0x10200-4) and prune the gap correctly. Was: `DT CPU 10 MPIDR mismatch 0x10201
  != 0x10200`; now clean.
- **DT is structurally correct** — cpus/AIC/timer/memory all accepted; `FDT
  prepared`; memory `DRAM at 0x10000000000 size 0x600000000`.
- **MCC Phase 2 validated** — `MCC: System level cache enabled` (plane_count=1,
  status mask 0x00010101) succeeds at kboot, no timeout/SError from it.
- **PCIe (item 3) parse validated** — `pcie: Initializing t6040 PCIe controller`,
  `ADT uses 7 reg entries per port` (confirms `shared_reg_count=7`).
- All the "not found / unsupported" for GPU/SEP/PMP/ISP/nvram/ATC/USB4 are the
  expected minimal-DT degradations (non-fatal).

### The blocker: imprecise async L2C access-fault SError
```
Exception: SError   (EL2h, MPIDR 0x80010100 = boot P-core)
ESR: 0xbe000000 (SError)
L2C_ERR_STS: 0x82   (ACCESS_FAULT | RECURSIVE_FAULT)
L2C_ERR_ADR: 0x283640500578190   L2C_ERR_INF: 0x1400000002   (identical every run)
FAR: 0x0   PC rel ~0x30c4c (in usb_dart_init, but that's just ADT reads = the
           delivery point of an imprecise async SError, NOT the cause)
Unhandled exception, rebooting...
```
`kboot_boot` order (src/kboot.c): `mcc_enable_cache → tunables_apply_static →
clk_init → usb_init → pcie_init → dapf_init_all → smp_set_wfe_mode → jump`.
SError is delivered **right after `dapf: Initialized dart-mtp`** (before "Setting
SMP mode to WFE" prints).

### Ruled OUT this session (by disabling and re-testing — SError persisted)
- **`mcc_enable_cache`** — deferred it entirely → SError unchanged.
- **`usb_init`** — commented out at kboot → SError unchanged (moved delivery point
  but same L2C_ERR_ADR/INF).
Both reverted (they weren't the cause). The PCIe PHY-defer is KEPT (that one IS
necessary — without it m1n1 hangs hard in the PHY refclk poll, committed 8a547971).

## Leading hypotheses for the L2C SError (next session)
1. **Carveout/SLC interaction (top suspect).** The MCC TZ carveouts could NOT be
   unmapped (t603x TZ regs read 0 — see the MCC plan). iBoot's SLC is enabled, so
   an access to a still-mapped, now-cacheable protected region (SEP etc.) raises
   an L2C access fault. This is deterministic (identical L2C_ERR_ADR) and survives
   disabling mcc/usb — fits a "wrong carveout map" root cause.
2. **`dapf_init_all`** — its DART MMIO is the last thing before delivery; could be
   the faulting access (t6040 dart-aop/mtp specifics).
3. **Pending pre-kboot SError** delivered when `linux.py` sets `DAIF=0xc0` (SError
   unmasked) — e.g. from the 50 MB kernel `writemem` into DRAM. (But load addr
   0x1000fe00000 is low, far from the top carveouts, so less likely.)

## Next steps
1. **Decode `L2C_ERR_ADR 0x283640500578190` / `L2C_ERR_INF 0x1400000002`** (Apple
   L2C error-syndrome format) → the faulting physical address/way. This is the
   fastest path to the culprit and sidesteps the imprecise-PC problem.
2. **Bisect the rest of kboot_boot**: disable `dapf_init_all`, then
   `smp_set_wfe_mode`, then `clk_init`/`tunables_apply_static`, one at a time.
3. **Reproduce without a kernel** (does the SError happen with a tiny dummy
   payload?) to separate kernel-load faults from kboot-step faults.
4. **Chase hypothesis 1**: get the real t6040 TZ/carveout region-ids from a booted
   macOS (region-id-2/4 per mcc.c:188) and fix `mcc_unmap_carveouts` so protected
   regions are actually unmapped before the SLC caches them.
5. Raise on #asahi-dev — an L2C access-fault SError on M4 raw-kboot may be known
   (yuka's t8132/t6050 series).

## Console note
The kernel's OWN console does NOT survive on the …YG3 USB UART (it's m1n1's gadget
bridge, gone after handoff). But since we're blocked in m1n1 (pre-handoff, EL2),
its console — including the SError dump — comes over the …YG1 proxy as `TTY>`
lines: capture `linux.py` output WITHOUT grep-filtering (`sed -n '/Ready to
boot/,$p'`). No screen photos needed for m1n1-side crashes.

## Build/run recipe
- Kernel/DTB: `podman machine start; podman exec kbuild bash /kbuild.sh image`
  → `~/code/linux-build-out/{Image,t6040-j614s.dtb}`. (See `t6040-kernel-build-env`.)
- Boot: `t6040-bootcap.sh` (chainload m1n1 + linux.py). linux.py raises UartTimeout
  at kboot_boot — that's the handoff, expected; the SError dump precedes it.
