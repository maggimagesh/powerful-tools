"""Touchpad Gestures: macOS-style three- and four-finger swipes, pinches, edge swipes and three-finger drag.

Fingers are read straight from the touchpad (evdev), next to the desktop's own driver, which keeps moving the
pointer and scrolling as usual. GNOME on X11 has no multi-finger gestures, so nothing is done twice.
Actions are sent as the key combinations the desktop is set up with (XTest), or through wmctrl / D-Bus."""
import ctypes
import errno
import fcntl
import glob
import os
import struct

from gi.repository import Gdk, Gio, GLib, Gtk

from . import alwaysontop, core, fancyzones, logic

AUTOSTART = os.path.join(GLib.get_user_config_dir(), 'autostart', 'powerful-tools-gestures.desktop')
UDEV_RULE = '/etc/udev/rules.d/70-powerful-tools-touchpad.rules'
RULE_TEXT = ('# Powerful Tools: the logged-in user may read the touchpad (touchpads only, never keyboards)\n'
             'SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_TOUCHPAD}=="1", TAG+="uaccess"\n')
RETRY_SECS = 5

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT = 0
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x2f, 0x35, 0x36, 0x39
BTN_TOOLS = {0x145: 1, 0x14d: 2, 0x14e: 3, 0x14f: 4, 0x148: 5}  # BTN_TOOL_FINGER .. QUINTTAP
EVENT = struct.Struct('llHHi')  # struct input_event on 64-bit Linux

WM = 'org.gnome.desktop.wm.keybindings'
SHELL = 'org.gnome.shell.keybindings'
# action -> the desktop's own shortcut for it, and the usual one when that is not set
BOUND = {
    'app-grid': (SHELL, 'toggle-application-view', '<Super>a'),
    'notifications': (SHELL, 'toggle-message-tray', '<Super>v'),
    'workspace-left': (WM, 'switch-to-workspace-left', '<Control><Alt>Left'),
    'workspace-right': (WM, 'switch-to-workspace-right', '<Control><Alt>Right'),
    'switch-app': (WM, 'switch-applications', '<Alt>Tab'),
    'switch-app-back': (WM, 'switch-applications-backward', '<Shift><Alt>Tab'),
    'maximize': (WM, 'toggle-maximized', '<Alt>F10'),
    'minimize': (WM, 'minimize', '<Super>h'),
    'close-window': (WM, 'close', '<Alt>F4'),
}
KEYS = {'back': '<Alt>Left', 'forward': '<Alt>Right', 'zoom-in': '<Control>equal', 'zoom-out': '<Control>minus',
        'rotate-cw': '<Control>r', 'rotate-ccw': '<Control><Shift>r', 'volume-up': 'XF86AudioRaiseVolume',
        'volume-down': 'XF86AudioLowerVolume', 'mute': 'XF86AudioMute', 'brightness-up': 'XF86MonBrightnessUp',
        'brightness-down': 'XF86MonBrightnessDown', 'play-pause': 'XF86AudioPlay'}
