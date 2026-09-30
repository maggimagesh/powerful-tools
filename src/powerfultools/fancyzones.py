import os
import re
import time

import gi
from gi.repository import Gdk, GLib, Gtk

from . import alwaysontop, core, logic

try:
    gi.require_version('GdkX11', '3.0')
    from gi.repository import GdkX11  # also gives other apps' windows their get_xid
except (ValueError, ImportError):
    GdkX11 = None

TICK_MS = 120  # how often the pointer is looked at
DWELL = 3  # ticks the pointer must rest on a maximize button before the zone view opens
SHADOW = 70  # widest invisible border that apps draw around their windows
STRIP = (200, 4, 26)  # part of a window's top corner that is searched for its buttons: width, first and last row
ALL_DESKTOPS = 0xFFFFFFFF
AUTOSTART = os.path.join(GLib.get_user_config_dir(), 'autostart', 'powerful-tools-zones.desktop')


def supported():
    return GdkX11 is not None and alwaysontop.supported()


def pointer():
    _screen, x, y = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
    return x, y


def scale():
    """GTK counts in scaled pixels, wmctrl and xprop in real ones. X11 has one scale for all monitors."""
    return Gdk.Display.get_default().get_monitor(0).get_scale_factor()


def inside(rect, x, y):
    return rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def props(wid):
    """(window exists, its state and type as text, frame extents, shadow extents): see logic.window_geometry."""
    rc, out, _ = core.run(['xprop', '-id', wid, '_NET_WM_STATE', '_NET_WM_WINDOW_TYPE', '_NET_FRAME_EXTENTS',
                           '_GTK_FRAME_EXTENTS'], timeout=5)
    ext = dict((name, tuple(int(v) for v in vals.split(',')))
               for name, vals in re.findall(r'_(NET|GTK)_FRAME_EXTENTS\(CARDINAL\) = (\d+, \d+, \d+, \d+)', out))
    return rc == 0, out, ext.get('NET', (0, 0, 0, 0)), ext.get('GTK', (0, 0, 0, 0))


def frames():
    """[(id, (x, y, w, h))] of the windows on this workspace, topmost first. Shadows are part of the frame."""
    screen = Gdk.Screen.get_default()
    out = []
    display = screen.get_display()
    display.error_trap_push()  # a window that closes while it is being read is an X error, which would end the app
    try:
        for w in reversed(screen.get_window_stack() or []):
            if w.get_desktop() in (screen.get_current_desktop(), ALL_DESKTOPS):
                r = w.get_frame_extents()
                out.append(('0x%08x' % w.get_xid(), (r.x, r.y, r.width, r.height)))
    finally:
        display.error_trap_pop_ignored()
    return out


def visible(rect, shadow):
    left, right, top, bottom = [v // scale() for v in shadow]
    return rect[0] + left, rect[1] + top, rect[2] - left - right, rect[3] - top - bottom


def window_at(x, y, wins=None):
    """(id, visible frame) of the topmost application window under a point, or None."""
    for wid, rect in frames() if wins is None else wins:
        if not inside(rect, x, y):
            continue
        alive, text, _frame, shadow = props(wid)
        rect = visible(rect, shadow)
        if alive and '_NET_WM_STATE_HIDDEN' not in text and inside(rect, x, y):
            return None if any(t in text for t in alwaysontop.SKIP_TYPES) else (wid, rect)
    return None


def seen_button(layout, rect):
    """The maximize button as the window really draws it, or None if its buttons cannot be made out."""
    left, _sep, right = layout.partition(':')
    side = right if 'maximize' in right else left
    names = [b for b in side.split(',') if b in ('minimize', 'maximize', 'close')]
    width, top, bottom = STRIP
    x0 = rect[0] + rect[2] - width if side is right else rect[0]
    pb = 'maximize' in names and Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), x0, rect[1] + top,
                                                            width, bottom - top)
    found = pb and logic.button_slots(pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels(), pb.get_width(),
                                      pb.get_height(), len(names), side is right)
    if not found:
        return None
    k = pb.get_width() / float(width)  # captures are in real pixels
    a, b = found[0][names.index('maximize')]
    return x0 + int(a / k), rect[1], int((b - a) / k), 2 * (top + int(found[1] / k))  # glyphs sit mid title bar


