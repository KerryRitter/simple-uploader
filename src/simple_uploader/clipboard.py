"""Snapshot clipboard data before confirmation; never upload a pasted path as text."""
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import urllib.parse

from .core import Item, UploaderError, mime_for_name


def executable(name):
    found = shutil.which(name)
    local = Path.home() / '.local/bin' / name
    if found:
        return found
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    raise UploaderError(f'Missing {name}. Run ./install.sh or install wl-clipboard (Wayland) / xclip (X11).')


class Clipboard:
    def __init__(self):
        self.wayland = bool(os.environ.get('WAYLAND_DISPLAY') or os.environ.get('XDG_SESSION_TYPE') == 'wayland')
        self.reader = executable('wl-paste' if self.wayland else 'xclip')
        self.writer = executable('wl-copy' if self.wayland else 'xclip')

    def _read_command(self, mime):
        if self.wayland:
            return [self.reader, '--no-newline', '--type', mime]
        return [self.reader, '-selection', 'clipboard', '-out', '-target', mime]

    def types(self):
        command = [self.reader, '--list-types'] if self.wayland else self._read_command('TARGETS')
        try:
            result = subprocess.run(command, capture_output=True, timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise UploaderError('The clipboard did not respond.') from exc
        if result.returncode:
            raise UploaderError('The clipboard is empty or unavailable. Copy something and try again.')
        return list(dict.fromkeys(result.stdout.decode('utf-8', 'replace').splitlines()))

    def read(self, mime):
        try:
            result = subprocess.run(self._read_command(mime), capture_output=True, timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise UploaderError('The clipboard did not respond.') from exc
        if result.returncode:
            raise UploaderError('Could not read the clipboard. Copy the item again and retry.')
        return result.stdout

    def snapshot(self, directory):
        types = self.types()
        mime = choose_type(types)
        if mime in ('text/uri-list', 'x-special/gnome-copied-files'):
            data = self.read(mime)
            if mime == 'text/uri-list':
                uris = [line for line in data.decode('utf-8', 'replace').splitlines()
                        if line and not line.startswith('#')]
                if uris and all(urllib.parse.urlsplit(uri).scheme in ('http', 'https') for uri in uris):
                    target = directory / 'clipboard.txt'
                    target.write_text('\n'.join(uris), encoding='utf-8')
                    return [Item(target, target.name, 'text/plain;charset=utf-8')]
            return snapshot_files(data, directory, mime)
        extension = extension_for(mime)
        target = directory / ('clipboard' + extension)
        try:
            with target.open('wb') as stream:
                result = subprocess.run(self._read_command(mime), stdout=stream, stderr=subprocess.PIPE, timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise UploaderError('The clipboard did not respond.') from exc
        if result.returncode or not target.stat().st_size:
            raise UploaderError('The clipboard is empty or could not be read.')
        return [Item(target, target.name, content_type(mime))]

    def copy(self, text):
        command = ([self.writer, '--type', 'text/plain;charset=utf-8'] if self.wayland
                   else [self.writer, '-selection', 'clipboard', '-in', '-target', 'UTF8_STRING'])
        try:
            # wl-copy forks a clipboard owner; redirect output so the child cannot hold a pipe open.
            result = subprocess.run(command, input=text.encode(), stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UploaderError('Uploaded, but could not copy the URL. Copy it from this window.') from exc
        if result.returncode:
            raise UploaderError('Uploaded, but could not copy the URL. Copy it from this window.')


def choose_type(types):
    for mime in ('x-special/gnome-copied-files', 'text/uri-list'):
        if mime in types:
            return mime
    # Prefer original media over alternate textual representations.
    for prefix in ('image/', 'video/', 'audio/'):
        matches = [mime for mime in types if mime.startswith(prefix)]
        if matches:
            return 'image/png' if 'image/png' in matches else matches[0]
    for mime in ('text/markdown', 'text/x-markdown', 'application/json',
                 'text/plain;charset=utf-8', 'text/plain', 'UTF8_STRING', 'TEXT', 'STRING', 'text/html'):
        if mime in types:
            return mime
    for mime in types:
        if '/' in mime and not mime.startswith(('x-special/', 'application/x-gtk-', 'application/x-qt-')):
            return mime
    raise UploaderError('The clipboard has no supported data. Copy text, an image, or a file.')


def content_type(mime):
    if mime in ('UTF8_STRING', 'TEXT', 'STRING'):
        return 'text/plain;charset=utf-8'
    if mime == 'text/x-markdown':
        return 'text/markdown'
    return mime


def extension_for(mime):
    base = content_type(mime).split(';')[0]
    known = {'text/plain': '.txt', 'text/markdown': '.md', 'text/html': '.html',
             'image/jpeg': '.jpg', 'application/json': '.json', 'video/mp4': '.mp4',
             'video/webm': '.webm', 'image/png': '.png', 'image/svg+xml': '.svg'}
    return known.get(base) or mimetypes.guess_extension(base) or '.bin'


def snapshot_files(data, directory, mime):
    try:
        lines = data.decode('utf-8').splitlines()
    except UnicodeDecodeError as exc:
        raise UploaderError('The copied file list is not valid UTF-8.') from exc
    if mime == 'x-special/gnome-copied-files' and lines and lines[0] in ('copy', 'cut'):
        lines = lines[1:]
    items = []
    seen = set()
    for line in lines:
        if not line or line.startswith('#') or line in seen:
            continue
        seen.add(line)
        parsed = urllib.parse.urlsplit(line)
        if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost') or parsed.query or parsed.fragment:
            raise UploaderError('Only local copied files can be uploaded. Remote URLs are not downloaded.')
        path = Path(urllib.parse.unquote(parsed.path))
        if not path.is_file():
            raise UploaderError(f'{path.name} is not a regular file. Zip folders before copying them.')
        target = directory / str(len(items))
        shutil.copyfile(path, target)
        items.append(Item(target, path.name, mime_for_name(path.name)))
    if not items:
        raise UploaderError('No local files were found on the clipboard.')
    return items
