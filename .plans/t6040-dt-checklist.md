# t6040 device tree fill-in checklist

Draft DTs live in `~/code/linux` branch `t6040-minimal-device-trees`
(`t6040.dtsi`, `t6040-j614s.dts`, on top of yuka's `feature/m4-m5-minimal-device-trees`).
Every unverified value is tagged `TODO(adt)` — grep for it. This doc maps each
one to the proxy command that resolves it. All of it needs one session with the
proxy up (`shell.py` on the host).

## 0. One-time: dump the ADT

```py
# in proxyclient/tools/shell.py
open("j614s.adt", "wb").write(u.get_adt())
```

Keep this blob forever — it answers every question below offline, and it's the
input to the pmgr generator. (Note: yuka's t8132/t6050 commits used macOS
26.6b2 firmware; note our iBoot version alongside the dump.)

## 1. CPU topology + reg values → t6040.dtsi cpus/cpu-map

```py
for node in u.adt["/cpus"]:
    print(node.name, hex(node.reg), node.cluster_type, node.die_cluster_id)
```

Fix: number of clusters (draft assumes 4E + 5P + 5P), each cpu node's `reg`
(draft uses t602x-style 0x0/0x10100/0x10200 bases), compatibles (expect
`apple,sawtooth` E / `apple,everest` P per earlier ioreg check).

## 2. L2 cache sizes → l2_cache_0/1/2

```py
u.adt["/cpus/cpu0"].l2_cache_size   # and one core per cluster
```

## 3. AIC base → aic node (CRITICAL — currently a t6050 guess)

```py
node = u.adt["/arm-io/aic"]
print(node.get_reg(0))   # base+size; add arm-io base 0x2_00000000 if reg is relative
```

Draft guesses `0x2_80400000` (copied from t6050). Also verify the second reg
(event/IACK page) against what the t8122-aic3 binding expects; m1n1's
`src/aic.c` shows how the offsets are derived.

## 4. UART IRQ → serial0 interrupts

```py
u.adt["/arm-io/uart0"].interrupts
```

reg `0x4_29200000` is already verified. Draft carries t8132's IRQ 1046 as a
placeholder. After fixing: flip `&serial0` to `status = "okay"` in the .dts.

## 5. Watchdog → add wdt node (currently omitted)

```py
node = u.adt["/arm-io/wdt"]
print(node.get_reg(0), node.interrupts)
```

Copy the t8132 wdt node shape with these values.

## 6. pmgr → generate t6040-pmgr.dtsi

```sh
python proxyclient/tools/pmgr_adt2dt.py j614s.adt > t6040-pmgr.dtsi
```

Then: add the two pmgr nodes to t6040.dtsi (t8132 shape, reg from
`/arm-io/pmgr` `get_reg(0)`/`get_reg(1)`), `#include "t6040-pmgr.dtsi"` at the
bottom, and wire `power-domains` back into serial0 (`ps_uart0`) and
framebuffer0 (`ps_disp_cpu`/`ps_dptx_phy` — check names in the generated file;
the j614s fb is on dispext/dcp, verify which domain).

## 7. Memory base → j614s.dts memory node

```py
print(hex(u.ba.mem_base), hex(u.ba.mem_size))
```

Draft assumes `0x100_00000000` (t600x/t602x Pro-die convention; t8132 uses
0x8_00000000). m1n1 rewrites the reg anyway, but the unit address should match.

## 8. Boot test order

1. m1n1 with the broken_wfi patch (already on fork main) via chainload
2. Kernel: yuka's branch + our DTs, `CONFIG_ARCH_APPLE`, boot args `idle=nop`
   (per yuka's cover letter: wfi/wfit lose state on secondaries) — expect
   single-core first (`maxcpus=1`), console on DockChannel (kisd) or fb
3. Expect the t6050-style `SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2` crash risk in AIC
   init — t8132 doesn't hit it, t6050 does; unknown which way t6040 goes.
   If it hits: patch out the write like yuka did, report which way it went.
4. Report to yuka (cyberchaos.dev/yuka/linux) / #asahi-dev either way — t6040
   fills the hole between her t8132 and t6050 series.