def hovered_button(x, y):
    """(window id, maximize button rect) if the point is on a window's maximize button, else None."""
    layout = Gtk.Settings.get_default().get_property('gtk-decoration-layout') or ''
    wins = frames()

    def button(rect):
        return logic.maximize_button_rect(layout, rect[0], rect[1], rect[2])
    # in-process test first: most of the time no window has its button anywhere near the pointer,
    # and finding out which window is really under it costs a subprocess per candidate
    near = [b for b in (button(r) for _w, r in wins) if b]
    if not any(inside((b[0] - SHADOW, b[1] - SHADOW, b[2] + 2 * SHADOW, b[3] + 2 * SHADOW), x, y) for b in near):
        return None
    hit = window_at(x, y, wins)
    b = hit and (seen_button(layout, hit[1]) or button(hit[1]))
    return (hit[0], b) if b and inside(b, x, y) else None


def workarea(wid):
    """Usable area of the monitor that shows a window."""
    d = Gdk.Display.get_default()
    rect = dict(frames()).get(wid)
    mon = d.get_monitor_at_point(rect[0] + rect[2] // 2, rect[1] + rect[3] // 2) if rect else \
        d.get_primary_monitor() or d.get_monitor(0)
    wa = mon.get_workarea()
    return wa.x, wa.y, wa.width, wa.height


def place(wid, rect):
    """Bring a window to the front and make it fill rect exactly."""
    core.run(['wmctrl', '-i', '-R', wid])  # also restores it from minimized or another workspace
    _alive, text, frame, shadow = props(wid)
    if 'MAXIMIZED' in text or 'FULLSCREEN' in text:
        core.run(['wmctrl', '-i', '-r', wid, '-b', 'remove,maximized_vert,maximized_horz'])
        core.run(['wmctrl', '-i', '-r', wid, '-b', 'remove,fullscreen'])
        time.sleep(0.1)  # the app redraws its borders for the new state
        frame, shadow = props(wid)[2:]
    geo = logic.window_geometry([v * scale() for v in rect], frame, shadow)
    return core.run(['wmctrl', '-i', '-r', wid, '-e', '0,%d,%d,%d,%d' % geo])[0] == 0


def arrange(app, wid, n):
    """Put a window in the main zone, then ask which windows take the other zones."""
    zones = logic.zone_rects(n, *workarea(wid))
    place(wid, zones[0])
    others = [(w, title) for w, title, _pinned in alwaysontop.list_windows() if w != wid]
    return ZonePicker(app, zones[1:], others) if others else None


def set_autostart(on):
    """Start the app without its window at login, so hovering works before it is opened."""
    if on:
        if re.search(r'[\x00-\x1f"`$\\%]', core.ENTRY):  # these would need escaping in a desktop entry
            raise OSError('unsupported character in the install path %r' % core.ENTRY)
        core.write_file_atomic(AUTOSTART, '[Desktop Entry]\nType=Application\nName=Powerful Tools (Fancy Zones)\n'
                               'TryExec=%s\nExec="%s" --background\nIcon=powerful-tools\n' % (core.ENTRY, core.ENTRY))
    elif os.path.exists(AUTOSTART):
        os.unlink(AUTOSTART)


def layout_icon(n):
    """A small picture of the layout for n windows, the main zone highlighted."""
    area = Gtk.DrawingArea()
    area.set_size_request(66, 42)

    def draw(w, cr):
        fg = w.get_style_context().get_color(w.get_state_flags())
        for i, (x, y, zw, zh) in enumerate(logic.zone_rects(n, 0, 0, w.get_allocated_width(),
                                                            w.get_allocated_height())):
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.8 if i == 0 else 0.3)
            cr.rectangle(x + 1, y + 1, zw - 2, zh - 2)
            cr.fill()
    area.connect('draw', draw)
    return area


