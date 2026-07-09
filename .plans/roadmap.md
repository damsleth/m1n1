# T6040 (M4 Pro, Mac16,8 / j614s) — roadmap: first light → full Linux desktop

End-goal: a bootable Linux distro on this MacBook Pro 16" M4 Pro with GPU accel,
WiFi, Bluetooth, keyboard/trackpad, audio, webcam, power management — daily-driver
comfort comparable to macOS.

Written 2026-07-10. Companion docs: `t6040-bringup-plan.md` (Stage A detail),
`2026-07-09-t6040-first-light-session.md` (what already happened).

## Where we are

**First light achieved 2026-07-09.** m1n1 v1.6.0+ boots via raw kmutil enrollment:
fb console 3024x1964, AIC3 up, pmgr 485 devices, 3 USB DARTs, "Running proxy...".
Verified: chip-id 0x6040, `EARLY_UART_BASE`. Unverified: SMP start offset.
Known gap already logged by m1n1 itself: `cpufreq: Chip 0x6040 is unsupported`.

One structural constraint colors everything below: **M4 = raw boot only** (SPTM
owns the mach-o path). Apple-private sysregs are locked. Linux itself doesn't
care (it runs at EL2/EL1 normally), but: no hypervisor tracing of macOS drivers
on this machine — the classic Asahi reverse-engineering tool (`hv` + tracers) is
crippled on M4. Reverse engineering of new hardware blocks largely has to happen
on M1/M2/M3 machines upstream, or via static ADT/firmware analysis. This is the
single biggest reason most of Stages E–G are "track upstream" rather than "build
it here".

## Stage map

```
A. Proxy solid ──► B. m1n1 Linux-boot ──► C. Kernel DT + boot ──► D. Storage/USB/HID/console
                                                                        │
        ┌───────────────────────────────────────────────────────────────┤
        ▼                          ▼                        ▼           ▼
E. WiFi + Bluetooth        F. GPU (long pole)        G. Audio/ISP/PM   H. Distro integration
```

A→D are sequential. E/F/G parallelize after D. H wraps it all.

---

## Stage A — finish the current plan (proxy solid, all cores)

*This is `t6040-bringup-plan.md` phases 2–4. Days, not weeks.*

