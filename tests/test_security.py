"""Attack attempts against the tools: every check passes when the attack is refused. Pure-logic attacks (hosts
lines, calculator, rename, ~/.profile) are in test_logic.py. Run under a virtual display:
    xvfb-run -a python3 tests/test_security.py
Uses an isolated HOME and never asks for a password: anything that would run as administrator is only recorded."""
import json
import os
import re
import signal
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import zlib

HOME = tempfile.mkdtemp(prefix='pt-sec-')
PLANT = os.path.join(HOME, 'bin')  # what a malicious program could leave in the user's PATH
MARK = os.path.join(HOME, 'PLANTED-PROGRAM-RAN')
PNG = os.path.join(HOME, 'small.png')
os.environ.update(HOME=HOME, XDG_CONFIG_HOME=os.path.join(HOME, '.config'), GSETTINGS_BACKEND='memory',
                  GDK_BACKEND='x11', PT_HOSTS_FILE=os.path.join(HOME, 'readonly-hosts'),
                  PATH=PLANT + ':' + os.environ['PATH'], PT_MARK=MARK, PT_PNG=PNG,
                  PT_SHOT_LOG=os.path.join(HOME, 'shot.log'))
os.environ.pop('WAYLAND_DISPLAY', None)
os.makedirs(PLANT)
for name in ('pkexec', 'tee', 'kill'):
    with open(os.path.join(PLANT, name), 'w') as f:
        f.write('#!/bin/sh\ntouch "$PT_MARK"\n')
    os.chmod(os.path.join(PLANT, name), 0o755)
with open(os.path.join(PLANT, 'gnome-screenshot'), 'w') as f:  # a screenshot tool that reports where it is told to save
    f.write('#!/bin/sh\nfor out; do :; done\nstat -c "%a %u" "$(dirname "$out")" > "$PT_SHOT_LOG"\ncp "$PT_PNG" "$out"\n')
os.chmod(os.path.join(PLANT, 'gnome-screenshot'), 0o755)
with open(os.environ['PT_HOSTS_FILE'], 'w') as f:
    f.write('127.0.0.1\tlocalhost\n')
os.chmod(os.environ['PT_HOSTS_FILE'], 0o444)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.environ.get('PT_SRC', os.path.join(HERE, '..', 'src')))
INSTALLED = SRC.startswith('/usr/')
BIN = '/usr/bin/powerful-tools' if INSTALLED else os.path.join(HERE, '..', 'bin', 'powerful-tools')
sys.path.insert(0, SRC)
from powerfultools import app as A, core, logic  # noqa: E402
from powerfultools import fancyzones, fileunlocker, hosts, imageresizer, keyboard, launcher, peek  # noqa: E402
from powerfultools.core import GdkPixbuf, GLib, Gtk  # noqa: E402

SYSTEM_DIRS = ('/usr/sbin', '/usr/bin', '/sbin', '/bin')
RESULTS, TOASTS, CALLS = [], [], []
core.confirm = lambda *a, **k: True
core.message = lambda parent, text, secondary=None, error=False: TOASTS.append(text)
real_run = core.run


def recorder(args, **_kw):
    """Stands in for core.run: nothing is executed, so no password prompt and no change to the system."""
    CALLS.append(list(args))
    return 127, '', ''


def check(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)[:600]), flush=True)


class TooSlow(Exception):  # not TimeoutError: that is an OSError, which file code rightly catches
    pass


def within(secs, fn, *args):
    """fn's result, or the exception it raised: TooSlow if it is still running after secs."""
    def late(*_a):
        raise TooSlow('still running after %d seconds' % secs)
    old = signal.signal(signal.SIGALRM, late)
    signal.alarm(secs)
    try:
        return fn(*args)
    except Exception as e:
        return e
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def write_png(path, w, h):
    """A valid 1-bit PNG of any size: a few kilobytes on disk even when it decodes to gigabytes."""
    comp = zlib.compressobj(9)
    row = b'\0' * (1 + (w + 7) // 8)
    data = b''.join(comp.compress(row) for _ in range(h)) + comp.flush()

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 1, 0, 0, 0, 0)) +
                chunk(b'IDAT', data) + chunk(b'IEND', b''))


class FakeApp(object):
    settings = core.Settings(os.path.join(HOME, 'settings.json'))


def trusted(path):
    return os.path.isabs(path) and os.path.dirname(path) in SYSTEM_DIRS


