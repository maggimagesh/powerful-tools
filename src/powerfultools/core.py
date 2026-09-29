"""Shared GTK helpers: settings, clipboard, screen capture, overlay base, widgets."""
import json
import os
import random
import shutil
import subprocess
import tempfile

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

APP_ID = 'io.github.maggimagesh.PowerfulTools'
APP_NAME = 'Powerful Tools'
VERSION = '1.0.0'
CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), 'powerful-tools')
ENTRY = shutil.which('powerful-tools') or 'powerful-tools'  # replaced by app.main()

CSS = b"""
.pt-title { font-size: x-large; font-weight: bold; }
.pt-subtitle { opacity: 0.75; }
.pt-heading { font-weight: bold; }
.pt-card { padding: 14px; border-radius: 8px;
  border: 1px solid alpha(@theme_fg_color, 0.14);
  background-color: alpha(@theme_fg_color, 0.035); }
.pt-dim { opacity: 0.65; }
.pt-mono { font-family: monospace; }
.pt-error { color: #d0312d; }
.pt-ok { color: #2e8b57; }
.pt-sidebar row { padding: 8px 10px; }
.pt-toast { padding: 8px 14px; border-radius: 0 0 8px 8px;
  background-color: @theme_selected_bg_color; color: @theme_selected_fg_color; }
.pt-toast.error { background-color: #c0392b; color: white; }
.pt-big-entry { font-size: large; padding: 8px; }
.pt-footer { font-size: small; font-style: italic; opacity: 0.45; padding: 5px 12px; }
"""


# ---------------------------------------------------------------- settings

class Settings(object):
    def __init__(self, path=None):
        self.path = path or os.path.join(CONFIG_DIR, 'settings.json')
        self.data = {}
        try:
            with open(self.path) as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data = d
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save()

    def save(self):
        write_file_atomic(self.path, json.dumps(self.data, indent=2, sort_keys=True))


def write_file_atomic(path, text):
    path = os.path.realpath(path)  # keep symlinked dotfiles as symlinks
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.pt-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        if os.path.exists(path):
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---------------------------------------------------------------- processes

