#!/usr/bin/env bash
# Replace /init in the known-good proof initramfs with the persistent-shell init.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OUT:-/Users/damsleth/Code/linux-build-out}
BASE=${BASE:-$OUT/initramfs.cpio.gz}
DEST=${DEST:-$OUT/initramfs-watchdog.cpio.gz}
INIT_SOURCE=${INIT_SOURCE:-$ROOT/.plans/t6040-init}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

LC_ALL=C gzip -dc "$BASE" | (cd "$TMP" && LC_ALL=C bsdtar -xf -)
install -m 0755 "$INIT_SOURCE" "$TMP/init"

(cd "$TMP" && LC_ALL=C find . -print | LC_ALL=C sort | \
    LC_ALL=C cpio -o -H newc 2>/dev/null | gzip -9) >"$DEST"

echo "initramfs -> $DEST"
shasum -a 256 "$DEST"