def s_admin_programs():
    """Whatever runs as administrator is named by its full system path and is never the user's own file."""
    core.run = recorder
    # 1. "Scan as administrator" started from a copy of the app that an ordinary user can change
    for name in ('powerful-tools', 'powerful-tools.py'):
        core.ENTRY = os.path.join(HOME, name)
        open(core.ENTRY, 'w').close()
        os.chmod(core.ENTRY, 0o755)
        del CALLS[:]
        _res, err = fileunlocker.scan_as_root(['/tmp'])
        check('administrator scan refuses to run a user-writable %s as root' % name, not CALLS and err, (CALLS, err))
    safe = getattr(fileunlocker, 'root_safe', lambda p: None)
    link = os.path.join(HOME, 'link-to-system-file')
    os.symlink('/etc/hostname' if os.path.exists('/etc/hostname') else '/etc/passwd', link)
    wrong = [p for p in (HOME, core.ENTRY, '/tmp', '/no/such/file', '') if safe(p) is not False]
    check('only files that root alone can change count as safe to run as root', not wrong
          and (os.stat('/etc').st_uid != 0 or safe(link) is True), (wrong, safe(link)))
    if INSTALLED:
        core.ENTRY = BIN
        del CALLS[:]
        fileunlocker.scan_as_root(['/tmp'])
        check('administrator scan of the installed package runs pkexec and the app by full path',
              CALLS and trusted(CALLS[-1][0]) and CALLS[-1][1:] == [BIN, '--unlocker-scan', '/tmp'], CALLS)
    # 2. ending a process: the number may now belong to another program
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    time.sleep(0.3)
    p = fileunlocker.FileUnlockerPage(FakeApp())
    with open('/proc/%d/comm' % child.pid) as f:
        comm = f.read().strip()
    p.store.append([child.pid, 'some-other-program', 'user', '', ''])
    p.tv.get_selection().select_path(Gtk.TreePath(0))
    p.kill()
    time.sleep(0.3)
    check('File Unlocker does not end a process whose name no longer matches the scan', child.poll() is None)
    p.store[0][1] = comm
    real_kill, os.kill = os.kill, lambda *_a: (_ for _ in ()).throw(PermissionError())
    try:
        del CALLS[:]
        p.kill()
    finally:
        os.kill = real_kill
    check('ending another user\'s process runs pkexec and kill by full path', len(CALLS) == 1
          and trusted(CALLS[0][0]) and trusted(CALLS[0][1]) and CALLS[0][2:] == ['-TERM', str(child.pid)], CALLS)
    child.kill()
    child.wait()
    # 3. hosts: the file named by PT_HOSTS_FILE (a test hook) is never written as administrator
    h = hosts.HostsPage(FakeApp())
    h.add_entry()
    del CALLS[:]
    h.save()
    check('Hosts editor never writes a file other than /etc/hosts as administrator', os.getuid() == 0 or (
        not CALLS and open(hosts.HOSTS).read() == '127.0.0.1\tlocalhost\n'), CALLS)
    h._edited(None, '0', '::1%x\n6.6.6.6 bank.example', 1)
    h._edited(None, '0', 'fine.example\nbank.example', 2)
    h._edited(None, '0', 'note\r6.6.6.6 bank.example\x0c7.7.7.7 shop.example', 3)
    text = logic.serialize_hosts(h.items)
    check('Hosts editor fields cannot add a line to the file', h.store[0][1] == '127.0.0.1'
          and not re.search(r'(^|[\n\r\x0b\x0c])\s*[67]\.', text) and text.count('\n') == 2, repr(text))
    if not os.access('/etc/hosts', os.W_OK):
        hosts.HOSTS = '/etc/hosts'
        h.load()
        h.add_entry()
        del CALLS[:]
        h.save()
        check('saving /etc/hosts runs pkexec and tee by full path', not CALLS or (
            len(CALLS) == 1 and trusted(CALLS[0][0]) and trusted(CALLS[0][1]) and CALLS[0][2:] == ['/etc/hosts']), CALLS)
    core.run = real_run


