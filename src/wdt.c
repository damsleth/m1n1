/* SPDX-License-Identifier: MIT */

#include "wdt.h"
#include "adt.h"
#include "types.h"
#include "utils.h"

#define WDT_COUNT 0x10
#define WDT_ALARM 0x14
#define WDT_CTL   0x1c

// Apple's watchdog counter is clocked by the ~24 MHz always-on reference. Only
// used to convert seconds -> alarm ticks for wdt_arm_secs().
#define WDT_CLK_HZ 24000000

static u64 wdt_base = 0;

// Populate wdt_base from the ADT if it isn't already known. Returns true on
// success. wdt_disable() (run at startup) normally sets it, but wdt_arm_secs()
// may be called on a path where that lookup was skipped or failed.
static bool wdt_find_base(void)
{
    if (wdt_base)
        return true;

    int path[8];
    int node = adt_path_offset_trace(adt, "/arm-io/wdt", path);
    if (node < 0)
        return false;

    if (adt_get_reg(adt, path, "reg", 0, &wdt_base, NULL))
        return false;

    return wdt_base != 0;
}

void wdt_arm_secs(u32 secs)
{
    if (!wdt_find_base()) {
        printf("WDT: could not arm, base unknown\n");
        return;
    }

    write32(wdt_base + WDT_ALARM, (u32)((u64)secs * WDT_CLK_HZ));
    write32(wdt_base + WDT_COUNT, 0);
    write32(wdt_base + WDT_CTL, 4);
    printf("WDT: armed for ~%us (warm reset on hang)\n", secs);
}

void wdt_disable(void)
{
    int path[8];
    int node = adt_path_offset_trace(adt, "/arm-io/wdt", path);

    if (node < 0) {
        printf("WDT node not found!\n");
        return;
    }

    if (adt_get_reg(adt, path, "reg", 0, &wdt_base, NULL)) {
        printf("Failed to get WDT reg property!\n");
        return;
    }

    printf("Primary WDT register @ 0x%lx\n", wdt_base);
    write32(wdt_base + WDT_CTL, 0);
    printf("Primary WDT disabled\n");

    // disable secondary watchdog if wdt-version is 2 or 3
    u32 wdt_version;
    if (ADT_GETPROP(adt, node, "wdt-version", &wdt_version) < 0)
        return;

    if (wdt_version == 2 || wdt_version == 3) {
        u64 wdt_2nd = 0;
        if (adt_get_reg(adt, path, "reg", 2, &wdt_2nd, NULL)) {
            printf("Failed to get WDT reg[2] property!\n");
            return;
        }

        printf("Secondary WDT register @ 0x%lx\n", wdt_2nd);
        write32(wdt_2nd, 0);
        printf("Secondary WDT disabled\n");
    }
}

void wdt_reboot(void)
{
    if (!wdt_base)
        return;

    write32(wdt_base + WDT_ALARM, 0x100000);
    write32(wdt_base + WDT_COUNT, 0);
    write32(wdt_base + WDT_CTL, 4);
}