def run(args, input_text=None, timeout=30):
    """Run a command; returns (returncode, stdout, stderr). Never raises for a missing binary."""
    try:
        p = subprocess.run(args, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, '', '%s: not found' % args[0]
    except subprocess.TimeoutExpired:
        return 124, '', '%s: timed out' % args[0]
    except OSError as e:
        return 126, '', str(e)


def spawn(args):
    """Start a detached process (it survives this app)."""
    subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def is_wayland():
    d = Gdk.Display.get_default()
    return d is not None and 'Wayland' in type(d).__name__


def is_x11():
    d = Gdk.Display.get_default()
    return d is not None and 'X11' in type(d).__name__ and not os.environ.get('WAYLAND_DISPLAY')


def desktop_name():
    return (os.environ.get('XDG_CURRENT_DESKTOP') or os.environ.get('DESKTOP_SESSION') or 'Unknown')


def open_uri(uri, parent=None):
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
        return True
    except GLib.Error:
        if shutil.which('xdg-open'):
            spawn(['xdg-open', uri])
            return True
        return False


def open_path(path):
    return open_uri(Gio.File.new_for_path(path).get_uri())


# ---------------------------------------------------------------- clipboard

def copy_text(text):
    cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    cb.set_text(text, -1)
    cb.store()


def read_clipboard_text():
    return Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()


# ---------------------------------------------------------------- gsettings

def schema_exists(schema_id):
    src = Gio.SettingsSchemaSource.get_default()
    return src is not None and src.lookup(schema_id, True) is not None


def gsettings(schema_id, path=None):
    if not schema_exists(schema_id):
        return None
    return Gio.Settings.new_with_path(schema_id, path) if path else Gio.Settings.new(schema_id)


MEDIA_KEYS = 'org.gnome.settings-daemon.plugins.media-keys'
CUSTOM_KB = MEDIA_KEYS + '.custom-keybinding'
CUSTOM_KB_PATH = '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/'


def keybindings_supported():
    return schema_exists(MEDIA_KEYS) and schema_exists(CUSTOM_KB)


def list_custom_keybindings():
    s = gsettings(MEDIA_KEYS)
    if not s or 'custom-keybindings' not in s.list_keys():
        return []
    out = []
    for p in s.get_strv('custom-keybindings'):
        k = gsettings(CUSTOM_KB, p)
        out.append({'path': p, 'name': k.get_string('name'), 'command': k.get_string('command'),
                    'binding': k.get_string('binding')})
    return out


def set_custom_keybinding(name, command, binding, path=None):
    s = gsettings(MEDIA_KEYS)
    paths = list(s.get_strv('custom-keybindings'))
    if not path:
        i = 0
        while CUSTOM_KB_PATH + 'custom%d/' % i in paths:
            i += 1
        path = CUSTOM_KB_PATH + 'custom%d/' % i
    k = gsettings(CUSTOM_KB, path)
    k.set_string('name', name)
    k.set_string('command', command)
    k.set_string('binding', binding)
    if path not in paths:
        s.set_strv('custom-keybindings', paths + [path])
    Gio.Settings.sync()
    return path


def remove_custom_keybinding(path):
    s = gsettings(MEDIA_KEYS)
    paths = [p for p in s.get_strv('custom-keybindings') if p != path]
    s.set_strv('custom-keybindings', paths)
    k = gsettings(CUSTOM_KB, path)
    for key in ('name', 'command', 'binding'):
        k.reset(key)
    Gio.Settings.sync()


def accel_label(accel):
    if not accel:
        return 'Not set'
    key, mods = Gtk.accelerator_parse(accel)
    if key == 0 and mods == 0:
        return accel
    return Gtk.accelerator_get_label(key, mods)


# ---------------------------------------------------------------- screen capture

def capture_screen(callback, hide_windows=()):
    """Capture the whole desktop asynchronously. callback(pixbuf or None, error_text)."""
    hidden = [w for w in hide_windows if w is not None and w.get_visible()]
    for w in hidden:
        w.hide()

    def go():
        _capture(callback)
        return False
    GLib.timeout_add(400 if hidden else 50, go)


def _capture(callback):
    if is_x11():
        try:
            root = Gdk.get_default_root_window()
            pb = Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())
            if pb is not None:
                callback(pb, None)
                return
        except Exception:  # fall through to other methods
            pass
    _capture_portal(callback, lambda: _capture_cli(callback))


def _capture_portal(callback, fallback):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        fallback()
        return
    token = 'pt%d' % random.randint(1, 1 << 30)
    sender = bus.get_unique_name()[1:].replace('.', '_')
    req_path = '/org/freedesktop/portal/desktop/request/%s/%s' % (sender, token)
    state = {'done': False, 'sub': 0, 'timer': 0}

    def finish(pb, err, use_fallback=False):
        if state['done']:
            return
        state['done'] = True
        if state['sub']:
            bus.signal_unsubscribe(state['sub'])
        if state['timer']:
            GLib.source_remove(state['timer'])
        if use_fallback:
            fallback()
        else:
            callback(pb, err)

    def on_response(conn, snd, path, iface, sig, params):
        code, results = params.unpack()
        if code != 0:
            finish(None, 'Screenshot was cancelled or denied')
            return
        path = Gio.File.new_for_uri(results.get('uri', '')).get_path()
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file(path)
        except (GLib.Error, TypeError):
            finish(None, 'Could not read screenshot')
            return
        try:
            os.unlink(path)  # portal saves into ~/Pictures; do not leave it there
        except OSError:
            pass
        finish(pb, None)

    def on_called(conn, res):
        try:
            conn.call_finish(res)
        except GLib.Error:
            finish(None, None, use_fallback=True)

    def on_timeout():
        state['timer'] = 0
        finish(None, 'Screenshot timed out')
        return False

    state['sub'] = bus.signal_subscribe('org.freedesktop.portal.Desktop', 'org.freedesktop.portal.Request',
                                        'Response', req_path, None, Gio.DBusSignalFlags.NONE, on_response)
    state['timer'] = GLib.timeout_add_seconds(90, on_timeout)
    opts = {'handle_token': GLib.Variant('s', token), 'interactive': GLib.Variant('b', False)}
    bus.call('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
             'org.freedesktop.portal.Screenshot', 'Screenshot', GLib.Variant('(sa{sv})', ('', opts)),
             GLib.VariantType('(o)'), Gio.DBusCallFlags.NONE, 5000, None, on_called)


