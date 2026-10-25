"""Install desktop shortcuts without replacing unrelated bindings."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile

from .core import UploaderError

SHORTCUT = 'Ctrl+Shift+Alt+U'


def cosmic_shortcut_text(text, command):
    if not text.strip().startswith('{') or not text.strip().endswith('}'):
        raise UploaderError('Unrecognized COSMIC shortcut config. Add the shortcut in Settings → Keyboard.')
    entry = ('(modifiers: [Ctrl, Shift, Alt], key: "u", description: Some("Simple Uploader")): '
             f'Spawn({json.dumps(command)}),')
    pattern = re.compile(r'\((?P<binding>[^()]*(?:Some\([^()]*\)[^()]*)?)\)\s*:\s*'
                         r'(?P<action>Spawn\("(?:[^"\\]|\\.)*"\)|[^,\n]+)\s*,?')
    for match in pattern.finditer(text):
        binding = match['binding']
        modifiers = re.search(r'modifiers\s*:\s*\[([^]]*)\]', binding)
        key = re.search(r'key\s*:\s*"([^"]+)"', binding)
        if not modifiers or not key:
            continue
        if set(re.findall(r'\w+', modifiers[1])) == {'Ctrl', 'Shift', 'Alt'} and key[1].lower() == 'u':
            if 'Simple Uploader' not in binding:
                raise UploaderError(f'{SHORTCUT} is already assigned. Choose a shortcut in Settings → Keyboard.')
            return text[:match.start()] + entry + text[match.end():]
    start = text.index('{') + 1
    return text[:start] + '\n    ' + entry + text[start:]


def setup_shortcut(command):
    desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    if 'COSMIC' in desktop:
        base = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
        path = base / 'cosmic/com.system76.CosmicSettings.Shortcuts/v1/custom'
        text = path.read_text() if path.exists() else '{}\n'
        updated = cosmic_shortcut_text(text, command)
        if updated != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                stamp = dt.datetime.now().strftime('%Y%m%d%H%M%S%f')
                shutil.copy2(path, path.with_name('custom.backup-' + stamp))
            fd, temporary = tempfile.mkstemp(prefix='.custom-', dir=path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(updated)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return f'{SHORTCUT} registered in COSMIC.'
    if any(name in desktop for name in ('GNOME', 'UNITY', 'POP')):
        from gi.repository import Gio
        schema = 'org.gnome.settings-daemon.plugins.media-keys'
        root = Gio.Settings.new(schema)
        paths = list(root.get_strv('custom-keybindings'))
        own_path = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/simple-uploader/'
        for path in paths:
            settings = Gio.Settings.new_with_path(schema + '.custom-keybinding', path)
            binding = settings.get_string('binding').replace('<Control>', '<Primary>').lower()
            if path != own_path and all(token in binding for token in ('<primary>', '<shift>', '<alt>')) and binding.endswith('u'):
                raise UploaderError(f'{SHORTCUT} is already assigned. Choose a shortcut in Settings → Keyboard.')
        settings = Gio.Settings.new_with_path(schema + '.custom-keybinding', own_path)
        settings.set_string('name', 'Simple Uploader')
        settings.set_string('command', command)
        settings.set_string('binding', '<Primary><Shift><Alt>u')
        if own_path not in paths:
            root.set_strv('custom-keybindings', paths + [own_path])
        Gio.Settings.sync()
        return f'{SHORTCUT} registered in GNOME.'
    raise UploaderError(f'Add {SHORTCUT} in your desktop keyboard settings, with command: {command}')


def launcher_command():
    import sys
    return shlex.quote(str(Path(sys.argv[0]).resolve()))