- [ ] Second machine + `shell.py` → proxy prompt (cherry-pick PR #616 if SPMI chokes)
- [ ] `smp.start_secondaries()` — validates `CPU_START_OFF_T6031` 0x88000 reuse
      (src/smp.c:296), the last untested constant. All 14 cores or a one-line fix.
- [ ] `chainload.py -r build/m1n1.bin` reliable → 10-second dev loop, kmutil retired
- [ ] Upstream: confirmed constants, features_m4 notes, raw-boot-on-26.2 doc note

**Exit:** proxy + chainload stable across reboots, 14/14 cores.

## Stage B — m1n1 grows Linux-boot support for T6040

*What `kboot` needs before it can hand a kernel a usable machine. This is the
M3 template (commits 83364d0→5393f41) replayed on T6040. Weeks. All of it is
doable solo with the proxy + ADT dumps; this is the highest-leverage local work.*

1. **cpufreq** (`src/cpufreq.c`) — T6040 cluster tables/DVFS init. The boot log
   already names this gap. Extract states from ADT `/arm-io/pmgr` + cluster nodes;
   follow the t6031 entry as template.
2. **MCC** (`src/mcc.c`) — memory cache controller layout, `mcc,t8132`-family.
   Needed for memory BW / DCP later.
3. **PCIe** (`src/pcie.c` + tunables) — `apcie` ADT bring-up for T6040. This is
   the WiFi/BT prerequisite: both sit on the Apple PCIe bus.
4. **ATC/USB tunables + DART config** for the kernel handoff.
5. **kboot FDT init** (`src/kboot.c` and friends) — `apple,t6040` compatibles,
   display reserved-regions handoff (framebuffer carveout), DCP node fixups, ISP
   preallocation, GPU carveout, SEP/SMC nodes, spin-table/CPU-release method.
6. **Python side** (`proxyclient/m1n1/`) — T6040 chip knowledge for the tools
   used to dump/verify all of the above.

**Exit:** m1n1 boots a kernel image with a correct, complete FDT; kernel gets to
early console. (Testable incrementally against Stage C.)

## Stage C — kernel devicetree + core boot (Asahi kernel tree)

*Target: linux-asahi boots to a shell on this machine. Weeks, parallel with B.*

- **Device trees:** `arch/arm64/boot/dts/apple/t6040.dtsi` + `t6040-j614s.dts`,
  templated from t6031 (M3 Pro/Max) and t602x. ADT quirk noted in session log
  helps: arm-io is literally `t6041` compat, CPUs reuse M3 names — the SoC is a
  Brava chop, so t6031 DTs are a close starting point.
- **AIC3:** boot log says AIC3 (vs AIC2 on M1/M2). Check the Asahi tree's M3-era
  `apple-aic` state; if AIC3 isn't there yet this is a real driver task, and it
  blocks *everything* (no interrupts, no boot).
- **Core platform drivers** (mostly compat-string + minor deltas on existing
  Asahi drivers): UART, watchdog, PMGR power domains, pinctrl/GPIO, I2C/SPI,
  mailbox/RTKit (new firmware version strings for 26.x!), DART t8110, cpufreq
  (`apple,cluster-cpufreq`), SMC, SPMI/PMU.
- **RTKit firmware versioning:** every coprocessor (NVMe/ANS, SMC, DCP, ISP…)
  ships firmware from the macOS 26.x install; Asahi drivers whitelist known
  ABI versions. Expect a steady trickle of "add fw 26.x compat" patches.

**Exit:** linux-asahi + our DT boots to initramfs shell over USB gadget/serial,
all 14 cores online, cpufreq working.

## Stage D — storage, USB, HID, display console (usable machine)

*The "it's a real computer now" stage. Weeks.*

- **NVMe** (apple-nvme + SART + ANS RTKit): internal SSD. Gate for installing
  a rootfs on disk.
- **USB** (dwc3 + ATC PHY): external keyboard/disk/ethernet from day one; also
  the USB-gadget console m1n1 already proves works.
- **Internal keyboard + trackpad:** M2+ MacBook Pros use **dockchannel-HID**
  (`apple,dockchannel-hid`); j614s almost certainly the same. Verify the ADT
  node, add compat + HID descriptors if the MTP firmware changed.
- **Display:** two steps.
  1. `simpledrm` on the m1n1-provided framebuffer — works immediately, no
     driver; gives a desktop-capable (unaccelerated) console. This alone plus
     NVMe/USB/HID = installable, usable-in-anger machine.
  2. **DCP driver** for real display control (brightness, DPMS, mode switch,
     external DP alt-mode). Firmware-version-locked; M4 + macOS 26.x firmware
     support must exist in the asahi DCP driver — likely upstream-tracking work.
- **SMC:** power button, lid, battery/charger via macsmc — mostly compat work.

**Exit:** boot from internal NVMe to a desktop on simpledrm, working built-in
keyboard/trackpad, battery status. Daily-drivable without GPU/WiFi (USB ethernet).

## Stage E — WiFi + Bluetooth

*Moderate; mostly enablement, not R&E — the drivers exist. Depends on Stage B PCIe.*

- Identify the chip from ADT (`/arm-io/apcie/...`/wlan node). M3 machines ship
  BCM4388; M4 is the same family or its successor. 
- **WiFi:** `brcmfmac` PCIe path — add chip/firmware IDs if new, plus board
  calibration blobs. Firmware comes from the macOS install; the Asahi
  `asahi-fwextract`/vendor-firmware flow needs j614s mappings.
- **Bluetooth:** `hci_bcm4377` — same story, add the new variant ID.
- If the chip generation is genuinely new (not just a new ID), this becomes
  upstream-collab work — but Broadcom generations have been incremental so far.

**Exit:** WiFi associates + BT pairs on mainline-asahi drivers with extracted fw.

## Stage F — GPU (the long pole)

*This is the item that decides when "all the comforts" arrives. Not a solo project.*

- M4 GPU is the G15/G16 family (M3 introduced Dynamic Caching — a large
  architectural break from the G13/G14 the shipping drm/asahi driver grew up on).
  Kernel driver (Rust, drm/asahi) + firmware ABI + Mesa compiler (agx) all need
  the M3/M4-generation work that the upstream Asahi team has been driving since
  the M3 bring-up; the 2026-06 progress report explicitly says M4 groundwork is
  being laid.
- Firmware ABI is version-locked per macOS release → our 26.x install needs
  explicit support.
- **Realistic role for this machine:** be the T6040 test mule — provide ADT/fw
  dumps, run bring-up branches, report. Writing a G16 GPU driver from scratch
  here is out of scope; the raw-boot hypervisor limitation (no XNU tracing on
  M4) means even upstream does the RE on other hardware.
- **Until it lands:** simpledrm desktop. KDE on simpledrm at 3024x1964 is
  serviceable; no video decode offload, no games, high CPU for compositing.

**Exit:** drm/asahi + Mesa honeykrisp/agx running the desktop with GL/Vulkan.

## Stage G — comforts: audio, camera, power

- **Speakers/headphones:** macaudio stack (tas2764 amps + cs42l84 jack codec are
  the recurring parts) — needs j614s DT wiring, `speakersafetyd` limits, and an
  **asahi-audio DSP profile measured for this exact chassis** (each model gets
  tuned EQ; 16" M4 Pro won't exist yet). Speaker safety is a hard gate: no
  profile → speakers stay muted. Headphones/USB audio work much earlier.
- **Webcam:** apple-isp driver + m1n1 ISP prealloc (Stage B item) + new sensor/
  firmware handling for the 12MP Center Stage camera. Upstream-tracking.
- **Power management:** s2idle suspend via SMC (works on M1/M2, needs T6040
  validation); `features_m4` sleep_mode currently SLEEP_NONE in m1n1 — deep-WFI/
  cpuidle needs careful enablement under locked sysregs. Battery life tuning
  (devfreq, runtime PM on DARTs/coprocessors) trails everything else.
- **Explicitly never (or SEP-blocked):** Touch ID. **Late/limited:** Thunderbolt
  tunneling (USB3/DP alt-mode work; full TB is still open upstream), video
  decode engines (AVD is M1/M2-era work, M4 unexplored).

## Stage H — distro integration ("bootable Linux distro")

- **asahi-installer:** must learn raw-boot-object enrollment for M4 (it enrolls
  mach-o m1n1 today — that path is *gone* on this machine) + Mac16,8 device
  metadata + firmware extraction for 26.x. This is a real, non-optional work item
  and mostly upstream-installer territory.
- **U-Boot:** T6040 support (usually near-free once m1n1's FDT + dwc3 are right)
  → standard EFI boot flow → GRUB/systemd-boot.
- **Fedora Asahi Remix:** kernel with all of the above, j614s asahi-audio
  profile, mesa builds, calamares/initial-setup — mostly automatic once the
  pieces exist upstream.
- Interim personal path (before official installer support): keep the APFS
  m1n1 volume + kmutil raw enrollment, m1n1 chainloads U-Boot/kernel from the
  existing setup. That's a "my machine boots Linux" milestone long before
  "a distro supports this machine".

## Dependencies & effort summary

| Stage | Blocked by | Who realistically does it | Effort |
|---|---|---|---|
| A proxy/SMP | — | you, now | days |
| B m1n1 kboot | A | you (best solo leverage) | weeks |
| C kernel DT/boot | B partial, AIC3 driver | you + upstream | weeks |
| D NVMe/USB/HID/simpledrm | C | you + upstream compat patches | weeks |
| E WiFi/BT | B (PCIe), D | mostly enablement, you | days–weeks |
| F GPU | upstream M3/M4 GPU program | upstream; you = test mule | months (external) |
| G audio/ISP/PM | D; audio profile needs hw measurement | mixed | weeks–months |
| H installer/distro | all above | upstream + you for j614s bits | weeks (external) |

## Risks (beyond the bring-up plan's table)

| Risk | Mitigation |
|---|---|
| No hypervisor tracing on M4 (SPTM) starves RE for new blocks | Static ADT/fw analysis; lean on upstream's M3 machines where blocks are shared |
| macOS 26.x firmware ABIs unsupported by every RTKit driver | Expect per-driver fw-version patches; keep the m1n1 volume's macOS pinned once things work |
| AIC3 unsupported in kernel | Check asahi tree first — if missing, it's the Stage C critical path; raise on #asahi-dev early |
| GPU timeline entirely external | simpledrm desktop is the honest interim; don't plan around a date |
| Speaker safety profile requires acoustic measurement rig | Use headphones/USB audio until a j614s profile exists upstream |

## Operating principle

Everything in Stages A–B and the DT/enablement halves of C–E is scarce-hardware
work where a T6040 owner adds unique value — do it, upstream it fast, coordinate
on #asahi-dev before writing anything big. Stages F and the deep halves of G–H
are upstream programs — track, test, report, don't fork.