def _capture_cli(callback):
    fd, tmp = tempfile.mkstemp(suffix='.png', prefix='pt-shot-')
    os.close(fd)
    os.unlink(tmp)
    for cmd in (['gnome-screenshot', '-f', tmp], ['grim', tmp], ['spectacle', '-b', '-n', '-f', '-o', tmp],
                ['scrot', tmp], ['import', '-window', 'root', tmp]):
        if shutil.which(cmd[0]) and run(cmd, timeout=20)[0] == 0 and os.path.exists(tmp):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(tmp)
                callback(pb, None)
                return
            except GLib.Error:
                pass
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
    callback(None, 'Could not capture the screen. Install gnome-screenshot, grim or scrot.')


class ScreenOverlay(Gtk.Window):
    """Fullscreen window showing a frozen screenshot of one monitor.
    Subclasses draw on top and call self.finish(result)."""

    def __init__(self, pixbuf, on_done, title='Overlay'):
        Gtk.Window.__init__(self, title=title)
        self.on_done = on_done
        self._finished = False
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        display = Gdk.Display.get_default()
        mon_index, geo, union = self._pick_monitor(display)
        ratio = pixbuf.get_width() / float(union.width)
        cx = max(0, int(round((geo.x - union.x) * ratio)))
        cy = max(0, int(round((geo.y - union.y) * ratio)))
        cw = max(1, min(pixbuf.get_width() - cx, int(round(geo.width * ratio))))
        ch = max(1, min(pixbuf.get_height() - cy, int(round(geo.height * ratio))))
        self.src = pixbuf.new_subpixbuf(cx, cy, cw, ch).copy()
        if self.src.get_has_alpha():  # uniform 3-channel access
            flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, cw, ch)
            flat.fill(0x000000ff)
            self.src.composite(flat, 0, 0, cw, ch, 0, 0, 1, 1, GdkPixbuf.InterpType.NEAREST, 255)
            self.src = flat
        self.pixels = self.src.get_pixels()
        self.rowstride = self.src.get_rowstride()
        self.nch = self.src.get_n_channels()
        self.sw, self.sh = cw, ch
        self.mx = self.my = -1  # pointer in widget coords
        self.area = Gtk.DrawingArea()
        self.area.set_can_focus(True)
        self.area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK |
                             Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.area.connect('draw', self._draw)
        self.area.connect('motion-notify-event', self._motion)
        self.area.connect('button-press-event', self.on_press)
        self.area.connect('button-release-event', self.on_release)
        self.connect('key-press-event', self._key)
        self.connect('delete-event', lambda *a: self.finish(None) or True)
        self.connect('realize', self._on_realize)
        self.add(self.area)
        self.move(geo.x, geo.y)
        self.set_default_size(geo.width, geo.height)
        self._mon_index = mon_index

    @staticmethod
    def _pick_monitor(display):
        n = display.get_n_monitors()
        mons = [display.get_monitor(i) for i in range(n)]
        idx = 0
        try:
            seat = display.get_default_seat()
            _s, x, y = seat.get_pointer().get_position()
            m = display.get_monitor_at_point(x, y)
            idx = mons.index(m) if m in mons else 0
        except Exception:
            prim = display.get_primary_monitor()
            idx = mons.index(prim) if prim in mons else 0
        geos = [m.get_geometry() for m in mons]
        u = Gdk.Rectangle()
        u.x, u.y = min(g.x for g in geos), min(g.y for g in geos)
        u.width = max(g.x + g.width for g in geos) - u.x
        u.height = max(g.y + g.height for g in geos) - u.y
        return idx, geos[idx], u

    def _on_realize(self, *_):
        self.fullscreen_on_monitor(self.get_screen(), self._mon_index)
        self.get_window().set_cursor(Gdk.Cursor.new_from_name(Gdk.Display.get_default(), 'crosshair'))

    def present_overlay(self):
        self.show_all()
        self.present()
        self.area.grab_focus()

    # coordinate mapping between widget and source pixels
    def scale(self):
        a = self.area.get_allocation()
        return a.width / float(self.sw), a.height / float(self.sh)

    def to_src(self, x, y):
        sx, sy = self.scale()
        return (min(self.sw - 1, max(0, int(x / sx))), min(self.sh - 1, max(0, int(y / sy))))

    def to_widget(self, px, py):
        sx, sy = self.scale()
        return px * sx, py * sy

    def pixel(self, px, py):
        i = py * self.rowstride + px * self.nch
        return self.pixels[i], self.pixels[i + 1], self.pixels[i + 2]

    def _draw(self, widget, cr):
        sx, sy = self.scale()
        cr.save()
        cr.scale(sx, sy)
        Gdk.cairo_set_source_pixbuf(cr, self.src, 0, 0)
        cr.paint()
        cr.restore()
        self.draw_over(cr)
        return False

    def _motion(self, widget, ev):
        self.mx, self.my = ev.x, ev.y
        self.on_motion(ev)
        self.area.queue_draw()

    def _key(self, widget, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.finish(None)
            return True
        return self.on_key(ev)

    def finish(self, result):
        if self._finished:
            return
        self._finished = True
        self.destroy()
        GLib.idle_add(lambda: self.on_done(result) and False)

    # hooks
    def draw_over(self, cr):
        pass

    def on_motion(self, ev):
        pass

    def on_press(self, widget, ev):
        return False

    def on_release(self, widget, ev):
        return False

    def on_key(self, ev):
        return False


def draw_label(cr, text, x, y, w_max, h_max, pad=6):
    """Draw a readable text badge near (x, y), kept inside the screen."""
    cr.set_font_size(14)
    ext = cr.text_extents(text)
    bw, bh = ext.width + pad * 2, ext.height + pad * 2
    bx = min(max(0, x), w_max - bw)
    by = min(max(0, y), h_max - bh)
    cr.set_source_rgba(0, 0, 0, 0.8)
    cr.rectangle(bx, by, bw, bh)
    cr.fill()
    cr.set_source_rgb(1, 1, 1)
    cr.move_to(bx + pad - ext.x_bearing, by + pad - ext.y_bearing)
    cr.show_text(text)


class RegionSelectOverlay(ScreenOverlay):
    """Drag a rectangle; result is the cropped GdkPixbuf."""
    hint = 'Drag to select an area  ·  Esc to cancel'

    def __init__(self, pixbuf, on_done, title='Select area'):
        ScreenOverlay.__init__(self, pixbuf, on_done, title)
        self.start = None

    def rect(self):
        if not self.start:
            return None
        x0, y0 = self.start
        return min(x0, self.mx), min(y0, self.my), abs(self.mx - x0), abs(self.my - y0)

    def draw_over(self, cr):
        a = self.area.get_allocation()
        cr.set_source_rgba(0, 0, 0, 0.35)
        r = self.rect()
        if r:
            cr.set_fill_rule(1)  # even-odd: dim everything except the selection
            cr.rectangle(0, 0, a.width, a.height)
            cr.rectangle(*r)
            cr.fill()
            cr.set_source_rgb(0.2, 0.6, 1)
            cr.set_line_width(2)
            cr.rectangle(*r)
            cr.stroke()
            (px0, py0), (px1, py1) = self.to_src(r[0], r[1]), self.to_src(r[0] + r[2], r[1] + r[3])
            draw_label(cr, '%d × %d' % (px1 - px0, py1 - py0), r[0], r[1] + r[3] + 6, a.width, a.height)
        else:
            cr.rectangle(0, 0, a.width, a.height)
            cr.fill()
        draw_label(cr, self.hint, a.width / 2 - 150, 20, a.width, a.height)

    def on_press(self, widget, ev):
        if ev.button == 1:
            self.start = (ev.x, ev.y)
            self.mx, self.my = ev.x, ev.y
        elif ev.button == 3:
            self.finish(None)
        return True

    def on_release(self, widget, ev):
        if ev.button != 1 or not self.start:
            return True
        self.mx, self.my = ev.x, ev.y
        x, y, w, h = self.rect()
        (px0, py0), (px1, py1) = self.to_src(x, y), self.to_src(x + w, y + h)
        if px1 - px0 < 3 or py1 - py0 < 3:
            self.start = None
            self.area.queue_draw()
            return True
        self.finish(self.src.new_subpixbuf(px0, py0, px1 - px0 + 1, py1 - py0 + 1).copy())
        return True


# ---------------------------------------------------------------- widgets

def label(text, cls=None, wrap=True, xalign=0.0, selectable=False, markup=False):
    lb = Gtk.Label()
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    lb.set_xalign(xalign)
    lb.set_line_wrap(wrap)
    if wrap:
        lb.set_line_wrap_mode(2)  # PANGO WRAP_WORD_CHAR: long paths never force width
    lb.set_selectable(selectable)
    for c in (cls or '').split():
        lb.get_style_context().add_class(c)
    return lb


def card(*children, spacing=10, title=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.get_style_context().add_class('pt-card')
    if title:
        box.pack_start(label(title, 'pt-heading'), False, False, 0)
    for c in children:
        box.pack_start(c, False, False, 0)
    return box


def row(title, subtitle, widget):
    """A setting row: text on the left, control on the right."""
    box = Gtk.Box(spacing=12)
    txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    txt.pack_start(label(title), False, False, 0)
    if subtitle:
        txt.pack_start(label(subtitle, 'pt-dim'), False, False, 0)
    box.pack_start(txt, True, True, 0)
    if widget is not None:
        widget.set_valign(Gtk.Align.CENTER)
        box.pack_end(widget, False, False, 0)
    return box


def button(text, cb=None, icon=None, suggested=False, destructive=False, tooltip=None):
    b = Gtk.Button()
    if icon and text:
        bx = Gtk.Box(spacing=6)
        bx.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
        bx.pack_start(Gtk.Label(label=text), False, False, 0)
        b.add(bx)
    elif icon:
        b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
    else:
        b.set_label(text)
    if suggested:
        b.get_style_context().add_class('suggested-action')
    if destructive:
        b.get_style_context().add_class('destructive-action')
    if tooltip or (icon and not text):
        b.set_tooltip_text(tooltip or text or '')
    if cb:
        b.connect('clicked', lambda *_: cb())
    return b


def button_row(*buttons):
    """Buttons that wrap onto new lines on narrow windows."""
    fb = Gtk.FlowBox()
    fb.set_selection_mode(Gtk.SelectionMode.NONE)
    fb.set_homogeneous(False)
    fb.set_column_spacing(8)
    fb.set_row_spacing(8)
    fb.set_max_children_per_line(20)
    for b in buttons:
        fb.add(b)
        b.get_parent().set_can_focus(False)
    return fb


def combo(options, active=None, on_change=None):
    """options: [(id, label)]"""
    c = Gtk.ComboBoxText()
    for oid, text in options:
        c.append(oid, text)
    c.set_active_id(active if active is not None else options[0][0])
    if on_change:
        c.connect('changed', lambda w: on_change(w.get_active_id()))
    return c


def spin(lo, hi, value, step=1, on_change=None, digits=0):
    s = Gtk.SpinButton.new_with_range(lo, hi, step)
    s.set_digits(digits)
    s.set_value(value)
    if on_change:
        s.connect('value-changed', lambda w: on_change(w.get_value()))
    return s


def scrolled(child, min_h=0, hpolicy=Gtk.PolicyType.AUTOMATIC):
    sw = Gtk.ScrolledWindow()
    sw.set_policy(hpolicy, Gtk.PolicyType.AUTOMATIC)
    sw.set_shadow_type(Gtk.ShadowType.IN)
    if min_h:
        sw.set_min_content_height(min_h)
    sw.add(child)
    return sw


def paths_from_uris(uris):
    out = []
    for u in uris or []:
        p = Gio.File.new_for_uri(u).get_path()
        if p:
            out.append(p)
    return out


def enable_file_drop(widget, callback):
    widget.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new('text/uri-list', 0, 0)],
                         Gdk.DragAction.COPY)

    def on_data(w, ctx, x, y, data, info, time):
        paths = paths_from_uris(data.get_uris())
        if paths:
            callback(paths)
    widget.connect('drag-data-received', on_data)


