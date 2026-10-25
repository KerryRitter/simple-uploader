"""Opt-in GTK integration checks using a local S3 server and an isolated clipboard."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simple_uploader.core import Item, write_config
from test_upload import S3Server


@unittest.skipUnless(os.environ.get('SIMPLE_UPLOADER_UI_TESTS') == '1', 'opt-in graphical test')
class UITests(unittest.TestCase):
    def drive(self, status=200, cancel=False, multiple=False):
        from simple_uploader import ui
        from gi.repository import GLib, Gtk
        copies = []

        class FakeClipboard:
            def snapshot(self, directory):
                path = directory / 'clipboard.txt'
                path.write_text('# A real GTK confirmation test\n')
                items = [Item(path, 'clipboard.txt', 'text/plain;charset=utf-8')]
                if multiple:
                    second = directory / 'second.txt'
                    second.write_text('Another file\n')
                    items.append(Item(second, 'second.txt', 'text/plain;charset=utf-8'))
                return items

            def copy(self, text):
                copies.append(text)

        with S3Server() as server, tempfile.TemporaryDirectory() as directory, patch.object(ui, 'notify'):
            directory = Path(directory)
            cfg_path = directory / 's3.conf'
            write_config(cfg_path, server.cfg)
            server.status = status
            window = ui.UploadWindow(FakeClipboard(), directory, cfg_path)
            activated = []
            timed_out = []

            def tick():
                for widget in Gtk.Window.list_toplevels():
                    if isinstance(widget, Gtk.MessageDialog) and widget.get_visible():
                        widget.response(Gtk.ResponseType.CLOSE)
                if not window.busy and not activated:
                    activated.append(True)
                    if window.format_combo is not None:
                        window.format_combo.set_active_id('md')
                    window.dialog.response(Gtk.ResponseType.CANCEL if cancel else Gtk.ResponseType.OK)
                return not window.finished

            def timeout():
                timed_out.append(True)
                window.finish()
                return False

            tick_id = GLib.timeout_add(30, tick)
            timeout_id = GLib.timeout_add_seconds(8, timeout)
            Gtk.main()
            GLib.source_remove(timeout_id)
            if not timed_out:
                # The final tick may still be scheduled if upload finished between ticks.
                source = GLib.MainContext.default().find_source_by_id(tick_id)
                if source is not None:
                    source.destroy()
            self.assertFalse(timed_out, 'GTK flow timed out')
            self.assertTrue(activated)
            return server.requests, copies, window.exit_code

    def test_confirm_upload_copies_url_after_success(self):
        requests, copies, code = self.drive()
        self.assertEqual(code, 0)
        self.assertEqual(len(copies), 1)
        self.assertTrue(copies[0].startswith('https://files.example.test/'))
        self.assertTrue(copies[0].endswith('.md'))
        self.assertEqual(requests[0][1]['Content-Type'], 'text/markdown;charset=utf-8')
        self.assertIsNone(requests[0][3])

    def test_cancel_does_not_upload_or_replace_clipboard(self):
        requests, copies, code = self.drive(cancel=True)
        self.assertEqual((requests, copies, code), ([], [], 0))

    def test_failure_does_not_replace_clipboard(self):
        requests, copies, code = self.drive(status=403)
        self.assertEqual(code, 1)
        self.assertEqual(len(requests), 1)
        self.assertEqual(copies, [])

    def test_multiple_files_copy_one_url_per_line(self):
        requests, copies, code = self.drive(multiple=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(copies[0].splitlines()), 2)