ACTIONS = [
    ('none', 'Do nothing'), ('overview', 'Show all windows (overview)'),
    ('app-windows', "Show the app's windows (App Exposé)"), ('app-grid', 'Show all apps'),
    ('workspace-left', 'Workspace on the left'), ('workspace-right', 'Workspace on the right'),
    ('show-desktop', 'Show the desktop (again: bring the windows back)'), ('switch-app', 'Switch to the next app'),
    ('switch-app-back', 'Switch to the previous app'), ('maximize', 'Maximize or restore the window'),
    ('minimize', 'Minimize the window'), ('tile-left', 'Window to the left half'),
    ('tile-right', 'Window to the right half'), ('close-window', 'Close the window'), ('back', 'Back'),
    ('forward', 'Forward'), ('zoom-in', 'Zoom in'), ('zoom-out', 'Zoom out'), ('rotate-cw', 'Rotate right'),
    ('rotate-ccw', 'Rotate left'), ('notifications', 'Notifications and calendar'),
    ('launcher', 'Open Quick Launcher'), ('volume-up', 'Volume up'), ('volume-down', 'Volume down'),
    ('mute', 'Mute or unmute'), ('play-pause', 'Play or pause media'), ('brightness-up', 'Screen brighter'),
    ('brightness-down', 'Screen dimmer'), ('middle-click', 'Middle click'),
]
# (group, [(gesture, label, default action)])
GESTURES = [
    ('Three fingers', [
        ('swipe3-up', 'Swipe up', 'overview'), ('swipe3-down', 'Swipe down', 'show-desktop'),
        ('swipe3-left', 'Swipe left', 'workspace-right'), ('swipe3-right', 'Swipe right', 'workspace-left'),
        ('swipe3-up-left', 'Swipe up and left', 'tile-left'), ('swipe3-up-right', 'Swipe up and right', 'tile-right'),
        ('pinch3-in', 'Pinch in', 'none'), ('pinch3-out', 'Spread out', 'none')]),
    ('Four fingers', [
        ('swipe4-up', 'Swipe up', 'maximize'), ('swipe4-down', 'Swipe down', 'minimize'),
        ('swipe4-left', 'Swipe left', 'switch-app'), ('swipe4-right', 'Swipe right', 'switch-app-back'),
        ('pinch4-in', 'Pinch in', 'app-grid'), ('pinch4-out', 'Spread out', 'app-windows')]),
    ('Two fingers', [
        ('swipe2-left', 'Quick swipe left (browsers and file managers)', 'back'),
        ('swipe2-right', 'Quick swipe right (browsers and file managers)', 'forward'),
        ('pinch2-out', 'Spread out (repeats while you spread)', 'zoom-in'),
        ('pinch2-in', 'Pinch in (repeats while you pinch)', 'zoom-out'),
        ('rotate2-cw', 'Rotate clockwise (image viewers)', 'rotate-cw'),
        ('rotate2-ccw', 'Rotate anticlockwise (image viewers)', 'rotate-ccw')]),
    ('From the edge, with two fingers', [
        ('edge-right', 'Swipe in from the right edge', 'notifications'),
        ('edge-left', 'Swipe in from the left edge', 'launcher')]),
]
DEFAULTS = dict((g, a) for _t, rows in GESTURES for g, _l, a in rows)
# two-finger swipes and turns are also ordinary scrolling and pinching: act only where they mean back/forward/rotate
ONLY_IN = {
    'swipe2-left': 'browser', 'swipe2-right': 'browser', 'rotate2-cw': 'images', 'rotate2-ccw': 'images'}
APP_KINDS = {
    'browser': ('firefox', 'chrom', 'brave', 'vivaldi', 'opera', 'microsoft-edge', 'epiphany', 'librewolf',
                'nautilus', 'nemo', 'caja', 'thunar', 'dolphin', 'pcmanfm'),
    'images': ('eog', 'loupe', 'gthumb', 'shotwell', 'gwenview', 'ristretto', 'viewnior', 'nomacs', 'qimgv', 'feh'),
}


# ---------------------------------------------------------------- input from the touchpad

def find_touchpad():
    """/dev/input/eventN of the first touchpad, as udev tags it, or None."""
    for dev in sorted(glob.glob('/sys/class/input/event*/dev')):
        try:
            with open(dev) as f:
                major, minor = f.read().strip().split(':')
            with open('/run/udev/data/c%s:%s' % (major, minor)) as f:
                if 'E:ID_INPUT_TOUCHPAD=1' in f.read().split('\n'):
                    return '/dev/input/' + dev.split('/')[-2]
        except (OSError, ValueError):
            continue
    return None


