/* SPDX-License-Identifier: MIT */

#ifndef __WDT_H__
#define __WDT_H__

#include "types.h"

void wdt_disable(void);
void wdt_reboot(void);
// Arm the primary watchdog to fire (warm reset) after `secs` seconds unless
// something pets/disables it first. Used to auto-recover from a hung kernel
// during bring-up: a hang -> watchdog warm reset (DRAM retained) -> back to the
// m1n1 proxy. Assumes the ~24 MHz WDT reference clock; tune WDT_CLK_HZ if the
// real timeout differs.
void wdt_arm_secs(u32 secs);

#endif