def choose_files(parent, title='Choose files', folders=False, multiple=True, mime_filter=None, save=False):
    action = (Gtk.FileChooserAction.SAVE if save else
              Gtk.FileChooserAction.SELECT_FOLDER if folders else Gtk.FileChooserAction.OPEN)
    dlg = Gtk.FileChooserDialog(title=title, transient_for=parent, action=action)
    dlg.add_buttons('_Cancel', Gtk.ResponseType.CANCEL, '_Select' if not save else '_Save', Gtk.ResponseType.ACCEPT)
    dlg.set_select_multiple(multiple and not save)
    if mime_filter:
        f = Gtk.FileFilter()
        f.set_name(mime_filter[0])
        for m in mime_filter[1]:
            f.add_mime_type(m)
        dlg.add_filter(f)
    res = dlg.run()
    paths = dlg.get_filenames() if res == Gtk.ResponseType.ACCEPT else []
    dlg.destroy()
    return paths


def message(parent, text, secondary=None, error=False):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True,
                            message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
                            buttons=Gtk.ButtonsType.OK, text=text)
    if secondary:
        dlg.format_secondary_text(secondary)
    dlg.run()
    dlg.destroy()


def confirm(parent, text, secondary=None, ok='OK'):
    dlg = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                            buttons=Gtk.ButtonsType.NONE, text=text)
    if secondary:
        dlg.format_secondary_text(secondary)
    dlg.add_buttons('_Cancel', Gtk.ResponseType.CANCEL, ok, Gtk.ResponseType.OK)
    res = dlg.run()
    dlg.destroy()
    return res == Gtk.ResponseType.OK


