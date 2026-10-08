#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
TOOLS_DIR=${FLUXEL_DEV_TOOLS_DIR:-"$REPO_DIR/.dev-tools"}

export CARGO_HOME="$TOOLS_DIR/cargo"
export RUSTUP_HOME="$TOOLS_DIR/rustup"

case "$(uname -m)" in
    arm64) RUST_HOST="aarch64-apple-darwin" ;;
    x86_64) RUST_HOST="x86_64-apple-darwin" ;;
    *)
        echo "Unsupported macOS architecture: $(uname -m)" >&2
        exit 1
        ;;
esac

mkdir -p "$CARGO_HOME" "$RUSTUP_HOME"

if [ ! -x "$CARGO_HOME/bin/rustup" ]; then
    RUSTUP_INIT="$TOOLS_DIR/rustup-init"
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error \
        "https://static.rust-lang.org/rustup/dist/$RUST_HOST/rustup-init" \
        --output "$RUSTUP_INIT"
    chmod +x "$RUSTUP_INIT"
    "$RUSTUP_INIT" -y --no-modify-path --profile minimal --default-toolchain none
    rm -f "$RUSTUP_INIT"
fi

"$CARGO_HOME/bin/rustup" toolchain install 1.95.0 \
    --profile minimal \
    --component rustfmt \
    --component clippy

echo "Fluxel local Rust is ready:"
"$CARGO_HOME/bin/rustc" --version
"$CARGO_HOME/bin/cargo" --version