def absinfo(fd, code):
    """(min, max, resolution in units per mm) of a touchpad axis."""
    req = (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + code)  # EVIOCGABS(code)
    _v, lo, hi, _fuzz, _flat, res = struct.unpack('6i', fcntl.ioctl(fd, req, bytes(24)))
    return lo, hi, res or max(1, (hi - lo) // 100)  # no resolution reported: call the pad 100 mm wide


class Touchpad(object):
    """Reads one touchpad and hands every complete frame to on_frame(time, [(x_mm, y_mm)], fingers)."""

    def __init__(self, path, on_frame, on_lost):
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            self.x0, x1, self.xres = absinfo(self.fd, ABS_MT_POSITION_X)
            self.y0, self.yres = absinfo(self.fd, ABS_MT_POSITION_Y)[::2]
        except OSError:
            os.close(self.fd)
            raise
        self.width_mm = (x1 - self.x0) / float(self.xres)
        self.on_frame, self.on_lost = on_frame, on_lost
        self.slot, self.slots, self.tool = 0, {}, 0
        self.watch = GLib.io_add_watch(self.fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                                       self._readable)

    def close(self):
        if self.watch:
            GLib.source_remove(self.watch)
            self.watch = 0
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _readable(self, _fd, cond):
        try:
            data = os.read(self.fd, EVENT.size * 64)
        except BlockingIOError:
            return True
        except OSError:  # unplugged, or gone during suspend
            data = b''
        if cond & (GLib.IO_HUP | GLib.IO_ERR) or not data:
            self.watch = 0
            self.close()
            self.on_lost()
            return False
        for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
            sec, usec, typ, code, value = EVENT.unpack_from(data, i)
            self._event(sec + usec / 1e6, typ, code, value)
        return True

    def _event(self, t, typ, code, value):
        if typ == EV_ABS:
            if code == ABS_MT_SLOT:
                self.slot = value
            elif code == ABS_MT_TRACKING_ID:
                if value < 0:
                    self.slots.pop(self.slot, None)
                else:
                    self.slots[self.slot] = [0.0, 0.0]
            elif code in (ABS_MT_POSITION_X, ABS_MT_POSITION_Y) and self.slot in self.slots:
                if code == ABS_MT_POSITION_X:
                    self.slots[self.slot][0] = (value - self.x0) / float(self.xres)
                else:
                    self.slots[self.slot][1] = (value - self.y0) / float(self.yres)
        elif typ == EV_KEY and code in BTN_TOOLS:
            if value:
                self.tool = BTN_TOOLS[code]
            elif self.tool == BTN_TOOLS[code]:
                self.tool = 0
        elif typ == EV_SYN and code == SYN_REPORT:
            self.on_frame(t, [tuple(self.slots[s]) for s in sorted(self.slots)], self.tool)


# ---------------------------------------------------------------- output: keys, clicks, pointer

MOD_KEYSYMS = ((1 << 0, 0xffe1), (1 << 2, 0xffe3), (1 << 3, 0xffe9), (1 << 26, 0xffeb), (1 << 6, 0xffeb))
# Gdk SHIFT, CONTROL, MOD1 (Alt), SUPER and MOD4 masks -> Shift_L, Control_L, Alt_L, Super_L


class XTest(object):
    """Fake key presses, clicks and pointer motion on the X server, as xdotool does."""

    def __init__(self):
        x11, self.xt = ctypes.CDLL('libX11.so.6'), ctypes.CDLL('libXtst.so.6')
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        x11.XFlush.argtypes = [ctypes.c_void_p]
        for name in ('XTestFakeKeyEvent', 'XTestFakeButtonEvent'):
            getattr(self.xt, name).argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.xt.XTestFakeRelativeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.x11 = x11
        self.d = x11.XOpenDisplay(None)
        if not self.d:
            raise OSError('cannot open the X display')

    def accel(self, accel):
        """Press and release a GTK accelerator such as '<Super>Page_Down'. False if it has no key here."""
        kv, mods = Gtk.accelerator_parse(accel)
        code = kv and self.x11.XKeysymToKeycode(self.d, kv)
        if not code:
            return False
        held = []
        for mask, sym in MOD_KEYSYMS:
            mc = int(mods) & mask and self.x11.XKeysymToKeycode(self.d, sym)
            if mc and mc not in held:
                held.append(mc)
        for k in held + [code]:
            self.xt.XTestFakeKeyEvent(self.d, k, True, 0)
        for k in [code] + held[::-1]:
            self.xt.XTestFakeKeyEvent(self.d, k, False, 0)
        self.x11.XFlush(self.d)
        return True

    def button(self, n, down):
        self.xt.XTestFakeButtonEvent(self.d, n, bool(down), 0)
        self.x11.XFlush(self.d)

    def move(self, dx, dy):
        self.xt.XTestFakeRelativeMotionEvent(self.d, dx, dy, 0)
        self.x11.XFlush(self.d)


def supported():
    """Needs X11 (to send keys) and wmctrl/xprop (for windows). Wayland desktops have their own gestures."""
    if not alwaysontop.supported():
        return False
    try:
        ctypes.CDLL('libXtst.so.6')
    except OSError:
        return False
    return True


def bound_accel(schema, key, fallback):
    """The first usable shortcut the desktop has for an action, else the usual one."""
    s = core.gsettings(schema)
    found = list(s.get_strv(key)) if s and key in s.list_keys() else []
    for a in found + [fallback]:
        if Gtk.accelerator_parse(a)[0]:
            return a
    return fallback


def overview_active(value=None):
    """Read, or set, whether the GNOME overview is open. None when the shell cannot be asked."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if value is None:
            res = bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties', 'Get',
                                GLib.Variant('(ss)', ('org.gnome.Shell', 'OverviewActive')), None, 0, 500, None)
            return bool(res.unpack()[0])
        bus.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties', 'Set',
                      GLib.Variant('(ssv)', ('org.gnome.Shell', 'OverviewActive', GLib.Variant('b', value))),
                      None, 0, 500, None)
        return value
    except GLib.Error:
        return None


def active_class():
    """WM_CLASS of the focused window, lower case ('' if unknown)."""
    wid = alwaysontop.active_window()
    return core.run(['xprop', '-id', wid, 'WM_CLASS'], timeout=2)[1].lower() if wid else ''


def tile(side):
    wid = alwaysontop.active_window()
    if not wid:
        return False
    x, y, w, h = fancyzones.workarea(wid)
    half = w // 2
    return fancyzones.place(wid, (x, y, half, h) if side == 'left' else (x + half, y, w - half, h))


def app_windows():
    """(app name, [(id, title)]) of every window of the focused app, on any workspace."""
    active = alwaysontop.active_window()
    classes = {}
    for line in core.run(['wmctrl', '-lx'], timeout=3)[1].splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3:
            try:
                classes[alwaysontop.norm(parts[0])] = parts[2]
            except ValueError:
                continue
    cls = classes.get(active)
    if not cls:
        return '', []
    wins = [(w, t) for w, t, _p in alwaysontop.list_windows() if classes.get(w) == cls]
    return cls.split('.')[-1], wins


class ExposeWindow(Gtk.Window):
    """App Exposé: the focused app's windows. Click one (or arrows and Enter) to go to it; Esc closes."""

    def __init__(self, app, name, windows):
        Gtk.Window.__init__(self, title='App Exposé')
        if isinstance(app, Gtk.Application):
            self.set_application(app)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_default_size(520, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(16)
        box.get_style_context().add_class('pt-card')
        box.pack_start(core.label('%s: %d window%s' % (name or 'This app', len(windows), '' if len(windows) == 1
                                                         else 's'), 'pt-title'), False, False, 0)
        for wid, title in windows:
            b = core.button(title or '(untitled)', lambda w=wid: self.pick(w))
            b.get_child().set_xalign(0)
            b.get_child().set_ellipsize(3)  # Pango END
            box.pack_start(b, False, False, 0)
        box.pack_start(core.label('Esc closes', 'pt-dim'), False, False, 0)
        self.add(box)
        self.connect('key-press-event', lambda _w, ev: ev.keyval == Gdk.KEY_Escape and (self.destroy() or True))
        self._had_focus = False
        self.connect('focus-in-event', lambda *_: setattr(self, '_had_focus', True))
        self.connect('focus-out-event', lambda *_: self._had_focus and GLib.timeout_add(150, self._gone))
        core.present_focused(self)

    def _gone(self):
        if not self.is_active():
            self.destroy()
        return False

    def pick(self, wid):
        self.destroy()
        core.run(['wmctrl', '-i', '-a', wid], timeout=3)


def show_desktop():
    on = '= 1' in core.run(['xprop', '-root', '_NET_SHOWING_DESKTOP'], timeout=2)[1]
    core.run(['wmctrl', '-k', 'off' if on else 'on'], timeout=2)


class Gestures(object):
    """Watches the touchpad in the background and runs the action set for each gesture."""

    def __init__(self, app):
        self.app = app
        self.pad = None
        self.xtest = None
        self.rec = None
        self.retry = 0
        self.held = False
        self.state = 'off'  # off, on, no-touchpad, no-access, unsupported
        self.listeners = []
        self.last = ''
        self._rest = [0.0, 0.0]

    @property
    def enabled(self):
        return self.state not in ('off', 'unsupported')

    def apply(self):
        """Follow the setting (on until the user turns it off). Returns an error text, if any."""
        want = self.app.settings.get('gestures_on', True)
        self._stop()
        if want and not supported():
            self.state = 'unsupported'
        elif want:
            self.state = 'no-touchpad'
            self._start()
        else:
            self.state = 'off'
        self._hold(self.enabled)
        self._changed()
        try:
            fancyzones.set_autostart(self.enabled, AUTOSTART, 'Touchpad Gestures')
        except OSError as e:
            return str(e)

    def _hold(self, on):
        if on and not self.held:
            self.app.hold()  # keep watching in the background, even with no window open
        elif not on and self.held:
            self.app.release()
        self.held = on

    def _start(self):
        path = find_touchpad()
        if path:
            try:
                self.xtest = self.xtest or XTest()
                self.pad = Touchpad(path, self._frame, self._lost)
                self.rec = logic.GestureRecognizer(self.pad.width_mm, self.app.settings.get('gesture_drag3', False))
                self.state = 'on'
            except OSError as e:
                self.state = 'no-access' if e.errno in (errno.EACCES, errno.EPERM) else 'no-touchpad'
        if self.state != 'on' and not self.retry:  # try again: access just set up, or the touchpad came back
            self.retry = GLib.timeout_add_seconds(RETRY_SECS, self._again)
        return self.state == 'on'

    def _again(self):
        self.retry = 0
        if self.enabled and self.pad is None:
            self._start()
            self._changed()
        return False

    def _stop(self):
        if self.pad:
            self.pad.close()
            self.pad = None
        if self.retry:
            GLib.source_remove(self.retry)
            self.retry = 0

    def _lost(self):
        self.pad = None
        if self.enabled:
            self.state = 'no-touchpad'
            self._start()
            self._changed()

    def set_drag3(self, on):
        self.app.settings.set('gesture_drag3', on)
        if self.rec:
            self.rec.drag3 = on

    def _frame(self, t, pts, fingers):
        for ev in self.rec.feed(t, pts, fingers):
            try:
                self.handle(ev)
            except Exception as e:  # noqa: BLE001 - one failed action must not stop the gestures
                print('Powerful Tools gestures: %s failed: %s' % (ev, e))

    def handle(self, ev):
        if isinstance(ev, tuple):  # three-finger drag: move the pointer with the button held
            k = self.app.settings.get('gesture_drag_speed', 5.0)
            self._rest = [self._rest[0] + ev[1] * k, self._rest[1] + ev[2] * k]
            mx, my = int(self._rest[0]), int(self._rest[1])
            if mx or my:
                self._rest = [self._rest[0] - mx, self._rest[1] - my]
                self.xtest.move(mx, my)
            return
        if ev in ('drag-begin', 'drag-end'):
            self._rest = [0.0, 0.0]
            self.xtest.button(1, ev == 'drag-begin')
            return
        if self.rec.drag3 and ev.startswith('swipe4-'):
            ev = 'swipe3-' + ev[len('swipe4-'):]  # as on a Mac: with three-finger drag, swipes take four fingers
        kind = ONLY_IN.get(ev)
        if kind and not any(n in active_class() for n in APP_KINDS[kind]):
            return
        self.last = ev
        self.run(self.action_for(ev))

    def action_for(self, gesture):
        m = self.app.settings.get('gesture_map', {})
        a = m.get(gesture) if isinstance(m.get(gesture), str) else None
        return a if a is not None else DEFAULTS.get(gesture, 'none')

    def set_action(self, gesture, action):
        m = dict(self.app.settings.get('gesture_map', {}))
        m[gesture] = action
        self.app.settings.set('gesture_map', m)

    def run(self, action):
        x = self.xtest
        if action == 'none':
            return
        if action.startswith('keys:'):
            x.accel(action[5:])
        elif action.startswith('cmd:'):
            core.spawn(['/bin/sh', '-c', action[4:]])
        elif action == 'overview':
            if overview_active(not overview_active()) is None:
                x.accel('Super_L')
        elif action == 'app-windows':
            if overview_active():  # as on a Mac, swiping down leaves the overview
                overview_active(False)
            else:
                name, wins = app_windows()
                if wins:
                    ExposeWindow(self.app, name, wins)
        elif action in BOUND:
            x.accel(bound_accel(*BOUND[action]))
        elif action in KEYS:
            x.accel(KEYS[action])
        elif action == 'show-desktop':
            if overview_active():  # leave the overview first, as swiping down does on a Mac
                overview_active(False)
            show_desktop()
        elif action in ('tile-left', 'tile-right'):
            tile(action[5:])
        elif action == 'launcher':
            from . import launcher
            launcher.LauncherWindow(self.app).present_run()
        elif action == 'middle-click':
            x.button(2, True)
            x.button(2, False)

    def _changed(self):
        for cb in list(self.listeners):
            cb()


def setup_access():
    """Install the udev rule that lets the logged-in user read the touchpad. Asks for the admin password."""
    pkexec, sh, udevadm = core.system_bin('pkexec'), core.system_bin('sh'), core.system_bin('udevadm')
    if not (pkexec and sh and udevadm):
        return 'pkexec and udevadm are required'
    script = ('printf "%s" "$1" > "$2" && chmod 644 "$2" && "$3" control --reload-rules && '
              '"$3" trigger --subsystem-match=input --action=change && "$3" settle --timeout=5')
    rc, _o, err = core.run([pkexec, sh, '-c', script, 'sh', RULE_TEXT, UDEV_RULE, udevadm], timeout=300)
    return None if rc == 0 else (err.strip() or 'cancelled')


# ---------------------------------------------------------------- page

TOUCHPAD = 'org.gnome.desktop.peripherals.touchpad'
STATUS = {
    'on': 'On. Gestures work everywhere, also with this window closed.',
    'off': 'Off.',
    'no-touchpad': 'No touchpad found. Gestures start as soon as one is connected.',
    'no-access': 'One-time setup needed: Powerful Tools is not yet allowed to read the touchpad.',
    'unsupported': 'Needs an X11 session with wmctrl and xprop installed (sudo apt install wmctrl x11-utils). '
                   'On Wayland, GNOME and KDE have three- and four-finger gestures built in.',
}


class GesturesPage(core.Page):
    ID = 'gestures'
    TITLE = 'Touchpad Gestures'
    ICON = 'input-touchpad-symbolic'
    DESC = ('Mac-style touchpad gestures: three fingers up for all windows, sideways for workspaces, '
            'pinch for all apps, three-finger drag, and more. Choose what each gesture does.')

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.ctl = app.gestures
        self.status = core.label('', 'pt-heading')
        self.setup = core.button('Allow touchpad access…', self._setup, 'dialog-password-symbolic', suggested=True)
        self.setup.set_no_show_all(True)
        self.switch = Gtk.Switch(active=app.settings.get('gestures_on', True))
        self.switch.connect('notify::active', self._toggle)
        self.add_widget(core.card(
            self.status, core.row('Use touchpad gestures', 'While this is on, Powerful Tools keeps running in the '
                                  'background and starts when you log in.', self.switch),
            core.label('The setup lets your user account read the touchpad only, never the keyboard. It is done '
                       'automatically when Powerful Tools is installed from its package.', 'pt-dim'),
            core.button_row(self.setup), title='Status'))

        drag = Gtk.Switch(active=app.settings.get('gesture_drag3', False))
        drag.connect('notify::active', lambda sw, _p: self.ctl.set_drag3(sw.get_active()))
        speed = core.spin(1, 20, app.settings.get('gesture_drag_speed', 5.0), 0.5, digits=1,
                          on_change=lambda v: app.settings.set('gesture_drag_speed', v))
        self.add_widget(core.card(
            core.row('Three-finger drag', 'Move windows and select text with three fingers, without pressing. '
                     'As on a Mac, the three-finger swipes then use four fingers.', drag),
            core.row('Drag speed', 'Pointer pixels per millimetre of finger travel.', speed), title='Dragging'))

        self.combos = {}
        for group, rows in GESTURES:
            box = []
            for g, text, _d in rows:
                c = self._combo(g)
                self.combos[g] = c
                box.append(core.row(text, None, c))
            self.add_widget(core.card(*box, title=group))
        self.add_widget(core.card(core.label(
            'Taps: one finger clicks, two fingers right-click, three fingers middle-click (paste, open a link in a '
            'new tab).', 'pt-dim')))
        self._touchpad_card()
        self.ctl.listeners.append(self._refresh)
        self.connect('destroy', lambda *_: self.ctl.listeners.remove(self._refresh))
        self._refresh()

    def _combo(self, gesture):
        current = self.ctl.action_for(gesture)
        options = list(ACTIONS) + [('keys:', 'Press a key combination…'), ('cmd:', 'Run a command…')]
        if current.startswith(('keys:', 'cmd:')):
            what = core.accel_label(current[5:]) if current.startswith('keys:') else current[4:]
            options.insert(0, (current, 'Custom: ' + what))
        c = core.combo(options, current)
        c.connect('changed', lambda w: self._chosen(gesture, w))
        return c

    def _chosen(self, gesture, combo):
        a = combo.get_active_id()
        if a == 'keys:':
            accel = core.ShortcutCapture(self.window).get()
            a = 'keys:' + accel if accel else None
        elif a == 'cmd:':
            cmd = self._ask_command()
            a = 'cmd:' + cmd if cmd else None
        if a is None:  # cancelled: show the action that is still set
            self._replace(gesture)
            return
        self.ctl.set_action(gesture, a)
        if a.startswith(('keys:', 'cmd:')):
            self._replace(gesture)

    def _replace(self, gesture):
        """Rebuild one gesture's list so a custom choice shows its keys or command."""
        old = self.combos[gesture]
        parent = old.get_parent()
        new = self._combo(gesture)
        new.set_valign(Gtk.Align.CENTER)
        parent.remove(old)
        parent.pack_end(new, False, False, 0)
        new.show()
        self.combos[gesture] = new

    def _ask_command(self):
        dlg = Gtk.Dialog(title='Run a command', transient_for=self.window, modal=True)
        dlg.add_buttons('_Cancel', Gtk.ResponseType.CANCEL, '_Save', Gtk.ResponseType.OK)
        entry = Gtk.Entry(activates_default=True, width_chars=40, placeholder_text='e.g. gnome-screenshot -i')
        dlg.set_default_response(Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        box.add(core.label('The command runs through the shell, as your user.'))
        box.add(entry)
        dlg.show_all()
        ok = dlg.run() == Gtk.ResponseType.OK
        text = entry.get_text().strip()
        dlg.destroy()
        return text if ok and text else None

    def _touchpad_card(self):
        s = core.gsettings(TOUCHPAD)
        if s is None:
            return
        rows = []
        for key, title, sub in (
                ('tap-to-click', 'Tap to click', 'Tap instead of pressing the touchpad.'),
                ('natural-scroll', 'Natural scrolling', 'Content follows your fingers, as on a Mac.'),
                ('disable-while-typing', 'Ignore the touchpad while typing', 'Stops a palm from moving the pointer.'),
                ('tap-and-drag', 'Tap and drag', 'Tap, then touch again and move to drag.')):
            if key in s.list_keys():
                sw = Gtk.Switch(active=s.get_boolean(key))
                sw.connect('notify::active', lambda w, _p, k=key: s.set_boolean(k, w.get_active()))
                rows.append(core.row(title, sub, sw))
        if 'send-events' in s.list_keys():
            rows.append(core.row('Touchpad', None, core.combo(
                [('enabled', 'Always on'), ('disabled-on-external-mouse', 'Off while a mouse is connected'),
                 ('disabled', 'Off')], s.get_string('send-events'), lambda v: s.set_string('send-events', v))))
        if 'speed' in s.list_keys():
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, -1, 1, 0.05)
            sc.set_value(s.get_double('speed'))
            sc.set_draw_value(False)
            sc.set_size_request(180, -1)
            sc.connect('value-changed', lambda w: s.set_double('speed', w.get_value()))
            rows.append(core.row('Pointer speed', None, sc))
        if rows:
            self.add_widget(core.card(*rows, title='Touchpad settings'))

    def _toggle(self, sw, _p):
        self.app.settings.set('gestures_on', sw.get_active())
        err = self.ctl.apply()
        if err:
            self.toast('Could not change the login setting: %s' % err, error=True)

    def _setup(self):
        err = setup_access()
        if err:
            self.toast('Touchpad access was not set up: %s' % err, error=True)
            return
        self.ctl.apply()
        self.toast('Touchpad gestures are on' if self.ctl.state == 'on' else STATUS[self.ctl.state],
                   error=self.ctl.state != 'on')

    def _refresh(self):
        self.status.set_text(STATUS[self.ctl.state])
        if self.ctl.state == 'no-access':
            self.setup.get_child().show_all()
            self.setup.show()
        else:
            self.setup.hide()