def s_install_path():
    """The app writes its own path into scripts, shortcuts and a login entry: a strange path must stay a path."""
    work = tempfile.mkdtemp(dir=HOME)
    core.ENTRY = os.path.join(HOME, 'my tools', '$(touch PWNED)`touch PWNED`";touch PWNED;"', 'powerful-tools')
    os.makedirs(os.path.join(HOME, '.local', 'share', 'nautilus'))
    A.install_fm_scripts()
    script = os.path.join(HOME, '.local/share/nautilus/scripts/Powerful Tools Peek')
    subprocess.call(['sh', script, 'file'], cwd=work, stderr=subprocess.DEVNULL)
    check('file manager script cannot be made to run commands through the install path', os.listdir(work) == [],
          open(script).read())
    A.remove_fm_scripts()
    ok, argv = GLib.shell_parse_argv(keyboard.action_command('--run'))
    check('keyboard shortcut command keeps a strange install path in one piece', argv == [core.ENTRY, '--run'], argv)
    for entry in (core.ENTRY, HOME + '/a\nExec=evil\n/powerful-tools', HOME + '/a"b/powerful-tools',
                  HOME + '/100%/powerful-tools', HOME + '/back\\slash/powerful-tools', HOME + '/with space/powerful-tools'):
        core.ENTRY = entry
        if os.path.exists(fancyzones.AUTOSTART):
            os.unlink(fancyzones.AUTOSTART)
        try:
            fancyzones.set_autostart(True)
        except OSError:
            pass
        argv = None
        if os.path.exists(fancyzones.AUTOSTART):
            kf = GLib.KeyFile()
            try:
                kf.load_from_file(fancyzones.AUTOSTART, GLib.KeyFileFlags.NONE)
                argv = GLib.shell_parse_argv(kf.get_string('Desktop Entry', 'Exec'))[1]
            except GLib.Error as e:
                argv = str(e)
        want = [entry, '--background'] if 'with space' in entry else (None, [entry, '--background'])
        check('login entry is either exact or not written for the path %r' % os.path.relpath(entry, HOME)[:24],
              argv == want or argv in want, argv)
    fancyzones.set_autostart(False)
    check('login entry is removed when hovering is turned off', not os.path.exists(fancyzones.AUTOSTART))
    fancyzones.set_autostart(False)  # twice: nothing to remove is not an error
    core.ENTRY = BIN


