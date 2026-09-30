"""End-to-end GUI test. Run under a virtual display:
    xvfb-run -a -s '-screen 0 3840x2160x24' python3 tests/test_gui.py
Uses an isolated HOME, in-memory gsettings and a temporary hosts file."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import faulthandler
faulthandler.enable()
faulthandler.dump_traceback_later(int(os.environ.get('PT_HANG_SECS', '240')), exit=True)

HOME = tempfile.mkdtemp(prefix='pt-home-')
os.environ['HOME'] = HOME
os.environ['XDG_CONFIG_HOME'] = os.path.join(HOME, '.config')
os.environ['GSETTINGS_BACKEND'] = 'memory'
os.environ.pop('WAYLAND_DISPLAY', None)
os.environ['GDK_BACKEND'] = 'x11'
HOSTS = os.path.join(HOME, 'hosts')
with open(HOSTS, 'w') as f:
    f.write('127.0.0.1\tlocalhost\n# 10.1.1.1 disabled.test\n::1 ip6-localhost\n')
os.environ['PT_HOSTS_FILE'] = HOSTS
SHOTS = os.environ.get('PT_SHOTS', os.path.join(tempfile.gettempdir(), 'pt-shots'))
os.makedirs(SHOTS, exist_ok=True)

sys.path.insert(0, os.environ.get('PT_SRC', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')))
from powerfultools import app as A, core, logic  # noqa: E402
from powerfultools.core import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

ERRORS = []
_orig_hook = sys.excepthook


def hook(t, v, tb):
    ERRORS.append(''.join(traceback.format_exception(t, v, tb)))
    _orig_hook(t, v, tb)


sys.excepthook = hook
MESSAGES = []
core.confirm = lambda *a, **k: True
core.message = lambda parent, text, secondary=None, error=False: MESSAGES.append((text, secondary, error))


def pump(t=0.25):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def wait_for(cond, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        pump(0.05)
        if cond():
            return True
    return False


def shot(win, name):
    pump(0.3)
    gw = win.get_window()
    _ok, x, y = gw.get_origin()
    root = Gdk.get_default_root_window()  # same capture path the app uses; direct CSD window reads crash old cairo
    w = min(gw.get_width(), root.get_width() - x)
    h = min(gw.get_height(), root.get_height() - y)
    pb = Gdk.pixbuf_get_from_window(root, x, y, w, h)
    if pb:
        pb.savev(os.path.join(SHOTS, name + '.png'), 'png', [], [])


class Key(object):
    def __init__(self, keyval, state=0):
        self.keyval, self.state = keyval, state


RESULTS = []


def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond), detail))
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)), flush=True)


def t_icons(app, win):
    theme = Gtk.IconTheme.get_default()
    missing = [c.ICON for c in win.order if not theme.has_icon(c.ICON)]
    check('all sidebar icons exist in the icon theme', not missing, missing)


def t_pages_and_sizes(app, win):
    sizes = [(360, 640), (480, 800), (800, 600), (1024, 600), (1366, 768), (1920, 1080), (2560, 1440), (3840, 2160)]
    too_wide = []
    for w, h in sizes:
        win.resize(w, h)
        pump(0.4)
        win.show_page('dashboard')
        pump(0.1)
        csd = win.get_allocated_width() - w  # client-side decoration border, constant per window
        for cls in win.order:
            win.show_page(cls.ID)
            pump(0.05)
            aw = win.get_allocated_width() - csd
            if aw > w or csd > 60:
                too_wide.append((cls.ID, w, aw, csd))
        win.show_page('dashboard')
        shot(win, 'main-%dx%d' % (w, h))
    check('every page fits every window size (360px → 4K)', not too_wide, too_wide)
    win.resize(360, 640)
    pump(0.4)
    win.show_list()
    pump(0.2)
    ok1 = win.narrow and win.side_scroll.get_visible() and not win.stack.get_visible()
    win.show_page('awake')
    pump(0.2)
    ok2 = win.stack.get_visible() and not win.side_scroll.get_visible() and win.back.get_visible()
    shot(win, 'narrow-awake')
    win.back.clicked()
    pump(0.2)
    ok3 = win.side_scroll.get_visible() and not win.stack.get_visible()
    check('narrow layout: list → page → back', ok1 and ok2 and ok3, (ok1, ok2, ok3))
    win.resize(1280, 800)
    pump(0.4)
    fa, sa = win.footer.get_allocation(), win.stack.get_allocation()
    check('footer note visible, below the content, not overlapping', win.footer.get_mapped()
          and 'Magesh\u00a0Kumar\u00a0A\u00a0T\u00a0\u2764' in win.footer.get_text() and fa.y >= sa.y + sa.height, (fa.y, sa.y, sa.height))
    check('wide layout shows sidebar and page together', not win.narrow and win.side_scroll.get_visible()
          and win.stack.get_visible() and not win.back.get_visible())


def t_bulkrename(app, win):
    d = tempfile.mkdtemp(dir=HOME)
    for n in ('IMG_001.jpg', 'IMG_002.jpg', 'notes.txt'):
        open(os.path.join(d, n), 'w').close()
    p = win.show_page('bulkrename')
    p.add_paths([os.path.join(d, n) for n in sorted(os.listdir(d))])
    p.search.set_text('IMG_')
    p.replace.set_text('Holiday-${n}-')
    p.pad.set_value(2)
    pump()
    rows = [(r[0], r[1]) for r in p.store]
    check('Bulk Rename preview', rows[0] == ('IMG_001.jpg', 'Holiday-01-001.jpg') and rows[2][1] == '', rows)
    p.apply()
    pump()
    names = sorted(os.listdir(d))
    check('Bulk Rename apply', names == ['Holiday-01-001.jpg', 'Holiday-02-002.jpg', 'notes.txt'], names)
    p.undo()
    pump()
    names = sorted(os.listdir(d))
    check('Bulk Rename undo', names == ['IMG_001.jpg', 'IMG_002.jpg', 'notes.txt'], names)
    p.regex.set_active(True)
    p.search.set_text('(')
    pump()
    check('Bulk Rename bad regex disables Apply', not p.apply_btn.get_sensitive())
    p.search.set_text('')
    p.regex.set_active(False)
    p.textcase.set_active_id('upper')
    pump()
    check('Bulk Rename text case', [r[1] for r in p.store][2] == 'NOTES.txt', [r[1] for r in p.store])
    shot(win, 'bulkrename')
    p.clear()


def _make_png(path, w, h, alpha=False):
    pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, alpha, 8, w, h)
    pb.fill(0x3366ccff if not alpha else 0x3366cc80)
    pb.savev(path, 'png', [], [])


def t_imageresizer(app, win):
    d = tempfile.mkdtemp(dir=HOME)
    a, b = os.path.join(d, 'photo.png'), os.path.join(d, 'logo.png')
    _make_png(a, 4000, 3000)
    _make_png(b, 500, 500, alpha=True)
    open(os.path.join(d, 'not-image.txt'), 'w').write('x')
    p = win.show_page('imageresizer')
    p.add_files([d])
    check('Image Resizer ignores non-images', len(p.files) == 2, p.files)
    p.preset.set_active_id('small')
    p.format.set_active_id('keep')
    p.resize()
    ok = wait_for(lambda: p.go.get_sensitive(), 30)
    out = os.path.join(d, 'photo (Small).png')
    info = GdkPixbuf.Pixbuf.get_file_info(out)
    check('Image Resizer fit 4000x3000 → Small', ok and info and (info[1], info[2]) == (640, 480), info)
    p.clear()
    p.add_files([b])
    p.preset.set_active_id('custom')
    p.w.set_value(100)
    p.h.set_value(50)
    p.mode.set_active_id('fill')
    p.format.set_active_id('jpeg')
    p.resize()
    wait_for(lambda: p.go.get_sensitive(), 30)
    info = GdkPixbuf.Pixbuf.get_file_info(os.path.join(d, 'logo (100x50).jpg'))
    check('Image Resizer fill + PNG(alpha) → JPEG', info and (info[0].get_name(), info[1], info[2]) == ('jpeg', 100, 50),
          info)
    p.clear()
    p.mode.set_active_id('fit')
    shot(win, 'imageresizer')


def t_hosts(app, win):
    p = win.show_page('hosts')
    check('Hosts editor loads entries', len(p.store) == 3, len(p.store))
    p._toggled(None, '1')  # enable the disabled entry
    p._edited(None, '0', '999.1.1.1', 1)  # invalid, must be rejected
    check('Hosts editor rejects invalid IP', p.store[0][1] == '127.0.0.1')
    p.add_entry()
    p._edited(None, '3', 'my.dev.local', 2)
    p.save()
    text = open(HOSTS).read()
    check('Hosts editor saves', '10.1.1.1\tdisabled.test' in text and 'my.dev.local' in text
          and not text.startswith('#'), text)
    check('Hosts backup written', os.path.exists(os.path.join(core.CONFIG_DIR, 'hosts.backup')))
    p.filter.set_text('dev')
    pump()
    check('Hosts filter', len(p.fstore) == 1, len(p.fstore))
    p.filter.set_text('')
    shot(win, 'hosts')


def t_envvars(app, win):
    with open(os.path.join(HOME, '.profile'), 'w') as f:
        f.write('# existing\nexport KEEP=1\n')
    p = win.show_page('envvars')
    p.load()
    p.add_var()
    p._edited(None, '0', 'MY_TOOL_HOME', 0)
    p._edited(None, '0', '$HOME/tools "x"', 1)
    p._edited(None, '0', '9BAD', 0)  # rejected
    p.save()
    text = open(os.path.join(HOME, '.profile')).read()
    check('Env vars saved to ~/.profile', 'export KEEP=1' in text and
          logic.env_block_parse(text) == [('MY_TOOL_HOME', '$HOME/tools "x"')], text)
    out = subprocess.check_output(['sh', '-c', '. "$HOME/.profile"; printf %s "$MY_TOOL_HOME"']).decode()
    check('Env var expands in a real shell', out == HOME + '/tools "x"', out)
    shot(win, 'envvars')


def t_advancedpaste(app, win):
    core.copy_text('{"b":1,"a":[1,2]}')
    pump()
    p = win.show_page('advancedpaste')
    pump()
    p.apply('json')
    pump()
    got = core.read_clipboard_text()
    check('Advanced Paste JSON format', got == '{\n  "b": 1,\n  "a": [\n    1,\n    2\n  ]\n}', got)
    p.src.get_buffer().set_text('not json')
    p.apply('json')
    check('Advanced Paste invalid JSON leaves clipboard', core.read_clipboard_text() == got)
    shot(win, 'advancedpaste')


def t_colorpicker(app, win):
    p = win.show_page('colorpicker')
    p.set_color((255, 0, 0))
    check('Color Picker history', app.settings.get('color_history')[0] == '#FF0000')
    win.resize(1280, 800)
    captured = {}
    core.capture_screen(lambda pb, err: captured.update(pb=pb, err=err), [])
    wait_for(lambda: captured, 10)
    check('Screen capture works (X11)', captured.get('pb') is not None, captured.get('err'))
    if captured.get('pb'):
        results = []
        ov = A.colorpicker.PickerOverlay(captured['pb'], results.append)
        ov.present_overlay()
        pump(0.5)
        ov.mx, ov.my = 50, 50
        ov.area.queue_draw()
        ov.on_key(Key(Gdk.KEY_Right))
        pump(0.2)
        shot(ov, 'overlay-colorpicker')
        ov.on_key(Key(Gdk.KEY_Return))
        pump(0.3)
        check('Color Picker overlay picks a pixel', len(results) == 1 and len(results[0]) == 3, results)
        ruler = A.screenruler.RulerOverlay(captured['pb'], lambda r: None)
        ruler.present_overlay()
        pump(0.4)
        ruler.mx, ruler.my = 200, 200
        ms = []
        for k in (Gdk.KEY_1, Gdk.KEY_2, Gdk.KEY_3):
            ruler.on_key(Key(k))
            ms.append(ruler.compute())
            ruler.area.queue_draw()
            pump(0.1)
        ruler.on_key(Key(Gdk.KEY_4))
        ruler.start = (10, 10)
        ruler.mx, ruler.my = ruler.to_widget(109, 59)
        m = ruler.compute()
        shot(ruler, 'overlay-ruler')
        check('Screen Ruler modes', all(x and x[0] for x in ms) and m[0] == '100 × 50', (ms, m))
        ruler.finish(None)
        sel = []
        rs = core.RegionSelectOverlay(captured['pb'], sel.append)
        rs.present_overlay()
        pump(0.3)
        ev = type('E', (), {'button': 1, 'x': 10.0, 'y': 10.0})
        rs.on_press(None, ev)
        ev.x, ev.y = 110.0, 60.0
        rs.on_release(None, ev)
        pump(0.3)
        check('Region selection crops', sel and sel[0].get_width() > 50, sel)
    shot(win, 'colorpicker')


def t_textextractor(app, win):
    p = win.show_page('textextractor')
    if not p.langs:
        check('Text Extractor shows install hint without tesseract', not p.capture_btn.get_sensitive())
        return
    import cairo
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 700, 120)
    cr = cairo.Context(surf)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    cr.set_source_rgb(0, 0, 0)
    cr.select_font_face('Sans')
    cr.set_font_size(48)
    cr.move_to(20, 80)
    cr.show_text('Hello Powerful Tools 2026')
    path = os.path.join(HOME, 'ocr.png')
    surf.write_to_png(path)
    p.recognize(GdkPixbuf.Pixbuf.new_from_file(path))
    wait_for(lambda: p.capture_btn.get_sensitive(), 60)
    b = p.view.get_buffer()
    text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
    check('Text Extractor OCR reads text', 'Powerful' in text and '2026' in text, text)
    check('OCR text copied to clipboard', core.read_clipboard_text() == text)


def t_unlocker(app, win):
    f = os.path.join(HOME, 'busy.txt')
    open(f, 'w').close()
    child = subprocess.Popen([sys.executable, '-c', 'import sys,time; h=open(sys.argv[1]); print(1, flush=True); '
                              'time.sleep(60)', f], stdout=subprocess.PIPE)
    child.stdout.readline()
    p = win.show_page('fileunlocker')
    p.add_paths([f])
    found = [r[0] for r in p.store]
    check('File Unlocker finds the process', child.pid in found, found)
    for i, r in enumerate(p.store):
        if r[0] == child.pid:
            p.tv.get_selection().select_path(Gtk.TreePath(i))
    p.kill()
    child.wait(5)
    wait_for(lambda: child.pid not in [r[0] for r in p.store], 5)
    check('File Unlocker ends the process', child.returncode is not None and
          child.pid not in [r[0] for r in p.store])
    shot(win, 'fileunlocker')
    p.clear()


def t_keyboard(app, win):
    tools = set(c.ID for c in A.PAGES) - {'general'}
    covered = set(a[0] for a in A.keyboard.ACTIONS) | {'launcher', 'screenruler', 'alwaysontop', 'advancedpaste',
                                                        'shortcutguide'}
    check('Every tool has a shortcut', tools <= covered, tools - covered)
    check('Every page shortcut is a valid page', all(a[2].split()[1] in tools for a in A.keyboard.ACTIONS
                                                     if a[2].startswith('--page')))
    kbm = A.keyboard
    kbm.FM_ACCELS = os.path.join(HOME, 'scripts-accels')
    with open(kbm.FM_ACCELS, 'w') as f:
        f.write('; comment\nF4 Other Script\n')
    kbm.set_fm_accel('<Primary><Shift>dollar')
    kbm.set_fm_accel('<Shift><Super>p')
    check('Peek shortcut stored for Files', kbm.get_fm_accel() == '<Shift><Super>p'
          and open(kbm.FM_ACCELS).read() == '; comment\nF4 Other Script\n<Shift><Super>p Powerful Tools Peek\n',
          open(kbm.FM_ACCELS).read())
    kbm.set_fm_accel('')
    check('Peek shortcut removed from Files', kbm.get_fm_accel() == '' and 'Other Script' in open(kbm.FM_ACCELS).read())
    if not core.keybindings_supported():
        p = win.show_page('keyboard')
        check('Keyboard Manager falls back without GNOME schemas', not p.kb_ok)
        return
    path = core.set_custom_keybinding('Powerful Tools: Test', core.ENTRY + ' --run', '<Primary><Alt>space')
    p = win.show_page('keyboard')
    p.refresh()
    kbs = core.list_custom_keybindings()
    check('Custom keybinding registered', any(k['path'] == path and k['binding'] == '<Primary><Alt>space'
                                              for k in kbs), kbs)
    check('Shortcut conflict detected', p._conflict('<Primary><Alt>space'))
    core.remove_custom_keybinding(path)
    check('Custom keybinding removed', not core.list_custom_keybindings())
    if p.remap_checks:
        p.remap_checks['caps:escape'].set_active(True)
        p.remap_checks['ctrl:nocaps'].set_active(True)
        opts = A.keyboard.get_xkb_options()
        check('Key remap options are mutually exclusive', 'ctrl:nocaps' in opts and 'caps:escape' not in opts
              and not p.remap_checks['caps:escape'].get_active(), opts)
        p.remap_checks['ctrl:nocaps'].set_active(False)
        check('Key remap option removed', 'ctrl:nocaps' not in A.keyboard.get_xkb_options())
    shot(win, 'keyboard')


def t_fancyzones(app, win):
    fz = A.fancyzones
    p = win.show_page('fancyzones')
    shot(win, 'fancyzones')
    if not fz.supported():
        return
    check('Fancy Zones ignores a pointer that is on no maximize button', fz.hovered_button(5, 5) is None)
    auto = open(fz.AUTOSTART).read() if os.path.exists(fz.AUTOSTART) else ''
    check('Fancy Zones hover is on from the start, in the background and at login', app.zones.enabled
          and p.switch.get_active() and '--background' in auto, auto)
    p.switch.set_active(False)
    check('Fancy Zones hover turns off', not app.zones.enabled and not os.path.exists(fz.AUTOSTART)
          and app.settings.get('zones_hover') is False)
    p.switch.set_active(True)
    check('Fancy Zones hover turns on again', app.zones.enabled and os.path.exists(fz.AUTOSTART))
    x, y = fz.pointer()
    app.zones.show('0x00000000', (x - 20, y - 20, 40, 44))  # a button under the pointer keeps the view open
    pop = app.zones.popup
    pump(0.6)
    check('Fancy Zones view offers 2, 3 and 4 windows below the button', len(pop.get_child().get_children()) == 3
          and pop.get_position()[1] == y + 24, pop.get_position())
    shot(pop, 'fancyzones-view')
    pop.anchor = (x + 500, y + 500, 1, 1)
    check('Fancy Zones view closes when the pointer is elsewhere', wait_for(lambda: app.zones.popup is None, 3))
    real = fz.pointer, fz.hovered_button
    fz.pointer, fz.hovered_button = (lambda: (50, 50)), (lambda x, y: ('0x00000000', (30, 30, 40, 44)))
    try:
        check('Fancy Zones view opens when the pointer rests on a maximize button',
              wait_for(lambda: app.zones.popup is not None, 3) and app.zones.popup.get_position()[1] == 74)
        app.zones.popup.destroy()
    finally:
        fz.pointer, fz.hovered_button = real
    zones = logic.zone_rects(3, 0, 0, 1600, 900)[1:]
    pk = fz.ZonePicker(app, zones, [('0x00000001', 'First window'), ('0x00000002', 'Second ' + 'long title ' * 40)])
    pump(0.3)
    check('Fancy Zones picker lists the windows inside the free zone', len(pk.list.get_children()) == 2
          and pk.get_size() == (752, 402), pk.get_size())
    shot(pk, 'fancyzones-picker')
    pk.pick('0x00000001')  # no such window: nothing moves, the picker goes on to the last zone
    pump(0.3)
    check('Fancy Zones picker moves on to the next zone', len(pk.list.get_children()) == 1 and len(pk.zones) == 1)
    pk._key(pk, Key(Gdk.KEY_Escape))
    check('Fancy Zones picker closes on Esc', not pk.get_visible())


def t_run(app, win):
    r = A.launcher.search('2+2*10', [], 'https://x.test/?q=')
    check('Run: calculator', r and r[0].title == '= 22' and r[0].action == ('copy', '22'), [x.title for x in r])
    r = A.launcher.search('/us', [], 'https://x.test/?q=')
    check('Run: path completion', any(x.action == ('path', '/usr') for x in r), [x.title for x in r])
    r = A.launcher.search('?? linux tips', [], 'https://x.test/?q=')
    check('Run: web search', r[0].action == ('uri', 'https://x.test/?q=linux+tips'))
    r = A.launcher.search('> echo hi', [], 'https://x.test/?q=')
    check('Run: shell command', r[0].action == ('shell', 'echo hi'))
    rw = A.launcher.LauncherWindow(app)
    rw.present_run()
    rw.entry.set_text('9*9')
    pump(0.3)
    check('Run window lists results', len(rw.list.get_children()) >= 2 and rw.results[0].title == '= 81')
    shot(rw, 'run')
    rw._key(None, Key(Gdk.KEY_Down))
    rw.activate(rw.list.get_row_at_index(0))
    pump()
    check('Run: Enter copies calculation', core.read_clipboard_text() == '81')
    check('Run window closes after activation', not rw.get_visible())


def t_peek(app, win):
    img = os.path.join(HOME, 'peek.png')
    _make_png(img, 64, 48)
    txt = os.path.join(HOME, 'peek.py')
    open(txt, 'w').write('print("hi")\n')
    binf = os.path.join(HOME, 'blob.bin')
    open(binf, 'wb').write(b'\0\1\2' * 100)
    pw = A.peek.PeekWindow(app, [img, txt, HOME, binf])
    pw.show_all()
    kinds = []
    for _ in range(4):
        pump(0.1)
        kinds.append(type(pw.body.get_children()[0]).__name__)
        shot(pw, 'peek-%d' % len(kinds))
        pw.go(1)
    check('Peek previews image/text/folder/other', kinds == ['ImageView', 'ScrolledWindow', 'ScrolledWindow', 'Box'],
          kinds)
    pw.destroy()


def t_templates(app, win):
    p = win.show_page('templates')
    p.add_quick('Shell script.sh', '#!/bin/sh\n')
    d = A.templates.templates_dir() or os.path.join(HOME, 'Templates')
    check('File Templates creates template', os.path.exists(os.path.join(d, 'Shell script.sh')), d)
    check('File Templates script template is executable', os.stat(os.path.join(d, 'Shell script.sh')).st_mode & 0o111)
    p.add_quick('Shell script.sh', '')
    check('File Templates never overwrites', os.path.exists(os.path.join(d, 'Shell script (2).sh')))
    shot(win, 'templates')


def t_misc_pages(app, win):
    p = win.show_page('shortcutguide')
    pump()
    check('Shortcut Guide shows shortcuts', len(p.box.get_children()) > 0)
    p.search.set_text('zzzzqqq')
    pump()
    check('Shortcut Guide search', len(p.box.get_children()) == 1)
    a = win.show_page('awake')
    a.r_inf.set_active(True)
    pump()
    consistent = (app.awake.active and not a.r_off.get_active()) or (not app.awake.active and a.r_off.get_active())
    check('Awake state stays consistent', consistent, app.awake.active)
    a.r_off.set_active(True)
    pump()
    check('Awake turns off', not app.awake.active)
    g = win.show_page('general')
    os.makedirs(os.path.join(HOME, '.local', 'share', 'nautilus'), exist_ok=True)
    g._fm_install()
    s = os.path.join(HOME, '.local/share/nautilus/scripts/Powerful Tools Bulk Rename')
    check('File manager scripts installed', os.path.exists(s) and os.stat(s).st_mode & 0o111 and '--rename' in open(s).read())
    g._fm_remove()
    check('File manager scripts removed', not os.path.exists(s))
    win.show_page('alwaysontop')
    shot(win, 'alwaysontop')


def t_cli(app, win):
    ns = A.build_parser().parse_args(['--rename', '/tmp'])
    app.handle(ns, ['/tmp'])
    pump()
    check('CLI --rename opens Bulk Rename with files', win.current == 'bulkrename'
          and '/tmp' in win.pages['bulkrename'].paths)
    win.pages['bulkrename'].clear()
    app.handle(A.build_parser().parse_args(['--toggle-awake']), [])
    first = (app.awake.active, app.awake.held)  # containers have no session manager or logind: stays off
    if first[0]:
        app.handle(A.build_parser().parse_args(['--toggle-awake']), [])  # already off if the first one failed
    check('CLI --toggle-awake turns Awake on and off', first[0] == first[1] and not app.awake.active
          and not app.awake.held, first)
    app.handle(A.build_parser().parse_args(['--page', 'hosts']), [])
    check('CLI --page', win.current == 'hosts')


def said(win, text):
    """The toast currently shown contains text."""
    return text in win.toast_label.get_text()


def t_edges_files(app, win):
    d = tempfile.mkdtemp(dir=HOME)
    a, b, c, missing = [os.path.join(d, n) for n in ('a.txt', 'b.txt', 'c.txt', 'missing.txt')]
    for f in (a, b, c):
        open(f, 'w').close()
    p = win.show_page('bulkrename')
    p.textcase.set_active_id('none')
    p.add_paths([a, a, missing, b, c])
    check('Bulk Rename ignores missing files and files added twice', p.paths == [a, b, c], p.paths)
    p.search.set_text('a')
    p.replace.set_text('x/y')
    pump()
    check('Bulk Rename refuses a name that would leave the folder', [r[2] for r in p.store] == ['Invalid name', '', '']
          and not p.apply_btn.get_sensitive(), [r[2] for r in p.store])
    p.regex.set_active(True)
    p.search.set_text('^[ab]$')
    p.replace.set_text('z')
    pump()
    check('Bulk Rename refuses two files getting the same name', [r[2] for r in p.store] ==
          ['Duplicate name', 'Duplicate name', ''] and not p.apply_btn.get_sensitive(), [r[2] for r in p.store])
    p.search.set_text('^a$')
    p.replace.set_text('c')
    pump()
    check('Bulk Rename refuses a name that is already taken', [r[2] for r in p.store][0] == 'Name already exists')
    p.apply()
    p.undo()  # nothing was renamed, nothing to undo
    check('Bulk Rename with only problems changes nothing', sorted(os.listdir(d)) == ['a.txt', 'b.txt', 'c.txt'])
    p.search.set_text('^(.)$')
    p.replace.set_text(r'\1\1')
    pump()
    os.unlink(b)  # a file disappears between the preview and Apply
    p.apply()
    check('Bulk Rename rolls everything back when a file has gone', sorted(os.listdir(d)) == ['a.txt', 'c.txt']
          and said(win, 'nothing was changed'), (os.listdir(d), win.toast_label.get_text()))
    p.regex.set_active(False)
    p.search.set_text('')
    p.replace.set_text('')
    p.clear()
    check('Bulk Rename with no files has nothing to apply', len(p.store) == 0 and not p.apply_btn.get_sensitive())

    r = win.show_page('imageresizer')
    r.clear()
    fake, empty, pic = os.path.join(d, 'fake.png'), os.path.join(d, 'empty.jpg'), os.path.join(d, 'pic.png')
    open(fake, 'w').write('not an image')
    open(empty, 'w').close()
    r.add_files([fake, empty, missing])
    check('Image Resizer refuses files that are not images', r.files == [] and said(win, 'No new supported images'), r.files)
    r.resize()
    check('Image Resizer with no images asks for some', said(win, 'Add some images first') and r.go.get_sensitive())
    _make_png(pic, 200, 100)
    r.add_files([pic, pic])
    check('Image Resizer adds an image only once', r.files == [pic], r.files)

    def resized(name, **ui):
        for k, v in ui.items():
            w = getattr(r, k)
            (w.set_active_id if isinstance(w, Gtk.ComboBoxText) else w.set_active if isinstance(w, Gtk.Switch)
             else w.set_text if isinstance(w, Gtk.Entry) and not isinstance(w, Gtk.SpinButton) else w.set_value)(v)
        r.resize()
        wait_for(lambda: r.go.get_sensitive(), 30)
        info = GdkPixbuf.Pixbuf.get_file_info(os.path.join(d, name))
        return info and (info[1], info[2])
    check('Image Resizer never enlarges when told to shrink only', resized('pic (Large).png', preset='large', format='keep',
                                                                       shrink=True) == (200, 100))
    check('Image Resizer with only a width keeps the shape, and overwrites when asked',
          resized('pic.png', shrink=False, overwrite=True, preset='custom', w=50, h=0) == (50, 25)
          and not os.path.exists(os.path.join(d, 'pic (50x0).png')))
    check('Image Resizer percent size', resized('pic.png', unit='percent', w=200, h=0) == (100, 50))
    check('Image Resizer keeps a file name pattern with a slash inside the folder',
          resized('.._pic.png', overwrite=False, unit='px', w=10, h=10, pattern='../%1') == (10, 5)
          and not os.path.exists(os.path.join(HOME, 'pic.png')), os.listdir(d))
    os.chmod(d, 0o500)
    r.resize()
    wait_for(lambda: r.go.get_sensitive(), 30)
    os.chmod(d, 0o700)
    check('Image Resizer reports a folder it cannot write to', MESSAGES and MESSAGES[-1][0] == 'Resized 0 of 1 images'
          or os.getuid() == 0, MESSAGES[-1:])
    resized('pic.png', pattern='%1 (%2)', preset='medium', unit='px')
    r.clear()

    u = win.show_page('fileunlocker')
    u.clear()
    u.add_paths([missing])
    u.scan()
    u.kill()  # nothing selected
    check('File Unlocker ignores a file that does not exist', u.targets == [] and not u.scan_btn.get_sensitive()
          and not u.kill_btn.get_sensitive())
    u.add_paths([d, d])
    check('File Unlocker says so when nothing uses a folder', u.targets == [d] and len(u.store) == 0
          and u.info.get_text().startswith('No process is using these items.'), u.info.get_text())
    u.clear()

    pw = A.peek.PeekWindow(app, [missing])
    pw.show_all()
    pump(0.2)
    kind = pw.body.get_children()[0]
    check('Peek explains a file it cannot open', isinstance(kind, Gtk.Label) and 'Cannot open' in kind.get_text())
    check('Peek hides the previous and next buttons for a single file', not pw.prev.get_visible()
          and not pw.next.get_visible() and pw.hb.get_subtitle() is None)
    pw._key(pw, Key(Gdk.KEY_Left))
    check('Peek stays on the only file', pw.i == 0)
    pw._key(pw, Key(Gdk.KEY_Escape))
    pw = A.peek.PeekWindow(app, [empty, fake, d], index=99)
    pw.show_all()
    pump(0.2)
    kinds = [type(pw.body.get_children()[0].get_child()).__name__]  # a folder is a list, text a text view
    for _ in range(3):
        pw._key(pw, Key(Gdk.KEY_Right))
        kinds.append(type(pw.body.get_children()[0].get_child()).__name__)
    check('Peek starts on the last file for an index past the end, wraps round, and shows an empty file and a text '
          'file named .png as text', kinds == ['Viewport', 'TextView', 'TextView', 'Viewport']
          and pw.hb.get_subtitle() == '3 of 3', (kinds, pw.hb.get_subtitle()))
    pw._key(pw, Key(Gdk.KEY_space))
    check('Peek closes on Space', not pw.get_visible())

    t = win.show_page('templates')
    tdir = A.templates.templates_dir() or os.path.join(HOME, 'Templates')
    tpl = os.path.join(tdir, 'Shell script.sh')
    real = core.choose_files
    try:
        core.choose_files = lambda *a, **k: []
        t.create_from(tpl)  # the folder chooser was cancelled
        core.choose_files = lambda *a, **k: [d]
        t.create_from(tpl)
        t.create_from(tpl)
        check('File Templates creates files without replacing one', os.path.exists(os.path.join(d, 'Shell script.sh'))
              and os.path.exists(os.path.join(d, 'Shell script (2).sh')), os.listdir(d))
        t.create_from(os.path.join(tdir, 'gone.txt'))
        check('File Templates reports a template that has gone', said(win, 'Could not create'))
        os.makedirs(os.path.join(d, 'Project', 'src'))
        core.choose_files = lambda *a, **k: [os.path.join(d, 'Project'), missing]
        t.add_from_file()
        check('File Templates takes a folder as a template and reports a missing file',
              os.path.isdir(os.path.join(tdir, 'Project', 'src')) and said(win, 'Could not add missing.txt'))
    finally:
        core.choose_files = real
    n = len(t.list.get_children())
    t.delete(os.path.join(tdir, 'Project'))
    t.delete(tpl)
    check('File Templates deletes templates, folders too', not os.path.exists(tpl) and len(t.list.get_children()) == n - 2
          and not os.path.exists(os.path.join(tdir, 'Project')))


def t_edges_pages(app, win):
    p = win.show_page('hosts')
    p.load()
    before = open(HOSTS).read()
    p._edited(None, '0', 'bad host!', 2)
    check('Hosts editor rejects an invalid host name', p.store[0][2] == 'localhost' and said(win, 'invalid host name'))
    p.save()
    check('Hosts editor has nothing to save when nothing changed', said(win, 'No changes to save'))
    p._edited(None, '0', '', 1)
    p.save()
    check('Hosts editor will not save a row without an address', said(win, 'row(s): 1') and open(HOSTS).read() == before)
    p.load()
    p.remove_entry()  # nothing selected
    p.add_entry()
    last = str(len(p.store) - 1)
    p._edited(None, last, 'fe80::1%eth0', 1)
    p._edited(None, last, 'router.lan printer.lan', 2)
    p._edited(None, last, 'two\nlines', 3)
    p._toggled(None, last)
    p.save()
    check('Hosts editor saves an IPv6 entry with a zone, switched off, its comment on one line',
          open(HOSTS).read() == before + '# fe80::1%eth0\trouter.lan printer.lan\t# two lines\n', open(HOSTS).read())
    p.filter.set_text('no-such-host')
    pump()
    check('Hosts filter can match nothing', len(p.fstore) == 0)
    p.filter.set_text('')
    p.tv.get_selection().select_path(Gtk.TreePath(len(p.store) - 1))
    p.remove_entry()
    p.save()
    check('Hosts editor removes an entry and keeps every other line', open(HOSTS).read() == before, open(HOSTS).read())
    p._toggled(None, '0')
    p.load()
    check('Hosts reload drops changes that were not saved', p.store[0][0] is True)
    real, A.hosts.HOSTS = A.hosts.HOSTS, os.path.join(HOME, 'no-hosts-file')
    p.load()
    A.hosts.HOSTS = real
    check('Hosts editor says when the file cannot be read', len(p.store) == 0 and 'Could not read' in p.status.get_text(),
          p.status.get_text())
    p.load()

    profile = os.path.join(HOME, '.profile')
    e = win.show_page('envvars')
    e.load()
    e.save()
    check('Env vars has nothing to save when nothing changed', said(win, 'No changes to save'))
    e.add_var()
    e.add_var()
    check('Env vars gives new variables different names', [r[0] for r in e.user][1:] == ['NEW_VARIABLE', 'NEW_VARIABLE_2'])
    e._edited(None, '1', 'MY_TOOL_HOME', 0)
    e._edited(None, '1', 'two\nlines', 1)
    before = open(profile).read()
    e.save()
    check('Env vars refuses two variables with the same name and a value of two lines',
          said(win, 'Duplicate names: MY_TOOL_HOME') and e.user[1][1] == '' and open(profile).read() == before)
    e.delete()  # nothing selected
    while len(e.user):
        e.utv.get_selection().select_path(Gtk.TreePath(0))
        e.delete()
    e.save()
    text = open(profile).read()
    check('Env vars removes its block when the last variable goes, and kept the first profile as a backup',
          logic.ENV_BEGIN not in text and text.startswith('# existing\nexport KEEP=1\n')
          and open(profile + '.powerful-tools.bak').read() == '# existing\nexport KEEP=1\n', text)

    a = win.show_page('advancedpaste')
    core.copy_text('unchanged')
    a.src.get_buffer().set_text('')
    a.apply('upper')
    check('Advanced Paste with no text says so', said(win, 'no text') and core.read_clipboard_text() == 'unchanged')
    a.src.get_buffer().set_text('***')
    a.apply('b64dec')
    a.src.get_buffer().set_text('a,"' + 'x' * 200000)
    a.apply('mdtable')
    check('Advanced Paste leaves the clipboard alone when the text cannot be converted',
          core.read_clipboard_text() == 'unchanged' and said(win, 'Not a table'), win.toast_label.get_text())
    a.src.get_buffer().set_text('straße ❤\n' * 20000)
    a.apply('upper')
    check('Advanced Paste handles long non-English text', core.read_clipboard_text() == 'STRASSE ❤\n' * 20000)

    search = A.launcher.search
    url = 'https://x.test/?q='
    check('Run: nothing typed, nothing offered', search('', [], url) == search('   ', [], url) == search('>', [], url)
          == search('??', [], url) == search('/no/such/folder/', [], url) == [])
    r = search('1/0', [], url)
    check('Run: a sum with no answer offers only a web search', len(r) == 1 and r[0].action[0] == 'uri', [x.title for x in r])
    r = search('~', [], url)
    check('Run: ~ is the home folder', r and r[0].action == ('path', HOME), [x.action for x in r])
    r = search('log(8, 2) + 1,000', [], url)
    check('Run: functions with two arguments and thousands separators', r[0].title == '= 1003', r[0].title)
    rw = A.launcher.LauncherWindow(app)
    rw.present_run()
    rw.entry.set_text('')
    pump(0.2)
    rw.activate(None)
    rw._key(None, Key(Gdk.KEY_Down))
    rw._key(None, Key(Gdk.KEY_Tab))
    check('Run window with nothing typed stays open and empty', rw.get_visible() and not rw.list.get_children())
    rw.entry.set_text('/us')
    pump(0.2)
    rw._key(None, Key(Gdk.KEY_Tab))
    check('Run: Tab completes a folder name', rw.entry.get_text() == '/usr/', rw.entry.get_text())
    rw.entry.set_text('7*6')
    pump(0.2)
    rw._key(None, Key(Gdk.KEY_Up))
    check('Run: Up from the first result goes to the last', rw.list.get_selected_row().get_index() == len(rw.results) - 1)
    rw._key(None, Key(Gdk.KEY_Escape))
    check('Run window closes on Esc', not rw.get_visible())

    aw = win.show_page('awake')
    aw.hours.set_value(0)
    aw.mins.set_value(0)
    aw.r_for.set_active(True)
    pump()
    check('Awake refuses a time of zero', not app.awake.active and aw.r_off.get_active() and said(win, 'longer than zero'))
    app.awake.stop()
    app.awake.stop()  # already off
    fmt = A.awake.fmt_secs
    check('Awake shows the time left', (fmt(0), fmt(59), fmt(3661), fmt(360000)) == ('0:00:00', '0:00:59', '1:01:01', '100:00:00'))
    if app.awake.start(1):  # only where the desktop can keep the computer awake
        check('Awake turns itself off when the time is up', wait_for(lambda: not app.awake.active, 5) and not app.awake.held)
    aw.hours.set_value(1)

    kbm = A.keyboard
    check('Shortcut labels: none, unknown and known', (core.accel_label(''), core.accel_label('not-a-key'),
                                                       core.accel_label('<Primary>c')) == ('Not set', 'not-a-key', 'Ctrl+C'))
    check('Files shortcut lines: comments and other scripts are left alone', not kbm._is_script_line('; x ' + kbm.PEEK_SCRIPT,
          kbm.PEEK_SCRIPT) and not kbm._is_script_line('F4 Other', kbm.PEEK_SCRIPT) and not kbm._is_script_line('', kbm.PEEK_SCRIPT))
    kbm.FM_ACCELS = os.path.join(HOME, 'new-folder', 'scripts-accels')
    check('Files shortcut file that does not exist yet', kbm.get_fm_accel() == '')
    kbm.set_fm_accel('F9')
    check('Files shortcut file is created with its folder', open(kbm.FM_ACCELS).read() == 'F9 Powerful Tools Peek\n')
    if core.keybindings_supported():
        k = win.show_page('keyboard')
        k._add_custom()
        check('Keyboard Manager needs a name, a command and a shortcut', said(win, 'Enter a name')
              and not core.list_custom_keybindings())
        k.c_name.set_text('Say hi')
        k.c_cmd.set_text('echo "hi there"')
        k.c_accel = '<Super>F9'
        k._add_custom()
        kbs = core.list_custom_keybindings()
        check('Keyboard Manager adds a custom shortcut and clears the form', len(kbs) == 1 and kbs[0]['command'] ==
              'echo "hi there"' and k.c_name.get_text() == '' and k.c_accel == '', kbs)
        k.c_name.set_text('Again')
        k.c_cmd.set_text('true')
        k.c_accel = '<Super>F9'
        k._add_custom()
        check('Keyboard Manager refuses a shortcut that is taken', len(core.list_custom_keybindings()) == 1
              and said(win, 'already used by "Say hi"'))
        k._remove(kbs[0])
        check('Keyboard Manager removes a custom shortcut', not core.list_custom_keybindings())

    g = win.show_page('general')
    dark = Gtk.Settings.get_default()
    g._theme('dark')
    on = dark.get_property('gtk-application-prefer-dark-theme')
    g._theme('light')
    off = dark.get_property('gtk-application-prefer-dark-theme')
    g._theme('system')
    check('App theme switches between dark and light and is remembered', on and not off
          and app.settings.get('theme') == 'system')
    shutil.rmtree(os.path.join(HOME, '.local', 'share', 'nautilus'))
    g._fm_install()
    g._fm_remove()
    check('File manager integration without a file manager says so and installs nothing',
          not any(os.path.exists(path) for _d, path, _f in A.fm_script_paths()))

    handle = lambda *args: app.handle(A.build_parser().parse_args(list(args)), [])  # noqa: E731
    before = len(Gtk.Window.list_toplevels())
    handle('--peek')
    handle('--background')
    handle('--zones')
    handle('--always-on-top')
    pump()
    check('CLI --peek without files, --background, and --zones / --always-on-top without a focused window open nothing new',
          len([w for w in Gtk.Window.list_toplevels() if w.get_visible()]) <= before and app.zones.popup is None)
    app.handle(A.build_parser().parse_args(['--resize', 'x']), [HOSTS])
    check('CLI --resize with a file that is no image', win.current == 'imageresizer' and said(win, 'No new supported images'))
    handle('--unlocker')
    check('CLI --unlocker without files opens the empty page', win.current == 'fileunlocker'
          and win.pages['fileunlocker'].targets == [])


def t_fancyzones_edges(app, win):
    fz = A.fancyzones
    check('Fancy Zones point-in-rectangle edges', fz.inside((0, 0, 10, 10), 0, 0) and fz.inside((0, 0, 10, 10), 9, 9)
          and not fz.inside((0, 0, 10, 10), 10, 9) and not fz.inside((0, 0, 10, 10), -1, 0) and not fz.inside((5, 5, 0, 0), 5, 5))
    if not fz.supported():
        p = win.show_page('fancyzones')
        check('Fancy Zones explains itself where it cannot move windows', not hasattr(p, 'switch') and not app.zones.enabled)
        return
    real = fz.supported, fz.pointer, fz.hovered_button
    try:
        fz.supported = lambda: False
        page = fz.FancyZonesPage(app)
        app.zones.apply()
        check('Fancy Zones on a desktop where it cannot move windows: help text, no watching, no login entry',
              not hasattr(page, 'switch') and not app.zones.enabled and not os.path.exists(fz.AUTOSTART))
        page.destroy()
        fz.supported = real[0]
        app.zones.apply()
        app.zones.set_enabled(True)
        timer = app.zones.timer
        app.zones.set_enabled(True)
        check('Fancy Zones turned on twice watches only once', app.zones.timer == timer and os.path.exists(fz.AUTOSTART))
        app.zones.set_enabled(False)
        app.zones.set_enabled(False)
        check('Fancy Zones turned off twice is simply off', not app.zones.enabled)
        app.zones.apply()

        moving = iter(range(10 ** 6))
        fz.hovered_button = lambda x, y: ('0x00000000', (x - 20, y - 20, 40, 44))
        fz.pointer = lambda: (next(moving), 50)
        check('Fancy Zones view does not open while the pointer is moving, even across a button',
              not wait_for(lambda: app.zones.popup is not None, 1.2))
        fz.pointer = lambda: (300, 300)
        fz.hovered_button = lambda x, y: None
        check('Fancy Zones view does not open when the pointer rests anywhere else',
              not wait_for(lambda: app.zones.popup is not None, 1.2))
        fz.hovered_button = lambda x, y: ('0x00000000', (280, 280, 40, 44))
        fz.pointer = lambda: (301, 300)
        opened = wait_for(lambda: app.zones.popup is not None, 3)
        first = app.zones.popup
        pump(1.0)
        check('Fancy Zones view opens once and stays while the pointer rests on the button', opened
              and app.zones.popup is first and first.get_visible())
        first.destroy()
        check('Fancy Zones view that was closed does not come back until the pointer moves and rests again',
              not wait_for(lambda: app.zones.popup is not None, 1.2))
        fz.pointer = lambda: (302, 300)
        check('Fancy Zones view opens again after the pointer moved', wait_for(lambda: app.zones.popup is not None, 3))
        second = app.zones.popup
        app.zones.show('0x00000001', (280, 280, 40, 44))
        check('Fancy Zones shows one view at a time', not second.get_visible() and app.zones.popup is not second
              and app.zones.popup.wid == '0x00000001')
        app.zones.popup.choose(3)  # that window does not exist: nothing to arrange, nothing to pick
        pump(0.3)
        check('Fancy Zones layout chosen for a window that has gone closes the view quietly', app.zones.popup is None)
    finally:
        fz.supported, fz.pointer, fz.hovered_button = real
    mon = Gdk.Display.get_default().get_monitor(0).get_geometry()
    for name, anchor in (('right', (mon.width - 10, 100, 40, 44)), ('left', (-30, 100, 40, 44))):
        app.zones.show('0x00000000', anchor)
        pump(0.2)
        x, width = app.zones.popup.get_position()[0], app.zones.popup.get_size()[0]
        check('Fancy Zones view stays on screen at the %s edge' % name, 0 <= x and x + width <= mon.width, (x, width))
        app.zones.popup.destroy()
    check('Fancy Zones shortcut without a focused window does nothing', app.zones.show_for_active() is False
          and app.zones.popup is None)
    check('Fancy Zones finds no window at a point on an empty screen', fz.window_at(5, 5) is None
          and fz.window_at(5, 5, [('0x00000000', (0, 0, 100, 100))]) is None and fz.hovered_button(-50, 99999) is None)
    check('Fancy Zones reads nothing from a window that has gone', fz.props('0x00000000')[0] is False
          and fz.props('0x00000000')[2:] == ((0, 0, 0, 0), (0, 0, 0, 0)) and fz.place('0x00000000', (0, 0, 10, 10)) is False)
    check('Fancy Zones visible frame leaves out the shadow', fz.visible((0, 0, 100, 100), (10, 10, 5, 5)) == (10, 5, 80, 90))
    check('Fancy Zones arranges a window with no others: no picker', fz.arrange(app, '0x00000000', 4) is None)
    for zones, wins in (([], [('0x00000001', 'a')]), ([(0, 0, 400, 300)], [])):
        pk = fz.ZonePicker(app, zones, wins)
        check('Fancy Zones picker with %s closes at once' % ('no zone left' if wins else 'no window left'), not pk.get_visible())
    pk = fz.ZonePicker(app, [(0, 0, 10, 10), (0, 0, 800, 600)], [('0x00000001', ''), ('0x00000002', 'b')])
    pump(0.2)
    check('Fancy Zones picker fits a zone smaller than its margins and names an untitled window',
          pk.get_visible() and pk.list.get_children()[0].get_label() == '(untitled)')
    check('Fancy Zones picker ignores other keys', pk._key(pk, Key(Gdk.KEY_a)) is False and pk.get_visible())
    cancel = pk.get_child().get_children()[2].get_children()[0].get_child()
    cancel.clicked()
    check('Fancy Zones picker closes with its Cancel button', not pk.get_visible())
    settings = Gtk.Settings.get_default()
    layout = settings.get_property('gtk-decoration-layout')
    settings.set_property('gtk-decoration-layout', 'menu:close')
    page = fz.FancyZonesPage(app)
    texts = []
    page.forall(lambda w: texts.extend(_labels(w)))
    check('Fancy Zones on a desktop without maximize buttons points to the shortcut',
          any('does not show a maximize button' in t for t in texts) and fz.hovered_button(100, 100) is None)
    settings.set_property('gtk-decoration-layout', layout)
    page.destroy()
    win.pages['fancyzones'].switch.set_active(False)
    app.zones.apply()
    check('Fancy Zones stays off once turned off', not app.zones.enabled and not os.path.exists(fz.AUTOSTART))
    win.pages['fancyzones'].switch.set_active(True)


def _labels(w):
    out = [w.get_text()] if isinstance(w, Gtk.Label) else []
    if isinstance(w, Gtk.Container):
        w.forall(lambda c: out.extend(_labels(c)))
    return out


def t_bad_settings(app, win):
    """A settings file edited by hand or damaged: every value is the wrong kind."""
    app.settings.data = {
        'theme': 5, 'resize_preset': 'gone', 'resize_w': 'wide', 'resize_h': None, 'resize_unit': 3, 'resize_mode': [],
        'resize_shrink': 'yes', 'resize_overwrite': 2, 'resize_pattern': 9, 'resize_format': 'bmp',
        'resize_quality': float('nan'), 'awake_hours': 'x', 'awake_minutes': [], 'awake_until_h': {}, 'awake_until_m': -5,
        'awake_screen_on': 'on', 'color_history': [1, None, 'zzz', '#00ff00'], 'color_current': [300, 'a'],
        'color_copy_format': 'XYZ', 'ocr_lang': '--help', 'run_engine': ['x'], 'ruler_tolerance': 'soft', 'zones_hover': 'no'}
    for page in list(win.pages.values()):
        win.stack.remove(page)
        page.destroy()
    win.pages.clear()
    failed = []
    for cls in win.order:
        try:
            win.show_page(cls.ID)
            pump(0.05)
        except Exception:
            failed.append((cls.ID, traceback.format_exc().splitlines()[-1]))
    check('every page opens with a damaged settings file', not failed, failed)
    r, c = win.pages.get('imageresizer'), win.pages.get('colorpicker')
    check('damaged settings fall back to usable values', not failed and r.preset.get_active_id() == 'small'
          and r.format.get_active_id() == 'keep' and r.pattern.get_text() == '%1 (%2)' and r.quality.get_value() == 90
          and c.rgb == (0, 120, 215) and len(c.history.get_children()) == 1 and c.copy_fmt.get_active_id() == 'HEX')
    app.apply_theme()
    app.zones.apply()
    rw = A.launcher.LauncherWindow(app)
    check('damaged settings: Quick Launcher and Fancy Zones use their defaults', rw.engine_url == A.launcher.ENGINES[0][2]
          and app.zones.enabled == A.fancyzones.supported())
    rw.destroy()


def setup_legacy():
    """A pre-release install: old settings dir, old shortcut command, old file-manager script."""
    os.makedirs(A.LEGACY_CONFIG)
    with open(os.path.join(A.LEGACY_CONFIG, 'settings.json'), 'w') as f:
        f.write('{"run_engine": "duckduckgo"}')
    if core.keybindings_supported():
        core.set_custom_keybinding('PowerToys: PowerToys Run (launcher)', '/usr/bin/powertoys-linux --run',
                                   '<Primary><Alt>space')
    d = os.path.join(HOME, '.local/share/nautilus/scripts')
    os.makedirs(d)
    with open(os.path.join(d, 'PowerToys PowerRename'), 'w') as f:
        f.write('#!/bin/sh\nexec /usr/bin/powertoys-linux --rename "$@"\n')


def t_migration(app, win):
    check('Upgrade keeps old settings', app.settings.get('run_engine') == 'duckduckgo' and
          not os.path.exists(A.LEGACY_CONFIG))
    if core.keybindings_supported():
        kbs = core.list_custom_keybindings()
        ok = len(kbs) == 1 and kbs[0]['command'] == core.ENTRY + ' --run' and \
            kbs[0]['name'] == 'Powerful Tools: Quick Launcher' and kbs[0]['binding'] == '<Primary><Alt>space'
        check('Upgrade rewrites old keyboard shortcuts', ok, kbs)
        for k in kbs:
            core.remove_custom_keybinding(k['path'])
    d = os.path.join(HOME, '.local/share/nautilus/scripts')
    new = os.path.join(d, 'Powerful Tools Bulk Rename')
    check('Upgrade replaces old file manager scripts', not os.path.exists(os.path.join(d, 'PowerToys PowerRename'))
          and os.path.exists(new) and '--rename' in open(new).read(), os.listdir(d))
    A.remove_fm_scripts()


TESTS = [t_migration, t_icons, t_pages_and_sizes, t_bulkrename, t_imageresizer, t_hosts, t_envvars, t_advancedpaste,
         t_colorpicker, t_textextractor, t_unlocker, t_keyboard, t_fancyzones, t_run, t_peek, t_templates, t_misc_pages, t_cli,
         t_edges_files, t_edges_pages, t_fancyzones_edges, t_bad_settings]


def main():
    setup_legacy()
    app = A.Application()
    state = {'rc': 1}

    def drive():
        try:
            win = app.main_window()
            pump(0.5)
            for t in TESTS:
                try:
                    t(app, win)
                except Exception:
                    ERRORS.append(traceback.format_exc())
                    check(t.__name__, False, traceback.format_exc())
            for e in ERRORS:
                print('UNCAUGHT:', e)
            failed = [r for r in RESULTS if not r[1]]
            print('\n%d checks, %d failed, %d uncaught errors' % (len(RESULTS), len(failed), len(ERRORS)))
            state['rc'] = 0 if not failed and not ERRORS else 1
        finally:
            app.awake.stop(notify=False)
            app.quit()
        return False

    app.connect('startup', lambda *_: GLib.idle_add(drive))
    app.run(['test'])
    return state['rc']


if __name__ == '__main__':
    sys.exit(main())