class ShortcutCapture(Gtk.Dialog):
    """Modal dialog: press a key combination; returns an accelerator string or None."""

    def __init__(self, parent):
        Gtk.Dialog.__init__(self, title='Set shortcut', transient_for=parent, modal=True)
        self.add_button('_Cancel', Gtk.ResponseType.CANCEL)
        self.accel = None
        box = self.get_content_area()
        box.set_border_width(18)
        box.set_spacing(8)
        box.add(label('Press the key combination you want to use.', xalign=0.5))
        box.add(label('Use at least one modifier (Ctrl, Alt, Super). Backspace clears, Esc cancels.',
                      'pt-dim', xalign=0.5))
        self.connect('key-press-event', self._key)
        self.show_all()

    def _key(self, w, ev):
        mods = ev.state & Gtk.accelerator_get_default_mod_mask()
        kv = Gdk.keyval_to_lower(ev.keyval)
        if kv == Gdk.KEY_Escape and not mods:
            self.response(Gtk.ResponseType.CANCEL)
        elif kv == Gdk.KEY_BackSpace and not mods:
            self.accel = ''
            self.response(Gtk.ResponseType.OK)
        elif kv in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Control_L, Gdk.KEY_Control_R,
                    Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R,
                    Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift):
            return True
        elif mods and Gtk.accelerator_valid(kv, mods):
            self.accel = Gtk.accelerator_name(kv, mods)
            self.response(Gtk.ResponseType.OK)
        return True

    def get(self):
        res = self.run()
        self.destroy()
        return self.accel if res == Gtk.ResponseType.OK else None


class Page(Gtk.ScrolledWindow):
    """Base class for every tool page."""
    ID = ''
    TITLE = ''
    ICON = 'application-x-executable-symbolic'
    DESC = ''

    def __init__(self, app):
        Gtk.ScrolledWindow.__init__(self)
        self.app = app
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.outer.set_border_width(24)
        self.outer.pack_start(label(self.TITLE, 'pt-title'), False, False, 0)
        if self.DESC:
            self.outer.pack_start(label(self.DESC, 'pt-subtitle'), False, False, 0)
        self.add(self.outer)
        self.get_child().set_shadow_type(Gtk.ShadowType.NONE)

    @property
    def window(self):
        return self.get_toplevel() if self.get_toplevel().is_toplevel() else None

    def add_widget(self, w, expand=False):
        self.outer.pack_start(w, expand, expand, 0)
        return w

    def toast(self, text, error=False):
        win = self.window
        if win is not None and hasattr(win, 'toast'):
            win.toast(text, error)
        else:
            message(win, text, error=error)

    def set_narrow(self, narrow):
        self.outer.set_border_width(12 if narrow else 24)

    def on_shown(self):
        pass
