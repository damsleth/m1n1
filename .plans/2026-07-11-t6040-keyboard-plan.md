# T6040 J614s internal keyboard/trackpad bring-up

Status 2026-07-11: Stage 1 complete. DockChannel/ASC-mailbox infrastructure
booted safely, then the corrected built-in DART boot also reached persistent
userspace. Hardware log:

`apple-dart 514800000.iommu: DART [pagesize 4000, 16 streams, bypass support: 1, bypass forced: 1, AS 42 -> 42] initialized`

Full MTP/HID remains untested.

## Source and hardware evidence

The J614s ADT describes the M2+ style MTP/DockChannel HID path:

- `/arm-io/mtp`: `iop,ascwrap-v6`, ASC `0x514600000`, mailbox at
  `0x514608000`, IRQs 793/792/795/794.
- `/arm-io/dart-mtp`: `dart,t8110`, base `0x514800000`, IRQ 775, SID 0,
  `sid-count=16`.
- `/arm-io/dockchannel-mtp`: `dockchannel,t8002`, IRQ/config/data at
  `0x514b14000`/`0x514b30000`/`0x514b34000`, IRQ 776, FIFO size `0x800`.
- MTP firmware SRAM segments 0 and 1 are contiguous at
  `0x514c00000..0x514cac000`.
- Transport children announced by the ADT are `multi-touch`, `keyboard`,
  `stm`, `actuator`, and `tp-accel`.

Kernel code comes from the local July 2026 `origin/dockchannel` branch:
DockChannel mailbox, RTKit TraceKit endpoint, HID Apple quirks, and the new
DockChannel HID transport. `.plans/t6040-kbuild.sh` imports those four commits
only when `DOCKCHANNEL=1`.

## Isolated artifacts

- `Image-keyboard` SHA-256:
  `f0c8f35294e4354b12e474a100dc0a880212390eec33653f1164a1e8d240f36a`
- Full HID DTB `t6040-j614s-kbd.dtb` SHA-256:
  `e24d1302938e366f8612b393012fa7a4b77d59eacceecaa2b48b5534cf1d1e83`
- Infrastructure-only DTB: `t6040-j614s-kbd-infra.dtb`
- Diagnostic/persistent initramfs: `initramfs-keyboard.cpio.gz` SHA-256:
  `2691977ec50c2d394786501be777967b3ad70193a3669ba8b5285995d2eac573`

The known-good framebuffer DTB remains untouched at SHA-256 `7bddc211...`.

## Hardware test stages

### Stage 1: infrastructure only

Enables the T8110 DART, ASC mailbox, and DockChannel mailbox. MTP HID remains
disabled, so the helper CPU is not started and no protocol/FIFO traffic occurs.

DockChannel probe writes exactly:

- `0x514b14000 = 0x00000000` (IRQ mask)
- `0x514b14004 = 0xffffffff` (clear latched IRQ flags, W1C)

ASC mailbox probe only maps resources and registers IRQs; it does not write.

The standard `apple,t8110-dart` reset path (ADT says 16 SIDs) writes:

- zero to TCR `0x514801000..0x51480103c` and TTBR
  `0x514801400..0x51480143c`, 4-byte stride;
- `0xffffffff` to stream-enable `0x514800c00`;
- the value read from error status back to W1C `0x514800100`;
- zero to error mask `0x514800104`;
- TLB flush commands `0x100|sid` for SID 0..15 to `0x514800080`.

This is the normal mature T8110 DART driver path, but is still the principal
risk because m1n1 cannot touch T6040's DART-MTP DAPF entry without an async
SError. Do not run without the maintainer watching the display.

### Stage 2: full HID

Adds MTP/RTKit and DockChannel traffic. The first additional fixed writes are:

- `0x514801000 = 0x6` (SID 0 identity/bypass TCR; the Stage-1 probe reports
  bypass support and forced bypass because the DART uses 16K pages)
- `0x514b30004 = 1` (DockChannel RX threshold)
- `0x514b14004 = 0x8`, then `0x514b14000 = 0x8` (clear/unmask RX)
- `0x514600044 = 0x10` (MTP ASC CPU RUN)

After that, standard RTKit sends dynamic messages through the ASC mailbox at
`0x514608000`, and DockChannel HID sends checksummed protocol frames only to
the known FIFO data ports `0x514b34010`/`0x514b34004`. TX threshold/IRQ writes
use `0x514b30000 = 0x800`, `0x514b14004 = 0x4`, and IRQ mask `0xc`.

The diagnostic initramfs waits five seconds, prints matching dmesg plus
`/proc/bus/input/devices`, then leaves a watchdog-petted shell for a key test.
