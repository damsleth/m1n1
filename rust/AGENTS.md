# AGENTS.md — rust (m1n1 Rust lib, `librust.a`)

Static lib linked into m1n1. Built by the top Makefile (`cargo build … --target
aarch64-unknown-none-softfloat`), default `make` pulls the `chainload` feature
(fatfs, uuid).

## Toolchain — NIGHTLY is mandatory

`src/lib.rs` uses `#![feature(...)]` (cfg_version, alloc_error_handler), so a
stable toolchain will not compile. On this host it's already set up:
- `rustup override set nightly` in the repo (no tracked toolchain file).
- `rustup target add aarch64-unknown-none-softfloat` on nightly.
- Homebrew `rust` was removed (broken dyld vs LLVM 22, and it shadowed the rustup
  shims). Build with `PATH="$HOME/.cargo/bin:$PATH" make -j8`.

Default build does **not** use `-Z build-std` (only if `BUILDSTD=1`), so the
prebuilt bare-metal target suffices.

## Gotcha

`~/.cargo` was once root-owned (legacy sudo) → cargo couldn't create `~/.cargo/git`
(`Permission denied`). Fix: `sudo chown -R $USER:staff ~/.cargo` (real terminal —
the in-session `!` has no tty for the sudo prompt).

Full toolchain history: host-local memory `m1n1-build-toolchain-m1host` (see root
`AGENTS.md`).
