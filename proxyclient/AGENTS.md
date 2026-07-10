# AGENTS.md — proxyclient (host-side tools that drive the tethered M4)

Python client that talks to m1n1's proxy over USB serial. **First read the root
`AGENTS.md` safety rules** — every call here pokes a real M4.

## Connect

- Python **must be pyenv 3.10.7** (has `pyserial`+`construct`; the 3.9 default
  lacks them). `pyenv local 3.10.7` is set in the repo, or use the full path.
- `export M1N1DEVICE=/dev/cu.usbmodemJ22GYCN4YG1` — the **lower**-numbered node is
  the proxy; the `…YG3` node is the secondary UART.
- Interactive: `M1N1DEVICE=… python3 proxyclient/tools/shell.py`.
- Scripted: `sys.path.append("proxyclient")`, `from m1n1.setup import *` gives
  `p` (proxy), `iface`, `u` (utils), `u.adt`, `u.base` (runtime load base).

## Use the shared helpers — don't re-derive

`experiments/t6040.py` is the canonical, safety-hardened helper module (import it;
it does NOT open the port on import): verified cluster/MPIDR maps, `healthcheck(p,u)`,
`guarded_read64`, `read_cluster_pstates`, `snapshot`/`diff`, `run_on_cpu`, and a
**denylist that refuses the known-SError offsets**. Run `python3
proxyclient/experiments/t6040.py` for a one-line health check. Prefer extending it
over writing fresh scratchpad scripts. Connect with `make proxy` (or
`./scripts/m1n1-shell`).

## Safe probing pattern (respect the SError gotcha)

```py
def gread64(addr):                     # guarded read: (value, faulted)
    p.set_exc_guard(GUARD.SKIP | GUARD.SILENT)
    v = p.read64(addr); cnt = p.get_exc_count()
    p.set_exc_guard(GUARD.OFF)
    return v, (cnt != 0)
```
This catches **synchronous** aborts only. Wrong-offset MMIO on M4 can raise an
**async SError** that sails past the guard, prints `TTY> Exception: SError`, and
drops the USB link → power-cycle. So: prefer reading the **ADT** (`u.adt[...]`,
`node.getprop(...)`, `node.reg`) to derive addresses; never sweep unknown offsets.

## Run code on a specific core

Preferred (real elf symbol, once your build is chainloaded): `runtime = u.base +
elf_vaddr` from `nm build/m1n1.elf`, then `p.smp_call_sync(cpu, addr, *args)`.

Fallback (no matching elf): compile a leaf and upload it —
```py
from m1n1.asm import ARMAsm
code = u.malloc(0x100); c = ARMAsm("add x0, x0, x1\n ret", code)
iface.writemem(code, c.data); p.dc_cvau(code, c.len); p.ic_ivau(code, c.len)
p.smp_call_sync(cpu, code, a, b)       # boot core (smp_id 4) can't call itself → use u.exec(...)
```
Gotchas: `u.mrs("mpidr_el1")` fails (name not in the sysreg table) but `mrs x0,
mpidr_el1` assembles fine in a leaf. ARMAsm needs the LLVM toolchain (auto-resolved
via `brew --prefix llvm` / `lld`).

## Local edit

`proxyclient/m1n1/proxy.py` has a local delta: `CPUFeatures` parses `broken_wfi`
(replaced a padding byte) — must stay in lockstep with the m1n1 binary's struct.

Deeper: SMP topology, per-core MPIDR, and the run-code recipe are in the host-local
memory dir referenced by the root `AGENTS.md`.
