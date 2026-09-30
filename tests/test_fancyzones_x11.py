"""Real-desktop X11 test for Fancy Zones (needs a running X11 window manager, e.g. GNOME on Xorg).
It only moves its own windows. Run: PT_SRC=src python3 tests/test_fancyzones_x11.py"""
import os
import sys
import time

sys.path.insert(0, os.environ.get('PT_SRC', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')))
from powerfultools import alwaysontop, fancyzones as T, logic  # noqa: E402
from powerfultools.core import Gdk, Gtk  # noqa: E402

ok = True


def check(name, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)), flush=True)


def pump(t):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.02)


def window(title, headerbar=False):
    w = Gtk.Window(title=title)
    if headerbar:  # draws its own title bar and shadow, like most GNOME apps
        w.set_titlebar(Gtk.HeaderBar(show_close_button=True, title=title))
    w.set_default_size(320, 200)
    w.show_all()
    w.present()
    pump(1.0)
    return w, [x[0] for x in alwaysontop.list_windows() if x[1] == title][0]


def shown(wid):
    """The rectangle a window visibly covers."""
    return T.visible(dict(T.frames())[wid], T.props(wid)[3])


check('supported on this session', T.supported())
wa, a = window('PT-ZONES-MAIN', headerbar=True)
wb, b = window('PT-ZONES-SECOND')
wc, c = window('PT-ZONES-THIRD', headerbar=True)
wa.maximize()
wa.present()
pump(1.0)


def centre(name):
    """Screen position of the middle of one of the main window's title-bar buttons."""
    found = []

    def walk(w):
        if isinstance(w, Gtk.Button) and w.get_style_context().has_class(name):
            found.append(w)
        elif isinstance(w, Gtk.Container):
            w.forall(walk)
    walk(wa.get_titlebar())
    if not found:
        return None
    _ok, ox, oy = wa.get_window().get_origin()
    x, y = found[0].translate_coordinates(wa, found[0].get_allocated_width() // 2, found[0].get_allocated_height() // 2)
    return ox + x, oy + y


if centre('maximize'):
    hit = T.hovered_button(*centre('maximize'))
    check('pointer on the maximize button finds the window', hit and hit[0] == a, hit)
    for other in ('minimize', 'close'):
        if centre(other):
            check('pointer on the %s button does not' % other, T.hovered_button(*centre(other)) is None)
    x, y, w, _h = shown(a)
    check('pointer elsewhere in the window does not', T.hovered_button(x + w // 2, y + 300) is None)

zones = logic.zone_rects(3, *T.workarea(a))
picker = T.arrange(None, a, 3)
pump(1.0)
check('main window leaves maximized and fills the left half', shown(a) == zones[0], (shown(a), zones[0]))
titles = [t for _w, t in picker.windows]
check('picker offers the other windows only', 'PT-ZONES-SECOND' in titles and 'PT-ZONES-MAIN' not in titles, titles)
m = picker.MARGIN
check('picker sits inside the second zone', picker.get_position() == (zones[1][0] + m, zones[1][1] + m),
      (picker.get_position(), zones[1]))
picker.pick(b)
pump(1.0)
check('chosen window fills the second zone', shown(b) == zones[1], (shown(b), zones[1]))
check('picker moves to the third zone and can still be cancelled with Esc',
      picker.get_position() == (zones[2][0] + m, zones[2][1] + m) and picker.is_active(),
      (picker.get_position(), picker.is_active()))
wc.iconify()
pump(0.5)
picker.pick(c)
pump(1.0)
check('minimized window is restored into the third zone', shown(c) == zones[2], (shown(c), zones[2]))
check('picker closes after the last zone', not picker.get_visible())

half = logic.zone_rects(2, *T.workarea(c))
picker = T.arrange(None, c, 2)
pump(1.0)
ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
ev.keyval = Gdk.KEY_Escape
picker._key(picker, ev)
pump(0.5)
check('Esc cancels: only the main window moved', not picker.get_visible() and shown(c) == half[0]
      and shown(b) == zones[1], (shown(c), shown(b)))

# four zones, but only two other windows to put in them
quarters = logic.zone_rects(4, *T.workarea(a))
picker = T.arrange(None, a, 4)
pump(1.0)
picker.pick(b)
pump(1.0)
picker.pick(c)
pump(1.0)
check('four windows: main window top left, the others fill the quarters in order',
      [shown(w) for w in (a, b, c)] == quarters[:3], [shown(w) for w in (a, b, c)])
check('picker closes when no window is left for the last zone', not picker.get_visible())

wa.fullscreen()
pump(1.0)
picker = T.arrange(None, a, 2)
pump(1.0)
check('a fullscreen window leaves fullscreen and fills the left half', shown(a) == half[0], (shown(a), half[0]))
picker.destroy()

wd, d = window('PT-ZONES-GONE')
picker = T.arrange(None, a, 2)
pump(0.5)
wd.destroy()
pump(0.5)
picker.pick(d)
pump(0.5)
T.place(d, (0, 0, 100, 100))
check('choosing a window that has just closed moves nothing and ends the picker', not picker.get_visible()
      and shown(a) == half[0] and T.props(d)[0] is False, (picker.get_visible(), shown(a), T.props(d)[0]))

# a window title is whatever its program says: a line break in one must not upset the window list
we = Gtk.Window(title='PT-ZONES-EVIL\nnot-a-window 0 host fake\n0x00000000 0 host ghost')
we.show_all()
pump(1.0)
try:
    titles = [t for _w, t, _p in alwaysontop.list_windows()]
except ValueError as e:
    titles = e
check('a title with line breaks does not break the window list', isinstance(titles, list) and 'PT-ZONES-EVIL' in titles
      and 'PT-ZONES-SECOND' in titles and 'ghost' not in titles, titles)
we.destroy()

for i in range(30):  # windows of other programs close at any moment, also while the window list is being read
    w = Gtk.Window(title='PT-ZONES-SHORT-LIVED')
    w.show()
    pump(0.05)
    w.destroy()
    T.frames()
    T.hovered_button(10, 10)
check('windows closing while the window list is read do not end the app', True)

spot = centre('maximize')
if spot:
    wb.present()
    T.place(b, (shown(a)[0], shown(a)[1], shown(a)[2], 300))
    pump(1.0)
    hit = T.hovered_button(*spot)
    check('a maximize button hidden behind another window is not hovered', not hit or hit[0] != a, hit)
    wb.iconify()
    pump(1.0)
    hit = T.hovered_button(*spot)
    check('once that window is minimized the button is found again', hit and hit[0] == a, hit)
    wa.iconify()
    pump(1.0)
    check('the button of a minimized window is not hovered', T.hovered_button(*spot) is None)

for win in (wa, wb, wc):
    win.destroy()
pump(0.3)
print('ALL OK' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
