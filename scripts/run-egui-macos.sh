#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
TOOLS_DIR=${FLUXEL_DEV_TOOLS_DIR:-"$REPO_DIR/.dev-tools"}

export CARGO_HOME="$TOOLS_DIR/cargo"
export RUSTUP_HOME="$TOOLS_DIR/rustup"

if [ ! -x "$CARGO_HOME/bin/cargo" ]; then
    "$SCRIPT_DIR/bootstrap-egui-macos.sh"
fi

cd "$REPO_DIR/fluxel-egui"
"$CARGO_HOME/bin/cargo" build --locked "$@"

BUILD_PROFILE="debug"
for argument in "$@"; do
    if [ "$argument" = "--release" ]; then
        BUILD_PROFILE="release"
    fi
done

APP_DIR="$REPO_DIR/fluxel-egui/target/$BUILD_PROFILE/Fluxel.app"
CONTENTS_DIR="$APP_DIR/Contents"
EXECUTABLE="$CONTENTS_DIR/MacOS/Fluxel"

mkdir -p "$CONTENTS_DIR/MacOS"
cp "$REPO_DIR/fluxel-egui/target/$BUILD_PROFILE/fluxel-egui" "$EXECUTABLE"
cp "$REPO_DIR/fluxel-egui/packaging/macos/Info.plist" "$CONTENTS_DIR/Info.plist"
chmod +x "$EXECUTABLE"
codesign --force --deep --sign - "$APP_DIR"

# Re-running the script replaces only this project's current development app.
pkill -f "$EXECUTABLE" 2>/dev/null || true
open "$APP_DIR"

echo "Fluxel development app launched: $APP_DIR"