def s_files():
    """Files the user is tricked into opening or that another local user prepared."""
    GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 1200, 900).savev(PNG, 'png', [], [])
    # previews never block or read without end
    fifo = os.path.join(HOME, 'pipe.txt')
    os.mkfifo(fifo)
    w = within(8, peek.preview_widget, fifo)
    check('Peek does not hang on a named pipe', isinstance(w, Gtk.Box), w)
    for path in ('/dev/zero', '/dev/urandom', '/dev/null'):
        w = within(8, peek.preview_widget, path)
        check('Peek shows only details for %s' % path, isinstance(w, Gtk.Box), type(w).__name__)
    dangling = os.path.join(HOME, 'dangling')
    os.symlink('/no/such/target', dangling)
    secret = os.path.join(HOME, 'unreadable.txt')
    open(secret, 'w').close()
    os.chmod(secret, 0)
    for path in (dangling, secret, os.path.join(HOME, 'missing'), HOME + '/\udcff-bad-name'):
        w = within(8, peek.preview_widget, path)
        check('Peek reports %s instead of failing' % os.path.basename(path).encode('ascii', 'replace').decode(),
              isinstance(w, Gtk.Widget), w)
    big = os.path.join(HOME, 'big.log')
    with open(big, 'wb') as f:
        f.write(b'\xff\xfe broken utf-8 <b>not markup</b> &amp;\n' + b'x' * (3 * 1024 * 1024))
    w = within(20, peek.preview_widget, big)
    buf = w.get_child().get_buffer() if isinstance(w, Gtk.ScrolledWindow) else None
    check('Peek cuts a huge text file short and shows markup as plain text', buf is not None
          and buf.get_char_count() < peek.TEXT_LIMIT + 100 and '<b>not markup</b> &amp;' in
          buf.get_text(buf.get_start_iter(), buf.get_iter_at_line(1), False), type(w).__name__)
    many = os.path.join(HOME, 'many')
    os.makedirs(many)
    for i in range(1200):
        open(os.path.join(many, '<b>%04d<b>' % i), 'w').close()
    w = within(20, peek.preview_widget, many)
    rows = w.get_child().get_child().get_children() if isinstance(w, Gtk.ScrolledWindow) else []
    first = rows[0].get_child().get_children()[1].get_text() if rows else None
    check('Peek lists at most 1000 entries of a folder, names as plain text', len(rows) == 1001 and first == '<b>0000<b>',
          (len(rows), first))
    # image resizer: a private picture stays private, and a link planted at the old temporary name is not followed
    d = os.path.join(HOME, 'shared')
    os.makedirs(d)
    src = os.path.join(d, 'private.png')
    GdkPixbuf.Pixbuf.new_from_file(PNG).savev(src, 'png', [], [])
    os.chmod(src, 0o600)
    victim = os.path.join(HOME, 'victim.txt')
    with open(victim, 'w') as f:
        f.write('SECRET')
    opts = {'w': 854, 'h': 480, 'mode': 'fit', 'unit': 'px', 'shrink_only': False, 'overwrite': False,
            'pattern': '%1 (%2)', 'format': 'keep', 'quality': 90, 'size_name': 'Small'}
    os.symlink(victim, logic.output_path(src, 'Small', '%1 (%2)', '.png') + '.pt-tmp')
    old = os.umask(0o022)
    out = imageresizer.resize_file(src, opts)
    os.umask(old)
    check('Image Resizer does not write through a link planted next to the picture', open(victim, 'rb').read() == b'SECRET'
          and not os.path.islink(out) and GdkPixbuf.Pixbuf.get_file_info(out)[1] == 640)
    check('a resized copy of a private picture is private too', os.stat(out).st_mode & 0o077 == 0,
          oct(os.stat(out).st_mode))
    left = [n for n in os.listdir(d) if n.startswith('.pt-')]
    check('Image Resizer leaves no temporary files behind', not left, left)
    for name, data in (('empty.png', b''), ('text.png', b'not an image'), ('cut.png', open(PNG, 'rb').read()[:60])):
        with open(os.path.join(d, name), 'wb') as f:
            f.write(data)
        try:
            imageresizer.resize_file(os.path.join(d, name), opts)
            err = None
        except Exception as e:
            err = e
        check('Image Resizer reports the damaged image %s and writes nothing' % name, isinstance(err, GLib.Error)
              and not [n for n in os.listdir(d) if n.startswith(name[:-4] + ' (') or n.startswith('.pt-')], err)
    # screenshots taken through a command-line tool go to a folder only this user can open, and are deleted
    got = []
    core._capture_cli(lambda pb, err: got.append((pb, err)))
    log = open(os.environ['PT_SHOT_LOG']).read().split() if os.path.exists(os.environ['PT_SHOT_LOG']) else None
    leftovers = [n for n in os.listdir(tempfile.gettempdir()) if n.startswith('pt-shot-')]
    check('screenshot helper writes into a private folder and removes it', got and got[0][0] is not None
          and log == ['700', str(os.getuid())] and not leftovers, (got, log, leftovers))
    os.unlink(os.path.join(PLANT, 'gnome-screenshot'))
    got, path = [], os.environ['PATH']
    os.environ['PATH'] = PLANT  # no screenshot tool anywhere
    core._capture_cli(lambda pb, err: got.append((pb, err)))
    os.environ['PATH'] = path
    check('no screenshot tool: an error message, nothing left in the temporary folder', got and got[0][0] is None
          and got[0][1] and not [n for n in os.listdir(tempfile.gettempdir()) if n.startswith('pt-shot-')], got)


def s_settings():
    """The settings file can be edited by hand or damaged: values of the wrong kind are ignored."""
    path = os.path.join(HOME, 'bad', 'settings.json')
    os.makedirs(os.path.dirname(path))
    for raw in (b'', b'{', b'[1, 2]', b'"text"', b'null', b'\xff\xfe\x00', b'{"theme": "dark"} trailing'):
        with open(path, 'wb') as f:
            f.write(raw)
        try:
            s = core.Settings(path)
        except Exception as e:  # a damaged file must never stop the app from starting
            s = e
        check('settings file containing %r is ignored' % raw[:12], getattr(s, 'data', None) == {}, s)
    with open(path, 'w') as f:
        f.write('{"theme": 5, "resize_w": "wide", "resize_h": NaN, "resize_quality": Infinity, "zones_hover": "no", '
                '"color_history": "red", "run_engine": ["x"], "awake_hours": null, "resize_shrink": 1, "ok": 7.5, '
                '"flag": false, "name": "n", "list": [1]}')
    s = core.Settings(path)
    got = [s.get('theme', 'system'), s.get('resize_w', 1024), s.get('resize_h', 768), s.get('resize_quality', 90),
           s.get('zones_hover', True), s.get('color_history', []), s.get('run_engine', 'google'),
           s.get('awake_hours', 1), s.get('resize_shrink', False)]
    check('settings of the wrong kind fall back to the defaults', got == ['system', 1024, 768, 90, True, [], 'google',
                                                                         1, False], got)
    check('settings of the right kind are kept', (s.get('ok', 1), s.get('flag', True), s.get('name', ''), s.get('list', []),
                                                  s.get('missing'), s.get('theme')) == (7.5, False, 'n', [1], None, 5))
    path = os.path.join(HOME, 'new', 'deeper', 'settings.json')
    core.Settings(path).set('theme', 'dark')
    mode = os.stat(path).st_mode & 0o777
    check('settings are saved readable by this user only, with nothing left over', mode == 0o600
          and os.listdir(os.path.dirname(path)) == ['settings.json'] and json.load(open(path)) == {'theme': 'dark'}, oct(mode))
    ro = os.path.join(HOME, 'ro')
    os.makedirs(ro)
    os.chmod(ro, 0o500)
    try:
        core.write_file_atomic(os.path.join(ro, 'x'), 'data')
        err = None if os.getuid() else OSError()  # root may write anywhere
    except OSError as e:
        err = e
    check('a save that fails raises an error and leaves no partial file', err is not None
          and (os.getuid() == 0 or os.listdir(ro) == []), err)
    os.chmod(ro, 0o700)


