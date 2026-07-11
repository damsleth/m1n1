/* SPDX-License-Identifier: MIT */

#include "dapf.h"
#include "adt.h"
#include "assert.h"
#include "malloc.h"
#include "memory.h"
#include "pmgr.h"
#include "string.h"
#include "utils.h"

struct dapf_t8020_config {
    u64 start;
    u64 end;
    u8 unk1;
    u8 r0_hi;
    u8 r0_lo;
    u8 unk2;
    u32 r4;
} PACKED;

static int dapf_init_t8020(const char *path, u64 base, int node)
{
    u32 length;
    const char *prop = "filter-data-instance-0";
    const struct dapf_t8020_config *config = adt_getprop(adt, node, prop, &length);

    if (!config || !length || (length % sizeof(*config)) != 0) {
        printf("dapf: Error getting ADT node %s property %s.\n", path, prop);
        return -1;
    }

    int count = length / sizeof(*config);

    for (int i = 0; i < count; i++) {
        write32(base + 0x04, config[i].r4);
        write64(base + 0x08, config[i].start);
        write64(base + 0x10, config[i].end);
        write32(base + 0x00, (config[i].r0_hi << 4) | config[i].r0_lo);
        base += 0x40;
    }
    return 0;
}

struct dapf_t8110_config {
    u64 start;
    u64 end;
    u32 r20;
    u32 unk1;
    u32 r4;
    u32 unk2[5];
    u8 unk3;
    u8 r0_hi;
    u8 r0_lo;
    u8 unk4;
} PACKED;

struct dapf_t8110b_config {
    u64 start;
    u64 end;
    u32 r20;
    u32 unk1;
    u32 r4;
    u32 unk2[5];
    u8 unk3;
    u8 r0_hi;
    u8 r0_lo;
    u8 unk4;
    u32 pad;
} PACKED;

static int dapf_init_t8110a(u64 base, struct dapf_t8110_config *config, u32 length)
{
    int count = length / sizeof(*config);

    for (int i = 0; i < count; i++) {
        write32(base + 0x04, config[i].r4);
        write64(base + 0x08, config[i].start);
        write64(base + 0x10, config[i].end);
        write32(base + 0x00, (config[i].r0_hi << 4) | config[i].r0_lo);
        write32(base + 0x20, config[i].r20);
        base += 0x40;
    }
    return 0;
}

static int dapf_init_t8110b(u64 base, struct dapf_t8110b_config *config, u32 length)
{
    int count = length / sizeof(*config);

    for (int i = 0; i < count; i++) {
        write32(base + 0x04, config[i].r4);
        write64(base + 0x08, config[i].start);
        write64(base + 0x10, config[i].end);
        write32(base + 0x00, (config[i].r0_hi << 4) | config[i].r0_lo);
        write32(base + 0x20, config[i].r20);
        base += 0x40;
    }
    return 0;
}

static int dapf_init_t8110(const char *path, u64 base, int node)
{
    u32 length;
    const char *prop = "dapf-instance-0";
    const void *config = adt_getprop(adt, node, prop, &length);

    if (!config || !length) {
        printf("dapf: Error getting ADT node %s property %s.\n", path, prop);
        return -1;
    }

    // The least common multiple of 52 and 56 is 728 which is in the range of
    // the observed lengthe for "dapf-instance-0". The 52 byte variant is more
    // common and prefering that works so far.
    if (length % sizeof(struct dapf_t8110_config) == 0) {
        return dapf_init_t8110a(base, (struct dapf_t8110_config *)config, length);
    } else if (length % sizeof(struct dapf_t8110b_config) == 0) {
        return dapf_init_t8110b(base, (struct dapf_t8110b_config *)config, length);
    } else {
        printf("dapf: Invalid length for %s property %s\n", path, prop);
        return -1;
    }
}

int dapf_init(const char *path, int index)
{
    int ret;
    int dart_path[8];
    int node = adt_path_offset_trace(adt, path, dart_path);
    if (node < 0) {
        printf("dapf: Error getting DAPF %s node.\n", path);
        return -1;
    }

    u32 pwr;
    if (!adt_getprop(adt, node, "clock-gates", &pwr))
        pwr = 0;
    if (pwr && (pmgr_adt_power_enable(path) < 0))
        return -1;

    u64 base;
    if (adt_get_reg(adt, dart_path, "reg", index, &base, NULL) < 0) {
        printf("dapf: Error getting DAPF %s base address.\n", path);
        return -1;
    }

    if (adt_is_compatible(adt, node, "dart,t8020")) {
        ret = dapf_init_t8020(path, base, node);
    } else if (adt_is_compatible(adt, node, "dart,t6000")) {
        ret = dapf_init_t8020(path, base, node);
    } else if (adt_is_compatible(adt, node, "dart,t8110")) {
        ret = dapf_init_t8110(path, base, node);
    } else {
        printf("dapf: DAPF %s at 0x%lx is of an unknown type\n", path, base);
        return -1;
    }

    if (pwr)
        pmgr_adt_power_disable(path);

    if (!ret)
        printf("dapf: Initialized %s\n", path);

    return ret;
}

struct entry {
    const char *path;
    int index;
    // Initializing this DAPF's filter raises a fatal async L2C SError on M4-family
    // SoCs (see m4_dapf_broken below). Skip it there.
    bool m4_broken;
};

struct entry dapf_entries[] = {
    {"/arm-io/dart-aop", 1, true},  {"/arm-io/dart-mtp", 1, false},
    {"/arm-io/dart-pmp", 1, false}, {"/arm-io/dart-isp", 5, true},
    {"/arm-io/dart-isp0", 5, true}, {NULL, -1, false},
};

// On the M4 generation (t6040 M4 Pro, t8132 "Neo" M4) initializing the dart-aop
// (and dart-isp) DAPF page-fault filters raises an imprecise async L2C
// ACCESS_FAULT SError that kills m1n1 during kboot handoff (L2C_ERR_STS 0x82).
// The dart-mtp/dart-pmp filters init fine and mtp needs them (without dapf the
// mtp only comes up with iommu.passthrough=1). Empirically found by yuka on
// t8132 and confirmed on t6040; there is no clean ADT signal for it, so gate on
// chip_id. Revisit if the aop/isp filters are ever needed on these SoCs.
static bool m4_dapf_broken(void)
{
    return chip_id == T6040 || chip_id == T8132;
}

int dapf_init_all(void)
{
    int ret = 0;
    int count = 0;
    struct entry *entry = dapf_entries;
    bool skip_broken = m4_dapf_broken();

    while (entry->path != NULL) {
        if (adt_path_offset(adt, entry->path) < 0) {
            entry++;
            continue;
        }
        if (entry->m4_broken && skip_broken) {
            printf("dapf: Skipping %s (async L2C SError on M4-family SoCs)\n", entry->path);
            entry++;
            continue;
        }
        if (dapf_init(entry->path, entry->index) < 0) {
            ret = -1;
        }
        entry++;
        count += 1;
    }
    return ret ? ret : count;
}
