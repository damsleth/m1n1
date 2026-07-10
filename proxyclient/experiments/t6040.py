#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
t6040.py -- reusable helpers for the tethered M4 Pro (T6040 "Brava Chop") bring-up.

Goal: stop every session from re-deriving the same maps and re-writing the same
guarded-read boilerplate -- and, crucially, keep agents from re-triggering the
known SError traps that wedge the proxy.

Run as a script for a one-line health check:
    M1N1DEVICE=/dev/cu.usbmodemJ22GYCN4YG1 python3 proxyclient/experiments/t6040.py

Import as a library (does NOT open the serial port on import):
    from m1n1.setup import *
    import t6040
    t6040.healthcheck(p, u)
    t6040.read_cluster_pstates(p)          # safe (0x20020 only)
    before = t6040.snapshot(p, [...]); ...; t6040.diff(before, t6040.snapshot(p, [...]))

READ proxyclient/AGENTS.md and src/AGENTS.md first. Every call pokes a real M4.
"""

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from m1n1.proxy import GUARD

# --- Verified topology (see memory t6040-smp-topology, .plans/*-smp-writeup) -------

CHIP_ID = 0x6040

# (name, cluster PSTATE base, "E"/"P"); bases confirmed vs ADT /cpus + live probe.
CLUSTERS = [
    ("ECPU0", 0x210e00000, "E"),
    ("PCPU0", 0x211e00000, "P"),
    ("PCPU1", 0x212e00000, "P"),
]

# smp_id -> (cluster-id, type, MPIDR).  smp_id 9 is absent (Apple non-contiguous).
CPUS = {
    0:  (0, "E", 0x80000000), 1: (0, "E", 0x80000001),
    2:  (0, "E", 0x80000002), 3: (0, "E", 0x80000003),
    4:  (1, "P", 0x80010100), 5: (1, "P", 0x80010101),   # smp_id 4 = boot core
    6:  (1, "P", 0x80010102), 7: (1, "P", 0x80010103), 8: (1, "P", 0x80010104),
    10: (2, "P", 0x80010200), 11: (2, "P", 0x80010201),
    12: (2, "P", 0x80010202), 13: (2, "P", 0x80010203), 14: (2, "P", 0x80010204),
}
BOOT_CPU = 4

# --- Register offsets within a cluster window --------------------------------------

CLUSTER_PSTATE = 0x20020          # validated safe to read on ALL clusters (E and P)

# Offsets that raise an ASYNC SError on P-clusters (t6030 throttle regs whose T6040
# offsets differ). GUARD.SKIP does NOT catch SError -> a read here WEDGES the proxy
# and needs a power-cycle. Do not touch until the T6040 register map is RE'd.
SERROR_OFFSETS_PCLUSTER = {0x40250, 0x40270}   # amx-thrtl, llc-thrtl
# Touched by t6030 code but never verified safe on P-clusters -- treat with caution.
UNVERIFIED_OFFSETS = {0x48400, 0x48408, 0x440f8}


class UnsafeProbe(Exception):
    pass


def is_pcluster(base):
    return any(b == base and t == "P" for _, b, t in CLUSTERS)


def _check_safe(base, off):
    if is_pcluster(base) and off in SERROR_OFFSETS_PCLUSTER:
        raise UnsafeProbe(
            f"0x{base+off:x} (cluster +0x{off:x}) raises SError on P-clusters and "
            f"WILL wedge the proxy. Refusing. See src/AGENTS.md.")


# --- Safe reads --------------------------------------------------------------------

def guarded_read64(p, addr):
    """(value, faulted). Catches SYNCHRONOUS aborts only -- NOT async SError."""
    p.set_exc_guard(GUARD.SKIP | GUARD.SILENT)
    v = p.read64(addr)
    faulted = p.get_exc_count() != 0
    p.set_exc_guard(GUARD.OFF)
    return v, faulted


def read_cluster_reg(p, base, off, force=False):
    """Guarded cluster read that refuses known-SError offsets unless force=True."""
    if not force:
        _check_safe(base, off)
    return guarded_read64(p, base + off)


def decode_cluster_pstate(v):
    return {
        "raw": v,
        "DESIRED1": v & 0x1f,
        "DESIRED2": (v >> 12) & 0xf,
        "SET": bool(v & (1 << 25)),
        "BUSY": bool(v & (1 << 31)),
        "APSC_BUSY": bool(v & (1 << 7)),
    }


def read_cluster_pstates(p):
    """Read CLUSTER_PSTATE (0x20020, safe on all clusters). Returns list of dicts."""
    out = []
    for name, base, typ in CLUSTERS:
        v, fault = guarded_read64(p, base + CLUSTER_PSTATE)
        d = decode_cluster_pstate(v)
        d.update(name=name, base=base, type=typ, fault=fault)
        out.append(d)
    return out


# --- Snapshot / diff (for gated before/after around an approved write) -------------

def snapshot(p, addrs):
    """{addr: value|None(fault)} over an explicit address list (caller ensures safe)."""
    snap = {}
    for a in addrs:
        v, fault = guarded_read64(p, a)
        snap[a] = None if fault else v
    return snap


def diff(before, after):
    changes = []
    for a in sorted(set(before) | set(after)):
        b, x = before.get(a), after.get(a)
        if b != x:
            changes.append((a, b, x))
    return changes


# --- Health check ------------------------------------------------------------------

def healthcheck(p, u, verbose=True):
    """chipid + cpu_features + per-cluster pstate. Returns a dict. All safe reads."""
    cid = p.get_chipid()
    f = p.get_cpu_features()
    info = {
        "chipid": cid,
        "chipid_ok": cid == CHIP_ID,
        "base": u.base,
        "broken_wfi": f.broken_wfi,
        "fast_ipi": f.fast_ipi,
        "pstates": read_cluster_pstates(p),
    }
    if verbose:
        print(f"chipid=0x{cid:x} ({'OK' if info['chipid_ok'] else 'UNEXPECTED'}) "
              f"base=0x{u.base:x} broken_wfi={f.broken_wfi} fast_ipi={f.fast_ipi}")
        for d in info["pstates"]:
            print(f"  {d['name']:5} 0x{d['base']+CLUSTER_PSTATE:x} = 0x{d['raw']:016x} "
                  f"DESIRED1={d['DESIRED1']} SET={int(d['SET'])} BUSY={int(d['BUSY'])}"
                  + ("  [FAULT]" if d["fault"] else ""))
    return info


# --- Run a leaf on a core (real-symbol smp_call preferred; this is the fallback) ---

def run_on_cpu(p, iface, u, asm_src, cpu, *args):
    """Compile `asm_src` (+ implicit ret) into heap and smp_call_sync it on `cpu`.
    Uploads code -- see proxyclient/AGENTS.md. boot core (4) can't call itself."""
    from m1n1.asm import ARMAsm
    code = u.malloc(0x100)
    c = ARMAsm(asm_src + "\n    ret", code)
    iface.writemem(code, c.data)
    p.dc_cvau(code, c.len)
    p.ic_ivau(code, c.len)
    return p.smp_call_sync(cpu, code, *args)


def read_mpidrs(p, iface, u):
    """Read MPIDR_EL1 on every core (leaf via smp_call; boot core via u.exec)."""
    out = {}
    leaf = "mrs x0, mpidr_el1"
    for cpu in sorted(CPUS):
        if cpu == BOOT_CPU:
            out[cpu] = u.exec(leaf) & ((1 << 64) - 1)
        else:
            out[cpu] = run_on_cpu(p, iface, u, leaf, cpu) & ((1 << 64) - 1)
    return out


if __name__ == "__main__":
    from m1n1.setup import *  # opens the serial port
    healthcheck(p, u)