def s_windows():
    """Window titles are chosen by other programs (and by web pages): they are text, never markup or commands."""
    titles = ['<b>bold</b> <span foreground="red">&amp;</span>', 'two\nlines', '', 'x' * 20000, '_underlined', '%s %d']
    pk = fancyzones.ZonePicker(None, [(0, 0, 400, 300), (400, 0, 1, 1)], [('0x%08x' % i, t) for i, t in enumerate(titles)])
    shown = [b.get_child().get_text() for b in pk.list.get_children()]
    check('window titles are shown as plain text', shown == [t or '(untitled)' for t in titles], shown[:3])
    check('a very long title does not widen the picker', pk.get_size()[0] <= 400, pk.get_size())
    mark = os.path.join(HOME, 'WINDOW-ID-RAN')
    for wid in ('0x1; touch %s' % mark, '$(touch %s)' % mark, '-h', '', '0xZZ'):
        ok = within(20, fancyzones.place, wid, (0, 0, 100, 100))
        check('window id %r is never run as a command' % wid[:12], ok is False and not os.path.exists(mark), ok)
    pk.pick('0x1; touch %s' % mark)  # the second zone is one pixel: still no crash
    check('picker survives an unknown window and a one-pixel zone', pk.get_visible() and len(pk.zones) == 1
          and not os.path.exists(mark))
    pk.destroy()
    r = launcher.search('> rm -rf "$HOME"; touch %s' % mark, [], 'https://x.test/?q=')
    check('Quick Launcher only offers a typed command, it runs nothing while typing', len(r) == 1
          and r[0].action[0] == 'shell' and not os.path.exists(mark))
    for q in ('9**999', 'factorial(1000)', '=' * 400, '??' + 'x' * 5000, '/no/such/dir/x', '~nobody-here/x', '\0', '>', '??'):
        r = within(10, launcher.search, q, [], 'https://x.test/?q=')
        check('Quick Launcher copes with %r' % q[:16], isinstance(r, list), r)
    r = launcher.search('?? a&b=c#d e/../f', [], 'https://x.test/?q=')
    check('web search text cannot change the address', r[0].action == ('uri', 'https://x.test/?q=a%26b%3Dc%23d+e%2F..%2Ff'),
          r[0].action)


def s_command_line():
    env = dict((k, v) for k, v in os.environ.items() if k != 'DISPLAY')

    def run(*args):
        p = subprocess.run([BIN] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=60)
        return p.returncode, p.stdout.decode(), p.stderr.decode()
    for args in (['--bogus'], ['--page', 'nope'], ['--page'], ['--run', '--ruler'], ['--zones', '--always-on-top'],
                 ['--page', 'hosts; touch ' + MARK]):
        rc, out, err = run(*args)
        check('command line %s is refused with a usage message' % ' '.join(args)[:28], rc == 2 and 'usage:' in err
              and not out, (rc, out, err[-200:]))
    rc, out, _err = run('--version')
    check('--version works without a display', rc == 0 and out.strip() == 'Powerful Tools ' + core.VERSION, out)
    rc, out, _err = run('--help')
    check('--help lists every tool flag', rc == 0 and all(a[2].split()[0] in out for a in keyboard.ACTIONS))
    rc, out, err = run('--unlocker-scan', '/no/such/file', '--help', '$(touch %s)' % MARK, '-x', '--version')
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    check('the administrator scan treats every argument as a path and prints only JSON', rc == 0 and data is not None
          and sorted(data) == ['denied', 'results'] and data['results'] == [] and not err, (rc, out[:200], err[-300:]))


