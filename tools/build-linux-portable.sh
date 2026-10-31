#!/usr/bin/env bash
# Build a portable Linux tarball: MemuMusic-<version>-linux.tar.gz in dist/.
# No network needed: the tarball ships sources; dependencies are installed
# into a per-user venv by the launcher on first run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(python3 -c "import re; print(re.search(r'__version__ = \"([^\"]+)\"', open('$ROOT/memumusic/__init__.py').read()).group(1))")"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
DEST="$STAGE/MemuMusic-$VERSION-linux"

mkdir -p "$DEST"
cp -a --no-preserve=ownership "$ROOT/memumusic" "$ROOT/requirements.txt" "$ROOT/LICENSE" \
    "$ROOT/THIRD_PARTY_NOTICES.md" "$ROOT/README_LINUX.md" "$ROOT/packaging" "$DEST/"
cp --no-preserve=ownership "$ROOT/packaging/memumusic" "$DEST/MemuMusic"
chmod +x "$DEST/MemuMusic" "$DEST/packaging/install-linux.sh"
find "$DEST" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name "*.pyc" -delete 2>/dev/null || true

mkdir -p "$ROOT/dist"
tar --owner=0 --group=0 -czf "$ROOT/dist/MemuMusic-$VERSION-linux.tar.gz" -C "$STAGE" "MemuMusic-$VERSION-linux"
echo "Built: $ROOT/dist/MemuMusic-$VERSION-linux.tar.gz"
tar -tzf "$ROOT/dist/MemuMusic-$VERSION-linux.tar.gz" | head -n 20
