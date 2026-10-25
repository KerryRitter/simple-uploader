import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simple_uploader.clipboard import choose_type, snapshot_files
from simple_uploader.core import UploaderError, config_path, read_config, write_config
from simple_uploader.desktop import cosmic_shortcut_text


class ClipboardConfigTests(unittest.TestCase):
    def test_media_and_files_preferred_over_plain_text(self):
        self.assertEqual(choose_type(['text/plain', 'image/png', 'text/html']), 'image/png')
        self.assertEqual(choose_type(['text/plain', 'video/mp4']), 'video/mp4')
        self.assertEqual(choose_type(['image/png', 'text/uri-list']), 'text/uri-list')
        self.assertEqual(choose_type(['text/plain', 'text/markdown']), 'text/markdown')
        self.assertEqual(choose_type(['text/html', 'text/plain']), 'text/plain')
        self.assertEqual(choose_type(['application/pdf']), 'application/pdf')

    def test_file_manager_copy_preserves_files_and_exact_content(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'my video 雪.mp4'
            source.write_bytes(b'\x00binary video\xff')
            markdown = directory / 'notes.md'
            markdown.write_text('# Notes\n')
            snapshot = directory / 'snapshot'
            snapshot.mkdir()
            data = f'cut\n{source.as_uri()}\n{markdown.as_uri()}\n'.encode()
            items = snapshot_files(data, snapshot, 'x-special/gnome-copied-files')
            self.assertEqual([item.content_type for item in items], ['video/mp4', 'text/markdown'])
            self.assertEqual(items[0].name, source.name)
            self.assertEqual(items[0].path.read_bytes(), source.read_bytes())
            source.write_bytes(b'changed after confirmation')
            self.assertEqual(items[0].path.read_bytes(), b'\x00binary video\xff')
            self.assertTrue(markdown.exists())

    def test_reject_remote_files_and_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            for uri in ('file://remote-host/private.txt', 'https://example.test/file', Path(directory).as_uri()):
                with self.assertRaises(UploaderError):
                    snapshot_files(uri.encode(), Path(directory), 'text/uri-list')

    def test_config_round_trip_permissions_and_no_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 's3.conf'
            marker = Path(directory) / 'executed'
            cfg = {'S3_ENDPOINT': 'https://s3.example.test', 'S3_BUCKET': 'bucket',
                   'S3_ACCESS_KEY_ID': 'key', 'S3_SECRET_ACCESS_KEY': "a # b ' c $value",
                   'S3_PATH_PREFIX': f'$(touch {marker})/'}
            write_config(path, cfg)
            loaded = read_config(path)
            for key, value in cfg.items():
                self.assertEqual(loaded[key], value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(marker.exists())

    def test_capture_config_fallback_and_own_override(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CONFIG_HOME=directory):
            base = Path(directory)
            own = base / 'simple-uploader/s3.conf'
            shared = base / 'capture/s3.conf'
            self.assertEqual(config_path(), own)
            shared.parent.mkdir()
            shared.touch()
            self.assertEqual(config_path(), shared)
            own.parent.mkdir()
            own.touch()
            self.assertEqual(config_path(), own)

    def test_cosmic_binding_preserves_other_actions_and_is_idempotent(self):
        original = '{\n    (modifiers: [Super], key: "x"): ToggleWindowFloating,\n}\n'
        registered = cosmic_shortcut_text(original, '/home/user/.local/bin/simple-uploader')
        self.assertIn('(modifiers: [Super], key: "x"): ToggleWindowFloating,', registered)
        self.assertEqual(cosmic_shortcut_text(registered, '/home/user/.local/bin/simple-uploader'), registered)
        conflict = '{(modifiers: [Alt, Ctrl, Shift], key: "u"): Spawn("another-app"),}'
        with self.assertRaisesRegex(UploaderError, 'already assigned'):
            cosmic_shortcut_text(conflict, '/usr/bin/simple-uploader')


if __name__ == '__main__':
    unittest.main()
