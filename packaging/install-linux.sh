#!/usr/bin/env bash
# Install the MemuMusic desktop entry and icon for the current user.
# Run from the extracted portable directory: ./packaging/install-linux.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$APPS_DIR" "$ICON_DIR" "$BIN_DIR"
cp "$HERE/packaging/memumusic.desktop" "$APPS_DIR/memumusic.desktop"
cp "$HERE/memumusic/web/icon.png" "$ICON_DIR/memumusic.png"
ln -sf "$HERE/MemuMusic" "$BIN_DIR/memumusic" 2>/dev/null || cp "$HERE/packaging/memumusic" "$BIN_DIR/memumusic"
chmod +x "$BIN_DIR/memumusic"
command -v desktop-file-validate >/dev/null && desktop-file-validate "$APPS_DIR/memumusic.desktop" || true
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" || true
echo "MemuMusic installed for $USER. Make sure ~/.local/bin is on your PATH, then run: memumusic"
