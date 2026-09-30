import datetime
import os

from gi.repository import Gdk, Gio, GLib, Gtk

from . import core

TEXT_LIMIT = 2 * 1024 * 1024
TEXT_TYPES = ('application/json', 'application/xml', 'application/javascript', 'application/x-shellscript',
              'application/x-yaml', 'application/toml', 'application/sql', 'application/x-desktop')


def human_size(n):
    for unit in ('bytes', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return ('%d %s' % (n, unit)) if unit == 'bytes' else '%.1f %s' % (n, unit)
        n /= 1024.0


def is_text_file(path, ctype):
    if ctype.startswith('text/') or ctype in TEXT_TYPES or Gio.content_type_is_a(ctype, 'text/plain'):
        return True
    try:
        with open(path, 'rb') as f:
            head = f.read(8192)
    except OSError:
        return False
    if not head or b'\0' in head:
        return False
    try:
        head.decode('utf-8')
        return True
    except UnicodeDecodeError as e:
        return e.start > len(head) - 4  # a multibyte char cut at the boundary


class ImageView(Gtk.DrawingArea):
    """Draws a pixbuf scaled to fit, keeping the aspect ratio (responsive)."""

    def __init__(self, pb):
        Gtk.DrawingArea.__init__(self)
        self.pb = pb
        self.set_size_request(100, 100)
        self.connect('draw', self._draw)

    def _draw(self, w, cr):
        a = self.get_allocation()
        pw, ph = self.pb.get_width(), self.pb.get_height()
        s = min(a.width / float(pw), a.height / float(ph), 1.0 if max(pw, ph) > 64 else 8.0)
        dw, dh = pw * s, ph * s
        cr.translate((a.width - dw) / 2, (a.height - dh) / 2)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, self.pb, 0, 0)
        cr.paint()
        return False


def preview_widget(path):
    """Widget previewing `path`, chosen by content type."""
    try:
        info = Gio.File.new_for_path(path).query_info('standard::*,time::modified', Gio.FileQueryInfoFlags.NONE,
                                                     None)
    except GLib.Error as e:
        return core.label('Cannot open this file: %s' % e.message, 'pt-error', xalign=0.5)
    ctype = info.get_content_type() or 'application/octet-stream'
    if info.get_file_type() == Gio.FileType.DIRECTORY:
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        try:
            names = sorted(os.listdir(path), key=str.lower)
        except OSError as e:
            return core.label(str(e), 'pt-error', xalign=0.5)
        for n in names[:1000]:
            full = os.path.join(path, n)
            b = Gtk.Box(spacing=8)
            b.set_border_width(4)
            b.pack_start(Gtk.Image.new_from_icon_name('folder' if os.path.isdir(full) else 'text-x-generic',
                                                      Gtk.IconSize.MENU), False, False, 0)
            b.pack_start(core.label(n, wrap=False), True, True, 0)
            lb.add(b)
        if len(names) > 1000:
            lb.add(core.label('… and %d more' % (len(names) - 1000), 'pt-dim'))
        if not names:
            lb.add(core.label('Empty folder', 'pt-dim', xalign=0.5))
        return core.scrolled(lb)
    regular = info.get_file_type() == Gio.FileType.REGULAR  # reading a pipe or a device would wait forever
    if regular and ctype.startswith('image/'):
        try:
            pb = core.load_pixbuf(path)
            pb = pb.apply_embedded_orientation() or pb
            return ImageView(pb)
        except (GLib.Error, ValueError):
            pass
    if regular and is_text_file(path, ctype):
        try:
            with open(path, 'rb') as f:
                data = f.read(TEXT_LIMIT + 1)
        except OSError as e:
            return core.label(str(e), 'pt-error', xalign=0.5)
        text = data[:TEXT_LIMIT].decode('utf-8', 'replace')
        if len(data) > TEXT_LIMIT:
            text += '\n\n… (file truncated in preview)'
        tv = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.set_left_margin(10)
        tv.set_top_margin(10)
        tv.get_buffer().set_text(text)
        return core.scrolled(tv)
    # fallback: information card
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_valign(Gtk.Align.CENTER)
    img = Gtk.Image.new_from_gicon(info.get_icon(), Gtk.IconSize.DIALOG)
    img.set_pixel_size(96)
    box.pack_start(img, False, False, 0)
    # from the details already read: asking again fails for a broken link
    mtime = datetime.datetime.fromtimestamp(info.get_attribute_uint64('time::modified')).strftime('%Y-%m-%d %H:%M')
    for t in (info.get_display_name(), Gio.content_type_get_description(ctype),
              human_size(info.get_size()), 'Modified ' + mtime):
        box.pack_start(core.label(t, xalign=0.5), False, False, 0)
    return box


