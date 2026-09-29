import shutil
import time

from gi.repository import Gio, GLib, Gtk

from . import core

WATCH_MS = 250  # how quickly a dropped "above" state is restored


def supported():
    return core.is_x11() and bool(shutil.which('wmctrl')) and bool(shutil.which('xprop'))


SKIP_TYPES = ('_NET_WM_WINDOW_TYPE_DESKTOP', '_NET_WM_WINDOW_TYPE_DOCK', '_NET_WM_WINDOW_TYPE_SPLASH',
              '_NET_WM_WINDOW_TYPE_TOOLBAR', '_NET_WM_WINDOW_TYPE_MENU', '_NET_WM_WINDOW_TYPE_NOTIFICATION')


def norm(wid):
    """wmctrl pads window ids (0x0240004a), xprop does not (0x240004a): compare normalised."""
    return '0x%08x' % int(wid, 16)


def _props(wid):
    """(window exists, xprop output)"""
    rc, out, _ = core.run(['xprop', '-id', wid, '_NET_WM_WINDOW_TYPE', '_NET_WM_STATE'], timeout=5)
    return rc == 0, out


def is_pinned(wid):
    return '_NET_WM_STATE_ABOVE' in _props(wid)[1]


def list_windows():
    """[(id, title, pinned)] of normal application windows via wmctrl (X11)."""
    out = core.run(['wmctrl', '-l'])[1]
    wins = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        # workspace -1 is also used for ordinary windows (other monitors), so filter by window type instead
        wid, title = norm(parts[0]), parts[3] if len(parts) == 4 else ''
        alive, props = _props(wid)
        if not alive or any(t in props for t in SKIP_TYPES):
            continue
        wins.append((wid, title, '_NET_WM_STATE_ABOVE' in props))
    return wins


def wait_pinned(wid, want, timeout=1.5):
    """The window manager applies state changes asynchronously; poll briefly."""
    end = time.monotonic() + timeout
    while True:
        if is_pinned(wid) == want:
            return True
        if time.monotonic() > end:
            return False
        time.sleep(0.05)


def set_pinned(wid, on):
    """Explicit add/remove: reliable, unlike rapid toggles."""
    return core.run(['wmctrl', '-i', '-r', wid, '-b', ('add' if on else 'remove') + ',above'])[0] == 0


def active_window():
    out = core.run(['xprop', '-root', '_NET_ACTIVE_WINDOW'])[1] if shutil.which('xprop') else ''
    wid = out.strip().split()[-1] if out.strip() else ''
    try:
        return norm(wid) if int(wid, 16) != 0 else None
    except ValueError:
        return None


class PinKeeper(object):
    """Keeps pinned windows floating above all others.
    Browsers and Electron apps rewrite their own window state (e.g. on tab or focus changes), which
    silently drops 'above'; this puts it back within WATCH_MS for as long as the window stays pinned."""

    def __init__(self, app):
        self.app = app
        self.pinned = {}  # normalised wid -> title
        self.timer = 0
        self.held = False
        self.listeners = []

    def is_pinned(self, wid):
        return norm(wid) in self.pinned

    def pin(self, wid, title=''):
        wid = norm(wid)
        if not (set_pinned(wid, True) and wait_pinned(wid, True)):
            return False
        self.pinned[wid] = title
        if not self.timer:
            self.timer = GLib.timeout_add(WATCH_MS, self._watch)
        if not self.held:  # keep the process alive in the background while something is pinned
            self.app.hold()
            self.held = True
        self._changed()
        return True

    def unpin(self, wid):
        wid = norm(wid)
        self.pinned.pop(wid, None)
        ok = set_pinned(wid, False) and wait_pinned(wid, False)
        self._settle()
        self._changed()
        return ok

    def toggle(self, wid=None):
        wid = wid or active_window()
        if wid is None:
            return False
        if self.is_pinned(wid) or is_pinned(wid):
            return self.unpin(wid)
        return self.pin(wid)

    def unpin_all(self):
        for wid in list(self.pinned):
            del self.pinned[wid]
            set_pinned(wid, False)
        self._settle()
        self._changed()

    def _settle(self):
        """Stop watching and let the app exit normally once nothing is pinned."""
        if self.pinned:
            return
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.held:
            self.held = False
            self.app.release()

    def _watch(self):
        closed = False
        for wid in list(self.pinned):
            alive, props = _props(wid)
            if not alive:
                del self.pinned[wid]
                closed = True
            elif '_NET_WM_STATE_ABOVE' not in props:
                set_pinned(wid, True)  # the app dropped it: put it back on top
        if not self.pinned:
            self.timer = 0  # returning False below removes this source
            self._settle()
        if closed:
            self._changed()
        return bool(self.pinned)

    def _changed(self):
        for cb in list(self.listeners):
            cb()


def notify_background(app):
    n = Gio.Notification.new('Always On Top is still active')
    n.set_body('Pinned windows stay on top. Open Powerful Tools to unpin them.')
    app.send_notification('pins', n)


WAYLAND_HELP = ('Linux Wayland desktops do not let apps change other windows, but they have this feature built in:\n'
                '• GNOME / Ubuntu: press Alt+Space (or right-click the title bar) and choose "Always on Top".\n'
                '• KDE Plasma: press Alt+F3 → More Actions → Keep Above Others.\n'
                'On an X11 session with wmctrl and xprop installed, Powerful Tools can pin windows directly.')


class AlwaysOnTopPage(core.Page):
    ID = 'alwaysontop'
    TITLE = 'Always On Top'
    ICON = 'go-top-symbolic'
    DESC = ('Pin windows so they float above all other windows, even when you switch to another app. '
            'While a window is pinned, Powerful Tools keeps running in the background to hold it on top.')

    def __init__(self, app):
        core.Page.__init__(self, app)
        if not supported():
            why = WAYLAND_HELP if not core.is_x11() else \
                'Install wmctrl and x11-utils to use this tool:  sudo apt install wmctrl x11-utils'
            self.add_widget(core.card(core.label(why, selectable=True), title='How to pin windows here'))
            return
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_widget(core.card(self.box, core.button_row(
            core.button('Refresh', self.refresh, 'view-refresh-symbolic'),
            core.button('Unpin all', app.pins.unpin_all, 'view-restore-symbolic')), title='Open windows'))
        self.add_widget(core.card(core.label('Tip: set a global shortcut in Keyboard Manager to pin or unpin '
                                             'whichever window is focused.', 'pt-dim')))
        app.pins.listeners.append(self._queue_refresh)
        self.connect('destroy', lambda *_: app.pins.listeners.remove(self._queue_refresh))

    def on_shown(self):
        if supported():
            self.refresh()

    def refresh(self):
        for c in self.box.get_children():
            c.destroy()
        wins = list_windows()
        if not wins:
            self.box.pack_start(core.label('No windows found.', 'pt-dim'), False, False, 0)
        for wid, title, pinned in wins:
            sw = Gtk.Switch(active=pinned or self.app.pins.is_pinned(wid))
            sw.connect('notify::active', self._switched, wid, title)
            self.box.pack_start(core.row(title or '(untitled)', None, sw), False, False, 0)
        self.box.show_all()

    def _queue_refresh(self):
        # never rebuild the list from inside a switch's own signal handler
        GLib.idle_add(lambda: self.refresh() and False)

    def _switched(self, sw, _pspec, wid, title):
        pins = self.app.pins
        ok = pins.pin(wid, title) if sw.get_active() else pins.unpin(wid)
        if not ok:
            self.toast('Could not change this window (it may have closed)', error=True)
            self._queue_refresh()
