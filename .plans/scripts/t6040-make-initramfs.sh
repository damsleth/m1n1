#!/usr/bin/env bash
# Replace /init in the known-good proof initramfs with the persistent-shell init.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${OUT:-/Users/damsleth/Code/linux-build-out}
BASE=${BASE:-$OUT/initramfs.cpio.gz}
DEST=${DEST:-$OUT/initramfs-dcuart.cpio.gz}
INIT_SOURCE=${INIT_SOURCE:-$ROOT/.plans/scripts/t6040-init-dcuart}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

LC_ALL=C gzip -dc "$BASE" | (cd "$TMP" && LC_ALL=C bsdtar -xf -)
install -m 0755 "$INIT_SOURCE" "$TMP/init"

# Optional space-separated EXTRA_FILES="src:dest src:dest" copied into the image.
for pair in ${EXTRA_FILES:-}; do
    src=${pair%%:*}; dest=${pair#*:}
    mkdir -p "$TMP/$(dirname "$dest")"
    install -m 0644 "$src" "$TMP/$dest"
done

(cd "$TMP" && LC_ALL=C find . -print | LC_ALL=C sort | \
    LC_ALL=C cpio -o -H newc 2>/dev/null | gzip -9) >"$DEST"

echo "initramfs -> $DEST"
shasum -a 256 "$DEST"
