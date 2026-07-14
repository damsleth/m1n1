/* SPDX-License-Identifier: MIT */

#include "adt.h"
#include "cpu_regs.h"
#include "tunables.h"
#include "types.h"
#include "utils.h"

struct tunable_info {
    int node_offset;
    int node_path[8];
    const u32 *tunable_raw;
    u32 tunable_len;
};

static int tunables_adt_find(const char *path, const char *prop, struct tunable_info *info,
                             u32 item_size)
{
    info->node_offset = adt_path_offset_trace(adt, path, info->node_path);
    if (info->node_offset < 0) {
        printf("tunable: unable to find ADT node %s.\n", path);
        return -1;
    }

    info->tunable_raw = adt_getprop(adt, info->node_offset, prop, &info->tunable_len);
    if (info->tunable_raw == NULL || info->tunable_len == 0) {
        printf("tunable: Error getting ADT node %s property %s .\n", path, prop);
        return -1;
    }

    if (info->tunable_len % item_size) {
        printf("tunable: tunable length needs to be a multiply of %d but is %d\n", item_size,
               info->tunable_len);
        return -1;
    }

    info->tunable_len /= item_size;

    return 0;
}

struct tunable_global {
    u32 reg_idx;
    u32 offset;
    u32 mask;
    u32 value;
} PACKED;

int tunables_apply_global(const char *path, const char *prop)
{
    struct tunable_info info;

    if (tunables_adt_find(path, prop, &info, sizeof(struct tunable_global)) < 0)
        return -1;

    const struct tunable_global *tunables = (const struct tunable_global *)info.tunable_raw;
    for (u32 i = 0; i < info.tunable_len; ++i) {
        const struct tunable_global *tunable = &tunables[i];

        u64 addr;
        if (adt_get_reg(adt, info.node_path, "reg", tunable->reg_idx, &addr, NULL) < 0) {
            printf("tunable: Error getting regs with index %d\n", tunable->reg_idx);
            return -1;
        }

        mask32(addr + tunable->offset, tunable->mask, tunable->value);
    }

    return 0;
}

struct tunable_local {
    u32 offset;
    u32 size;
    u64 mask;
    u64 value;
} PACKED;

static int tunables_apply_local_addr_internal(const char *path, const char *prop, uintptr_t base,
                                              bool trace, bool write)
{
    struct tunable_info info;

    if (tunables_adt_find(path, prop, &info, sizeof(struct tunable_local)) < 0)
        return -1;

    if (trace && write) {
        /*
         * T6040 can report bad fabric accesses as an imprecise asynchronous
         * L2C SError. Fence the preceding PMGR work and check for an already
         * pending error before attributing one to the first tunable below.
         * Do not clear the status: preserve it for the exception report.
         */
        sysop("dsb sy");
        u64 l2c_err_sts = mrs(SYS_IMP_APL_L2C_ERR_STS);
        if (l2c_err_sts) {
            printf("tunable: %s pending L2C_ERR_STS=0x%lx before first RMW\n", prop, l2c_err_sts);
            return -1;
        }
    }

    const struct tunable_local *tunables = (const struct tunable_local *)info.tunable_raw;
    for (u32 i = 0; i < info.tunable_len; ++i) {
        const struct tunable_local *tunable = &tunables[i];
        uintptr_t addr = base + tunable->offset;

        if (trace)
            printf("tunable: %s[%d] addr=0x%lx size=%d mask=0x%lx value=0x%lx\n", prop, i, addr,
                   tunable->size, tunable->mask, tunable->value);

        if (write) {
            switch (tunable->size) {
                case 1:
                    mask8(addr, tunable->mask, tunable->value);
                    break;
                case 2:
                    mask16(addr, tunable->mask, tunable->value);
                    break;
                case 4:
                    mask32(addr, tunable->mask, tunable->value);
                    break;
                case 8:
                    mask64(addr, tunable->mask, tunable->value);
                    break;
                default:
                    printf("tunable: unknown tunable size 0x%08x\n", tunable->size);
                    return -1;
            }
        }

        if (trace && write) {
            /* Force this RMW to complete before sampling the async status. */
            sysop("dsb sy");
            u64 l2c_err_sts = mrs(SYS_IMP_APL_L2C_ERR_STS);
            if (l2c_err_sts) {
                printf("tunable: %s[%d] pending L2C_ERR_STS=0x%lx\n", prop, i, l2c_err_sts);
                return -1;
            }
        }
        if (trace)
            printf("tunable: %s[%d] done\n", prop, i);
    }
    return 0;
}

