"""Real-desktop X11 test for Always On Top (needs a running X11 window manager, e.g. GNOME on Xorg).
Run: PT_SRC=src python3 tests/test_alwaysontop_x11.py"""
import os
import sys
import time

sys.path.insert(0, os.environ.get('PT_SRC', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')))
from powerfultools import alwaysontop as T  # noqa: E402
from powerfultools import core  # noqa: E402
from powerfultools.core import Gtk  # noqa: E402

ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)


def pump(t):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.02)


def window(title):
    w = Gtk.Window(title=title)
    w.set_default_size(320, 200)
    w.show_all()
    w.present()
    pump(1.0)
    return w, [x[0] for x in T.list_windows() if x[1] == title][0]


def stacking():
    """Window ids from bottom to top, as the window manager stacks them."""
    out = core.run(['xprop', '-root', '_NET_CLIENT_LIST_STACKING'])[1]
    return [T.norm(x.strip().rstrip(',')) for x in out.split('#')[-1].split(',') if x.strip()]


def above(a, b):
    s = stacking()
    return a in s and b in s and s.index(a) > s.index(b)


class FakeApp(object):
    holds = 0

    def hold(self):
        self.holds += 1

    def release(self):
        self.holds -= 1


app = FakeApp()
keeper = T.PinKeeper(app)
check('supported on this session', T.supported())
wa, a = window('PT-AOT-PINNED')
wb, b = window('PT-AOT-OTHER')
check('windows on every workspace are listed', len(T.list_windows()) >= 2)

check('pin window A', keeper.pin(a, 'A') and T.is_pinned(a))
check('app kept alive while pinned', app.holds == 1)
wb.present()
pump(1.0)
check('after switching to B, A still floats above B', above(a, b))

# what Chrome/Electron do on tab switches: rewrite their state and drop "above"
T.set_pinned(a, False)
T.wait_pinned(a, False)
wb.present()
pump(1.0)
check('dropped pin is restored automatically', T.is_pinned(a))
check('A is back above B', above(a, b))

for i in range(3):
    wb.present()
    pump(0.4)
    wa.present()
    pump(0.4)
check('A stays above B through repeated switching', above(a, b) and T.is_pinned(a))

wb.present()
pump(0.5)
check('shortcut toggle on focused B pins it', keeper.toggle() and T.is_pinned(b) and keeper.is_pinned(b))
check('shortcut toggle again unpins it', keeper.toggle() and not T.is_pinned(b) and not keeper.is_pinned(b))

check('unpin A', keeper.unpin(a) and not T.is_pinned(a))
check('app released when nothing is pinned', app.holds == 0 and not keeper.timer)

keeper.pin(a, 'A')
wa.destroy()
pump(1.0)
check('closed windows are forgotten', not keeper.pinned and app.holds == 0)
wb.destroy()
pump(0.3)
print('ALL OK' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
