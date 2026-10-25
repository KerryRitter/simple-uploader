import argparse
import fcntl
import os
from pathlib import Path
import sys
import tempfile

from . import __version__
from .clipboard import Clipboard
from .core import UploaderError, config_path, read_config, validate_config
from .desktop import launcher_command, setup_shortcut


def main():
    parser = argparse.ArgumentParser(description='Confirm, upload clipboard contents to S3/R2, and copy the URL.')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--setup', action='store_true', help='configure S3/R2 in a dialog')
    actions.add_argument('--setup-shortcut', action='store_true', help='register Ctrl+Shift+Alt+U')
    actions.add_argument('--check', action='store_true', help='check dependencies and config without uploading')
    parser.add_argument('--config', help='override the S3 config file path')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args()
    path = config_path(args.config)
    try:
        if args.setup_shortcut:
            print(setup_shortcut(launcher_command()))
            return 0
        if args.check:
            clipboard = Clipboard()
            print('Clipboard: ' + ('Wayland' if clipboard.wayland else 'X11'))
            print(f'Config: {path}')
            validate_config(read_config(path))
            import gi
            gi.require_version('Gtk', '3.0')
            from gi.repository import Gtk
            print('GTK: available\nConfig: valid')
            return 0
        cache = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'simple-uploader'
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (cache / 'instance.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('Simple Uploader is already open.', file=sys.stderr)
                return 0
            from . import ui
            if not ui.Gtk.init_check()[0]:
                raise UploaderError('No graphical desktop is available.')
            if args.setup:
                return 0 if ui.setup(path) else 1
            clipboard = Clipboard()
            with tempfile.TemporaryDirectory(prefix='simple-uploader-') as directory:
                return ui.run(clipboard, Path(directory), path)
    except (UploaderError, OSError, ImportError, ValueError) as exc:
        text = str(exc)
        print('simple-uploader: ' + text, file=sys.stderr)
        if not (args.check or args.setup_shortcut):
            try:
                from . import ui
                if ui.Gtk.init_check()[0]:
                    ui.message(text)
            except (ImportError, ValueError):
                pass
        return 1


if __name__ == '__main__':
    sys.exit(main())
