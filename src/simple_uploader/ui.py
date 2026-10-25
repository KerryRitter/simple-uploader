"""Small GTK confirmation and setup dialogs; clipboard and network work off-thread."""
import threading
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, Gio, GLib, Gtk

from .core import FIELDS, UploaderError, read_config, readable_size, validate_config, write_config, upload


def label(text):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    widget.set_selectable(True)
    return widget


def message(text, parent=None, error=True):
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, title='Simple Uploader',
                               message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                               buttons=Gtk.ButtonsType.CLOSE, text=text)
    dialog.set_default_size(480, -1)
    dialog.run()
    dialog.destroy()


def setup(path, parent=None):
    cfg = read_config(path)
    dialog = Gtk.Dialog(title='Simple Uploader — S3 / R2 setup', transient_for=parent, modal=True)
    dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Save', Gtk.ResponseType.OK)
    dialog.set_default_size(570, -1)
    box = dialog.get_content_area()
    box.set_border_width(16)
    box.set_spacing(12)
    box.add(label('Enter your bucket settings. For R2, use your S3 API endpoint and a public custom domain.'))
    grid = Gtk.Grid(column_spacing=12, row_spacing=10)
    entries = {}
    for row, (key, title, default) in enumerate(FIELDS):
        grid.attach(label(title), 0, row, 1, 1)
        entry = Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_text(cfg.get(key, default))
        if key in ('S3_SECRET_ACCESS_KEY', 'S3_SESSION_TOKEN'):
            entry.set_visibility(False)
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entries[key] = entry
        grid.attach(entry, 1, row, 1, 1)
    box.add(grid)
    box.add(label(f'Config: {path}\nSaved with owner-only permissions (600).'))
    dialog.show_all()
    try:
        while dialog.run() == Gtk.ResponseType.OK:
            cfg = {key: entry.get_text().strip() for key, entry in entries.items()}
            try:
                write_config(path, cfg)
            except (UploaderError, OSError) as exc:
                message(str(exc), dialog)
            else:
                return cfg
        return None
    finally:
        dialog.destroy()


def notify(text):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync('org.freedesktop.Notifications', '/org/freedesktop/Notifications',
                      'org.freedesktop.Notifications', 'Notify',
                      GLib.Variant('(susssasa{sv}i)', ('Simple Uploader', 0, 'document-send',
                                   'URL copied to clipboard', text, [], {}, 4000)),
                      None, Gio.DBusCallFlags.NONE, 1500, None)
    except GLib.Error:
        pass


