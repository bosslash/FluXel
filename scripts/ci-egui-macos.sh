#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/fluxel-egui"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script must run on macOS." >&2
    exit 1
fi

if ! command -v rustup >/dev/null 2>&1; then
    echo "rustup is required: https://rustup.rs/" >&2
    exit 1
fi

rustup toolchain install 1.95.0 --profile minimal --component rustfmt --component clippy
cargo +1.95.0 fmt --all -- --check
cargo +1.95.0 test --all-targets --locked
cargo +1.95.0 clippy --all-targets --locked -- -D warnings
cargo +1.95.0 build --release --locked

bundle_dir="$repo_root/fluxel-egui/dist/Fluxel.app/Contents"
mkdir -p "$bundle_dir/MacOS"
cp target/release/fluxel-egui "$bundle_dir/MacOS/Fluxel"
cp packaging/macos/Info.plist "$bundle_dir/Info.plist"
chmod +x "$bundle_dir/MacOS/Fluxel"
tar -C "$repo_root/fluxel-egui/dist" -czf "$repo_root/fluxel-egui/dist/Fluxel-macOS.tar.gz" Fluxel.app