def s_data_stays_local():
    sources = dict((n, open(os.path.join(SRC, 'powerfultools', n)).read())
                   for n in sorted(os.listdir(os.path.join(SRC, 'powerfultools'))) if n.endswith('.py'))
    sources['bin/powerful-tools'] = open(BIN).read()
    net = r'^\s*(?:import|from)\s+(?:socket|ssl|http|urllib\.request|urllib3|requests|ftplib|smtplib|telnetlib|xmlrpc|asyncio)\b'
    found = [(n, m) for n, s in sources.items() for m in re.findall(net, s, re.M)]
    found += [(n, m) for n, s in sources.items() for m in re.findall(r'urlopen|urlretrieve|\.connect_ex\(|create_connection', s)]
    check('no part of the app can open a network connection', len(sources) > 20 and not found, found)
    risky = r'(?<![\w.])(?:eval|exec)\(|\bpickle\b|\bmarshal\b|os\.system|os\.popen|shell=True|markup=True|yaml\.load'
    found = [(n, m) for n, s in sources.items() for m in re.findall(risky, s)]
    check('no eval, exec, shell=True, pickle or markup from outside text anywhere', not found, found)
    urls = sorted(set(m for s in sources.values() for m in re.findall(r'\w+://[^\s\'"]+', s)))
    check('the only web addresses are the three search engines, opened in the browser on request',
          urls == sorted(e[2] for e in launcher.ENGINES), urls)
    if INSTALLED:
        bad = []
        for top in ('/usr/lib/powerful-tools', BIN, '/usr/share/applications/' + core.APP_ID + '.desktop'):
            for root, dirs, files in os.walk(top) if os.path.isdir(top) else [(os.path.dirname(top), [], [os.path.basename(top)])]:
                for n in dirs + files + ['.']:
                    st = os.lstat(os.path.join(root, n))
                    if st.st_uid != 0 or st.st_mode & 0o6022:
                        bad.append((os.path.join(root, n), st.st_uid, oct(st.st_mode)))
        check('installed files belong to root, nobody else can change them, none is setuid', not bad, bad[:5])
        check('the installed app counts as safe for the administrator scan', hasattr(fileunlocker, 'root_safe')
              and fileunlocker.root_safe(BIN) and fileunlocker.root_safe(logic.__file__))


def s_image_bomb():
    """Last: before the fix these decode gigabytes. A 30000 x 30000 image is 120 kB on disk."""
    bomb = os.path.join(HOME, 'bomb.png')
    write_png(bomb, 30000, 30000)
    small = os.path.join(HOME, 'tiny.png')
    write_png(small, 64, 64)
    check('a small hand-made image still previews (the test image itself is valid)',
          type(within(20, peek.preview_widget, small)).__name__ == 'ImageView')
    info = GdkPixbuf.Pixbuf.get_file_info(bomb)
    limit = getattr(core, 'MAX_PIXELS', 0)
    check('test image is a real decompression bomb', os.path.getsize(bomb) < 300000 and info[1] * info[2] > limit > 0,
          (os.path.getsize(bomb), info[1:], limit))
    if not limit:
        return  # without the limit the next two calls would use about 3 GB
    w = within(30, peek.preview_widget, bomb)
    check('Peek shows only details for an image that would not fit in memory', isinstance(w, Gtk.Box), type(w).__name__)
    try:
        imageresizer.resize_file(bomb, {'w': 10, 'h': 10, 'mode': 'fit', 'unit': 'px', 'shrink_only': False,
                                        'overwrite': False, 'pattern': '%1 (%2)', 'format': 'keep', 'quality': 90,
                                        'size_name': 'S'})
        err = None
    except ValueError as e:
        err = e
    check('Image Resizer refuses it with a clear message', err is not None and 'too large' in str(err), err)


if __name__ == '__main__':
    for section in (s_admin_programs, s_install_path, s_files, s_settings, s_windows, s_command_line,
                    s_data_stays_local, s_image_bomb):
        try:
            section()
        except Exception:
            check(section.__name__ + ' ran to the end', False, traceback.format_exc())
        finally:
            core.run = real_run
    check('no program planted in the user\'s PATH was ever run', not os.path.exists(MARK))
    print('\n%d security checks, %d failed' % (len(RESULTS), RESULTS.count(False)))
    sys.exit(1 if False in RESULTS else 0)