int tunables_apply_local_addr(const char *path, const char *prop, uintptr_t base)
{
    return tunables_apply_local_addr_internal(path, prop, base, false, true);
}

int tunables_apply_local_addr_trace(const char *path, const char *prop, uintptr_t base)
{
    return tunables_apply_local_addr_internal(path, prop, base, true, true);
}

int tunables_read_first_local_addr_trace(const char *path, const char *prop, uintptr_t base)
{
    struct tunable_info info;

    if (tunables_adt_find(path, prop, &info, sizeof(struct tunable_local)) < 0)
        return -1;

    const struct tunable_local *tunable = (const struct tunable_local *)info.tunable_raw;
    uintptr_t addr = base + tunable->offset;

    /*
     * Bring-up diagnostic: split the first tunable RMW into a read-only run.
     * The address, width, and property entry all come from the ADT; callers
     * must stop before applying this or any later tunable.
     */
    printf("tunable: %s[0] read-only addr=0x%lx size=%d mask=0x%lx value=0x%lx\n", prop,
           addr, tunable->size, tunable->mask, tunable->value);

    sysop("dsb sy");
    u64 l2c_err_sts = mrs(SYS_IMP_APL_L2C_ERR_STS);
    if (l2c_err_sts) {
        printf("tunable: %s pending L2C_ERR_STS=0x%lx before first read\n", prop, l2c_err_sts);
        return -1;
    }

    u64 read_value;
    switch (tunable->size) {
        case 1:
            read_value = read8(addr);
            break;
        case 2:
            read_value = read16(addr);
            break;
        case 4:
            read_value = read32(addr);
            break;
        case 8:
            read_value = read64(addr);
            break;
        default:
            printf("tunable: unknown tunable size 0x%08x\n", tunable->size);
            return -1;
    }

    sysop("dsb sy");
    l2c_err_sts = mrs(SYS_IMP_APL_L2C_ERR_STS);
    if (l2c_err_sts) {
        printf("tunable: %s[0] read pending L2C_ERR_STS=0x%lx\n", prop, l2c_err_sts);
        return -1;
    }

    printf("tunable: %s[0] read value=0x%lx done\n", prop, read_value);
    return 0;
}

int tunables_apply_local(const char *path, const char *prop, u32 reg_offset)
{
    struct tunable_info info;

    if (tunables_adt_find(path, prop, &info, sizeof(struct tunable_local)) < 0)
        return -1;

    u64 base;
    if (adt_get_reg(adt, info.node_path, "reg", reg_offset, &base, NULL) < 0) {
        printf("tunable: Error getting regs\n");
        return -1;
    }

    return tunables_apply_local_addr(path, prop, base);
}

int tunables_apply_local_trace(const char *path, const char *prop, u32 reg_offset)
{
    struct tunable_info info;

    if (tunables_adt_find(path, prop, &info, sizeof(struct tunable_local)) < 0)
        return -1;

    u64 base;
    if (adt_get_reg(adt, info.node_path, "reg", reg_offset, &base, NULL) < 0) {
        printf("tunable: Error getting regs\n");
        return -1;
    }

    return tunables_apply_local_addr_trace(path, prop, base);
}

int tunables_trace_local_dry_run(const char *path, const char *prop, u32 reg_offset)
{
    struct tunable_info info;

    if (tunables_adt_find(path, prop, &info, sizeof(struct tunable_local)) < 0)
        return -1;

    u64 base;
    if (adt_get_reg(adt, info.node_path, "reg", reg_offset, &base, NULL) < 0) {
        printf("tunable: Error getting regs\n");
        return -1;
    }

    return tunables_apply_local_addr_internal(path, prop, base, true, false);
}