class PeekWindow(Gtk.Window):
    def __init__(self, app, paths, index=0):
        Gtk.Window.__init__(self, title='Peek')
        if isinstance(app, Gtk.Application):
            self.set_application(app)
        self.paths = [os.path.abspath(p) for p in paths]
        self.i = max(0, min(index, len(self.paths) - 1))
        mon = Gdk.Display.get_default().get_primary_monitor() or Gdk.Display.get_default().get_monitor(0)
        wa = mon.get_workarea()
        self.set_default_size(max(320, int(wa.width * 0.6)), max(300, int(wa.height * 0.7)))
        hb = Gtk.HeaderBar(show_close_button=True)
        self.hb = hb
        self.set_titlebar(hb)
        self.prev = core.button('', lambda: self.go(-1), 'go-previous-symbolic', tooltip='Previous (Left)')
        self.next = core.button('', lambda: self.go(1), 'go-next-symbolic', tooltip='Next (Right)')
        for b in (self.prev, self.next):  # shown by show_file, and only when there is more than one file
            b.set_no_show_all(True)
            hb.pack_start(b)
        hb.pack_end(core.button('', lambda: core.open_path(self.paths[self.i]), 'document-open-symbolic',
                                tooltip='Open with default app'))
        hb.pack_end(core.button('', lambda: core.open_path(os.path.dirname(self.paths[self.i])),
                                'folder-open-symbolic', tooltip='Open containing folder'))
        self.body = Gtk.Box()
        self.add(self.body)
        self.connect('key-press-event', self._key)
        self.show_file()

    def show_file(self):
        for c in self.body.get_children():
            c.destroy()
        p = self.paths[self.i]
        self.hb.set_title(os.path.basename(p) or p)
        self.hb.set_subtitle('%d of %d' % (self.i + 1, len(self.paths)) if len(self.paths) > 1 else None)
        self.prev.set_visible(len(self.paths) > 1)
        self.next.set_visible(len(self.paths) > 1)
        w = preview_widget(p)
        self.body.pack_start(w, True, True, 0)
        self.body.show_all()

    def go(self, d):
        self.i = (self.i + d) % len(self.paths)
        self.show_file()

    def _key(self, w, ev):
        in_text = isinstance(self.get_focus(), Gtk.TextView)
        if ev.keyval == Gdk.KEY_Escape or (ev.keyval == Gdk.KEY_space and not in_text):
            self.destroy()
            return True
        if ev.keyval in (Gdk.KEY_Left, Gdk.KEY_Right) and len(self.paths) > 1 and not in_text:
            self.go(-1 if ev.keyval == Gdk.KEY_Left else 1)
            return True
        return False


class PeekPage(core.Page):
    ID = 'peek'
    TITLE = 'Peek'
    ICON = 'view-paged-symbolic'
    DESC = 'Quickly preview images, text and code files, folders and file details without opening an app.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        drop = core.card(core.label('Drop files here to preview them', 'pt-heading', xalign=0.5),
                         core.label('Also available from the file manager (Scripts → Powerful Tools Peek) after '
                                    'enabling file manager integration in General settings.', 'pt-dim', xalign=0.5))
        drop.set_size_request(-1, 140)
        self.add_widget(drop)
        core.enable_file_drop(self, self.open)
        self.add_widget(core.button_row(core.button('Choose files to preview', lambda: self.open(
            core.choose_files(self.window, 'Preview')), 'document-open-symbolic', suggested=True)))

    def open(self, paths):
        if paths:
            PeekWindow(self.app, paths).show_all()