class ZonePopup(Gtk.Window):
    """The zone view: choose how many windows share the screen. Closes when the pointer moves away."""

    def __init__(self, app, wid, anchor):
        Gtk.Window.__init__(self, type=Gtk.WindowType.POPUP)  # never takes focus from the window it belongs to
        self.app, self.wid, self.anchor = app, wid, anchor
        self.away = 0
        box = Gtk.Box(spacing=6)
        box.set_border_width(8)
        for n in (2, 3, 4):
            b = Gtk.Button(tooltip_text='%d windows' % n)
            b.add(layout_icon(n))
            b.connect('clicked', lambda _b, n=n: self.choose(n))
            box.pack_start(b, False, False, 0)
        self.add(box)
        box.show_all()
        width = self.get_preferred_size()[1].width
        mon = Gdk.Display.get_default().get_monitor_at_point(anchor[0], anchor[1]).get_geometry()
        x = anchor[0] + anchor[2] // 2 - width // 2
        self.move(min(max(mon.x, x), mon.x + mon.width - width), anchor[1] + anchor[3])
        self.timer = GLib.timeout_add(TICK_MS, self._watch)
        self.connect('destroy', self._gone)
        self.show()

    def _watch(self):
        (x, y), (px, py), (w, h) = pointer(), self.get_position(), self.get_size()
        self.away = 0 if inside(self.anchor, x, y) or inside((px - 6, py - 6, w + 12, h + 12), x, y) else self.away + 1
        if self.away > 2:
            self.timer = 0
            self.destroy()
        return bool(self.timer)

    def _gone(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def choose(self, n):
        self.destroy()
        arrange(self.app, self.wid, n)


class ZonePicker(Gtk.Window):
    """Sits in the next free zone and lists the open windows: click one to put it there. Esc cancels."""
    MARGIN = 24

    def __init__(self, app, zones, windows):
        Gtk.Window.__init__(self, title='Fancy Zones')
        if isinstance(app, Gtk.Application):
            self.set_application(app)
        self.zones, self.windows = list(zones), list(windows)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(16)
        box.pack_start(core.label('Choose a window for this zone', 'pt-title'), False, False, 0)
        box.pack_start(core.scrolled(self.list, hpolicy=Gtk.PolicyType.NEVER), True, True, 0)
        box.pack_start(core.button_row(core.button('Cancel (Esc)', self.destroy)), False, False, 0)
        self.add(box)
        self.connect('key-press-event', self._key)
        self.next()

    def next(self):
        if not self.zones or not self.windows:
            self.destroy()
            return
        for c in self.list.get_children():
            c.destroy()
        for wid, title in self.windows:
            b = core.button(title or '(untitled)', lambda w=wid: self.pick(w))
            b.get_child().set_xalign(0)
            b.get_child().set_ellipsize(3)  # Pango END: a long title never widens the zone
            self.list.pack_start(b, False, False, 0)
        x, y, w, h = self.zones[0]
        self.resize(max(1, w - 2 * self.MARGIN), max(1, h - 2 * self.MARGIN))
        self.move(x + self.MARGIN, y + self.MARGIN)
        self.show_all()
        # the window just placed took the focus; only a newer timestamp than its own gets it back, for Esc
        self.present_with_time(GdkX11.x11_get_server_time(self.get_window()))

    def pick(self, wid):
        place(wid, self.zones.pop(0))
        self.windows = [w for w in self.windows if w[0] != wid]
        self.next()

    def _key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False


class Zones(object):
    """Opens the zone view when the pointer rests on a window's maximize button, or on request."""

    def __init__(self, app):
        self.app = app
        self.timer = 0
        self.last = None
        self.still = 0
        self.popup = None

    @property
    def enabled(self):
        return bool(self.timer)

    def set_enabled(self, on):
        if on and not self.timer:
            self.timer = GLib.timeout_add(TICK_MS, self._tick)
            self.app.hold()  # keep watching in the background, even with no window open
        elif not on and self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
            self.app.release()

    def apply(self):
        """Follow the setting: hovering is on until the user turns it off. Returns an error text, if any."""
        on = supported() and self.app.settings.get('zones_hover', True)
        self.set_enabled(on)
        try:
            set_autostart(on)
        except OSError as e:
            return str(e)

    def _tick(self):
        pos = pointer()
        self.still = self.still + 1 if pos == self.last else 0
        self.last = pos
        if self.still == DWELL and self.popup is None:
            hit = hovered_button(*pos)
            if hit:
                self.show(*hit)
        return True

    def show(self, wid, anchor):
        if self.popup:
            self.popup.destroy()
        self.popup = ZonePopup(self.app, wid, anchor)
        self.popup.connect('destroy', self._closed)

    def _closed(self, popup):
        if self.popup is popup:
            self.popup = None

    def show_for_active(self):
        """Keyboard shortcut: the zone view for the focused window, right under the pointer."""
        wid = alwaysontop.active_window()
        if wid:
            x, y = pointer()
            self.show(wid, (x - 20, y - 20, 40, 24))
        return bool(wid)


WAYLAND_HELP = ('Linux Wayland desktops do not let apps move other windows, but they can tile windows themselves:\n'
                '• GNOME / Ubuntu: drag a window to the left or right screen edge, or press Super+Left / Super+Right.\n'
                '• KDE Plasma: drag a window to a screen edge or corner, or press Meta+Arrow keys.\n'
                'On an X11 session with wmctrl and xprop installed, Powerful Tools can arrange windows directly.')


class FancyZonesPage(core.Page):
    ID = 'fancyzones'
    TITLE = 'Fancy Zones'
    ICON = 'view-grid-symbolic'
    DESC = ('Arrange windows side by side. Rest the pointer on a window\'s maximize button, choose a layout for '
            '2, 3 or 4 windows, then pick the windows that fill the other zones.')

    def __init__(self, app):
        core.Page.__init__(self, app)
        if not supported():
            why = WAYLAND_HELP if not core.is_x11() else \
                'Install wmctrl and x11-utils to use this tool:  sudo apt install wmctrl x11-utils'
            self.add_widget(core.card(core.label(why, selectable=True), title='How to arrange windows here'))
            return
        self.switch = Gtk.Switch(active=app.zones.enabled)
        self.switch.connect('notify::active', lambda sw, _p: self.set_hover(sw.get_active()))
        hover = core.card(core.row('Open the zone view from the maximize button',
                                   'While this is on, Powerful Tools keeps running in the background and starts '
                                   'when you log in.', self.switch), title='Maximize button')
        if 'maximize' not in (Gtk.Settings.get_default().get_property('gtk-decoration-layout') or ''):
            hover.pack_start(core.label('Your desktop does not show a maximize button on windows. Use the keyboard '
                                        'shortcut instead.', 'pt-dim'), False, False, 0)
        self.add_widget(hover)
        layouts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for n, text in ((2, 'The main window takes the left half, the second one the right half.'),
                        (3, 'The main window takes the left half, two more share the right half.'),
                        (4, 'Each window takes a quarter of the screen.')):
            layouts.pack_start(core.row('%d windows' % n, text, layout_icon(n)), False, False, 0)
        self.add_widget(core.card(layouts, core.label(
            'The window you started from is the main one. For every other zone you choose a window from a list; '
            'press Esc to stop and leave the remaining zones empty.', 'pt-dim'), title='Layouts'))
        self.add_widget(core.card(core.label('Tip: set a global shortcut in Keyboard Manager to open the zone view '
                                             'for whichever window is focused.', 'pt-dim')))

    def set_hover(self, on):
        self.app.settings.set('zones_hover', on)
        err = self.app.zones.apply()
        if err:
            self.toast('Could not change the login setting: %s' % err, error=True)
