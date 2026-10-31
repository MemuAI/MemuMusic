#!/usr/bin/env bash
# Build a .deb (Architecture: all) with dpkg-deb, no debhelper needed.
# Output: dist/memumusic_<version>_all.deb
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(python3 -c "import re; print(re.search(r'__version__ = \"([^\"]+)\"', open('$ROOT/memumusic/__init__.py').read()).group(1))")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/memumusic"

mkdir -p "$PKG/DEBIAN" "$PKG/usr/lib/memumusic" "$PKG/usr/bin" \
    "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"
cp -a --no-preserve=ownership "$ROOT/memumusic" "$ROOT/requirements.txt" "$ROOT/LICENSE" \
    "$ROOT/THIRD_PARTY_NOTICES.md" "$ROOT/README_LINUX.md" "$PKG/usr/lib/memumusic/"
cp --no-preserve=ownership "$ROOT/packaging/memumusic" "$PKG/usr/bin/memumusic"
cp "$ROOT/packaging/memumusic.desktop" "$PKG/usr/share/applications/memumusic.desktop"
cp --no-preserve=ownership "$ROOT/memumusic/web/icon.png" "$PKG/usr/share/icons/hicolor/256x256/apps/memumusic.png"
chmod 755 "$PKG/usr/bin/memumusic"
find "$PKG/usr/lib/memumusic" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$PKG/usr/lib/memumusic" -name "*.pyc" -delete 2>/dev/null || true

cat > "$PKG/DEBIAN/control" <<EOF
Package: memumusic
Version: $VERSION
Section: sound
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-venv, python3-gi, gir1.2-gtk-3.0, libwebkit2gtk-4.1-0 | libwebkit2gtk-4.0-37, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, xdg-utils
Recommends: ffmpeg, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, gstreamer1.0-libav, gstreamer1.0-pipewire
Maintainer: MemuMusic <support@memumusic.local>
Description: MemuMusic desktop music player
 MemuMusic is a local music player with a desktop window (GTK + WebKitGTK
 via pywebview) served from 127.0.0.1. The window packages are hard
 dependencies: without them the app cannot open its window and shows an
 explicit install page instead of silently falling back to a browser tab.
 Audio in the window is decoded by GStreamer inside WebKitGTK: the base
 and good plugin sets are hard dependencies, and the bad/ugly/libav sets
 plus the PipeWire plugin are recommended, so mp3/m4a/aac tracks play
 instead of failing silently on a stock install.
EOF
cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
cat > "$PKG/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
# Bytecode caches created on first run live inside the package tree; drop
# them so dpkg can remove the directories cleanly.
find /usr/lib/memumusic -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
exit 0
EOF
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm" "$PKG/DEBIAN" "$PKG/DEBIAN"
chmod 644 "$PKG/DEBIAN/control"
find "$PKG" -type d -exec chmod 755 {} +
find "$PKG/usr" -type f -exec chmod 644 {} +
chmod 755 "$PKG/usr/bin/memumusic"

mkdir -p "$ROOT/dist"
dpkg-deb --build --root-owner-group "$PKG" "$ROOT/dist/memumusic_${VERSION}_all.deb"
echo "Built: $ROOT/dist/memumusic_${VERSION}_all.deb"
dpkg-deb --info "$ROOT/dist/memumusic_${VERSION}_all.deb"
