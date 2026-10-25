#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PREFIX=${PREFIX:-"$HOME/.local"}

if [[ "${1:-}" == "--help" ]]; then
  echo 'Usage: ./install.sh [--no-shortcut]'
  echo 'Installs to ~/.local by default; override with PREFIX.'
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--no-shortcut" ) ]]; then
  echo 'Usage: ./install.sh [--no-shortcut]' >&2
  exit 1
fi

if ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null; then
  echo 'Install GTK support, then rerun: sudo apt install python3-gi gir1.2-gtk-3.0' >&2
  exit 1
fi

# On Pop!_OS/Ubuntu, wl-clipboard needs only libraries already in the desktop.
# A per-user extraction avoids requiring root to install this small helper.
if [[ -n "${WAYLAND_DISPLAY:-}" || "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
  if ! { command -v wl-paste >/dev/null && command -v wl-copy >/dev/null; } && \
     ! { [[ -x "$HOME/.local/bin/wl-paste" && -x "$HOME/.local/bin/wl-copy" ]]; }; then
    if ! command -v apt-get >/dev/null || ! command -v dpkg-deb >/dev/null; then
      echo 'Install wl-clipboard with your package manager, then rerun.' >&2
      exit 1
    fi
    DEPS=$(mktemp -d)
    trap 'rm -rf -- "$DEPS"' EXIT
    (cd "$DEPS" && apt-get download wl-clipboard)
    dpkg-deb -x "$DEPS"/*.deb "$DEPS/unpacked"
    install -d "$HOME/.local/bin" "$HOME/.local/share/doc/simple-uploader/wl-clipboard"
    install -m 755 "$DEPS/unpacked/usr/bin/"{wl-paste,wl-copy} "$HOME/.local/bin/"
    cp -a "$DEPS/unpacked/usr/share/doc/wl-clipboard/." "$HOME/.local/share/doc/simple-uploader/wl-clipboard/"
  fi
elif ! command -v xclip >/dev/null; then
  echo 'Install xclip, then rerun: sudo apt install xclip' >&2
  exit 1
fi

install -d "$PREFIX/bin" "$PREFIX/lib/simple-uploader/simple_uploader" "$PREFIX/share/applications"
install -m 755 "$ROOT/src/simple-uploader" "$PREFIX/bin/simple-uploader"
install -m 644 "$ROOT/src/simple_uploader/"*.py "$PREFIX/lib/simple-uploader/simple_uploader/"
install -m 644 "$ROOT/data/simple-uploader.desktop" "$PREFIX/share/applications/simple-uploader.desktop"
# Desktop launchers do not necessarily inherit ~/.local/bin in PATH.
/usr/bin/python3 - "$PREFIX" <<'PY'
from pathlib import Path
import sys
prefix = Path(sys.argv[1]).resolve()
path = prefix / 'share/applications/simple-uploader.desktop'
command = str(prefix / 'bin/simple-uploader')
escaped = command.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
path.write_text(path.read_text().replace('Exec=simple-uploader', f'Exec="{escaped}"'))
PY
if [[ "${1:-}" != "--no-shortcut" ]]; then
  "$PREFIX/bin/simple-uploader" --setup-shortcut
fi
echo "Installed: $PREFIX/bin/simple-uploader"
echo 'Press Ctrl+Shift+Alt+U. First launch asks for your S3/R2 settings if needed.'
echo "Or configure now: $PREFIX/bin/simple-uploader --setup"
