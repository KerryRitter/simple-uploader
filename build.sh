#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VERSION=${1:-1.0.0}
if [[ ! "$VERSION" =~ ^[0-9][0-9A-Za-z.+:~\-]*$ ]]; then
  echo 'Invalid Debian package version.' >&2
  exit 1
fi
STAGE=$(mktemp -d)
trap 'rm -rf -- "$STAGE"' EXIT
install -d "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/lib/simple-uploader/simple_uploader" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/doc/simple-uploader"
install -m 755 "$ROOT/src/simple-uploader" "$STAGE/usr/bin/simple-uploader"
install -m 644 "$ROOT/src/simple_uploader/"*.py "$STAGE/usr/lib/simple-uploader/simple_uploader/"
install -m 644 "$ROOT/data/simple-uploader.desktop" "$STAGE/usr/share/applications/"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/simple-uploader/"
sed "s/^Version: .*/Version: $VERSION/" "$ROOT/debian/control" > "$STAGE/DEBIAN/control"
mkdir -p "$ROOT/dist"
dpkg-deb --build --root-owner-group "$STAGE" "$ROOT/dist/simple-uploader_${VERSION}_all.deb"
