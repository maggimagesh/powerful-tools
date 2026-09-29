"""End-to-end GUI test. Run under a virtual display:
    xvfb-run -a -s '-screen 0 3840x2160x24' python3 tests/test_gui.py
Uses an isolated HOME, in-memory gsettings and a temporary hosts file."""
import os
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
    on = app.awake.active and app.awake.held
    app.handle(A.build_parser().parse_args(['--toggle-awake']), [])
    check('CLI --toggle-awake turns Awake on and off', on and not app.awake.active and not app.awake.held)
    app.handle(A.build_parser().parse_args(['--page', 'hosts']), [])
    check('CLI --page', win.current == 'hosts')


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
         t_colorpicker, t_textextractor, t_unlocker, t_keyboard, t_run, t_peek, t_templates, t_misc_pages, t_cli]


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