class UploadWindow:
    def __init__(self, clipboard, directory, path):
        self.clipboard, self.directory, self.path = clipboard, directory, path
        self.items, self.cfg = [], {}
        self.finished = False
        self.busy = True
        self.exit_code = 0
        self.dialog = Gtk.Dialog(title='Upload clipboard?', modal=False)
        self.dialog.set_default_size(440, -1)
        self.dialog.set_resizable(False)
        self.dialog.set_position(Gtk.WindowPosition.CENTER)
        self.dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL, 'Upload', Gtk.ResponseType.OK)
        self.dialog.set_default_response(Gtk.ResponseType.CANCEL)
        self.dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(False)
        self.dialog.connect('response', self.respond)
        self.dialog.connect('delete-event', self.close)
        self.box = self.dialog.get_content_area()
        self.box.set_border_width(18)
        self.box.set_spacing(12)
        self.status = label('Reading clipboard…')
        self.spinner = Gtk.Spinner()
        self.spinner.start()
        self.box.add(self.status)
        self.box.add(self.spinner)
        self.dialog.show_all()
        self.background(lambda: clipboard.snapshot(directory), self.loaded)

    def background(self, work, success):
        def run():
            try:
                result = work()
            except Exception as exc:
                GLib.idle_add(self.failed, str(exc))
            else:
                GLib.idle_add(success, result)
        threading.Thread(target=run, daemon=True).start()

    def loaded(self, items):
        if self.finished:
            return False
        self.items = items
        try:
            self.cfg = read_config(self.path)
            try:
                validate_config(self.cfg)
            except UploaderError:
                self.cfg = setup(self.path, self.dialog)
                if self.cfg is None:
                    self.finish()
                    return False
        except (UploaderError, OSError) as exc:
            return self.failed(str(exc))
        self.spinner.stop()
        self.spinner.hide()
        self.status.set_text(f'{len(items)} item' + ('s' if len(items) != 1 else '')
                             + f' · {readable_size(sum(item.size for item in items))}')
        destination = self.cfg.get('S3_PUBLIC_URL_BASE') or self.cfg['S3_ENDPOINT'] + '/' + self.cfg['S3_BUCKET']
        self.box.add(label('Upload to ' + destination))
        self.name_entry = None
        self.format_combo = None
        if len(items) == 1:
            item = items[0]
            self.name_entry = Gtk.Entry(text=item.name)
            self.box.add(self.name_entry)
            if item.content_type.split(';')[0] in ('text/plain', 'text/markdown'):
                self.format_combo = Gtk.ComboBoxText()
                self.format_combo.append('txt', 'Plain text (.txt)')
                self.format_combo.append('md', 'Markdown (.md)')
                self.format_combo.set_active_id('md' if item.content_type.startswith('text/markdown') else 'txt')
                self.format_combo.connect('changed', self.format_changed)
                self.box.add(self.format_combo)
            if item.content_type.startswith('text/') or item.content_type == 'application/json':
                with item.path.open('rb') as stream:
                    preview = stream.read(4096).decode('utf-8', 'replace')
                view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
                view.get_buffer().set_text(preview + ('\n…' if item.size > 4096 else ''))
                scroll = Gtk.ScrolledWindow()
                scroll.set_size_request(400, 150)
                scroll.add(view)
                self.box.add(scroll)
            elif item.content_type.startswith('image/'):
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(item.path), 360, 220, True)
                    self.box.add(Gtk.Image.new_from_pixbuf(pixbuf))
                except GLib.Error:
                    pass
        else:
            view = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
            view.get_buffer().set_text('\n'.join(f'{item.name} ({readable_size(item.size)})' for item in items))
            scroll = Gtk.ScrolledWindow()
            scroll.set_size_request(400, 150)
            scroll.add(view)
            self.box.add(scroll)
        self.box.add(label('The shareable URL will replace your clipboard after upload.'))
        self.busy = False
        self.dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(True)
        self.dialog.show_all()
        self.spinner.hide()
        return False

    def format_changed(self, combo):
        from pathlib import Path
        name = self.name_entry.get_text()
        self.name_entry.set_text(str(Path(name).with_suffix('.' + combo.get_active_id())))

    def respond(self, dialog, response):
        if response != Gtk.ResponseType.OK:
            if not self.busy:
                self.finish()
            return
        if self.busy:
            return
        if self.name_entry is not None:
            name = self.name_entry.get_text().strip()
            if not name or '/' in name or '\\' in name or name in ('.', '..'):
                message('Enter a filename without slashes.', dialog)
                return
            self.items[0].name = name
        if self.format_combo is not None:
            self.items[0].content_type = ('text/markdown;charset=utf-8' if self.format_combo.get_active_id() == 'md'
                                          else 'text/plain;charset=utf-8')
        self.busy = True
        dialog.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(False)
        dialog.get_widget_for_response(Gtk.ResponseType.CANCEL).set_sensitive(False)
        self.spinner.show()
        self.spinner.start()
        self.background(self.upload_all, self.uploaded)

    def upload_all(self):
        urls = []
        for index, item in enumerate(self.items, 1):
            GLib.idle_add(self.set_status, f'Uploading {index}/{len(self.items)}: {item.name}')
            try:
                urls.append(upload(self.cfg, item))
            except Exception as exc:
                partial = '\n\nAlready uploaded:\n' + '\n'.join(urls) if urls else ''
                raise UploaderError(str(exc) + partial) from exc
        return urls

    def set_status(self, text):
        if not self.finished:
            self.status.set_text(text)
        return False

    def uploaded(self, urls):
        text = '\n'.join(urls)
        try:
            self.clipboard.copy(text)
        except UploaderError as exc:
            return self.failed(str(exc) + '\n\n' + text)
        notify(text)
        self.finish()
        return False

    def failed(self, text):
        if not self.finished:
            self.exit_code = 1
            self.spinner.stop()
            message(text, self.dialog)
            self.finish()
        return False

    def close(self, *_):
        if not self.busy:
            self.finish()
        return True

    def finish(self):
        self.finished = True
        self.dialog.destroy()
        Gtk.main_quit()


def run(clipboard, directory, path):
    window = UploadWindow(clipboard, directory, path)
    Gtk.main()
    return window.exit_code
