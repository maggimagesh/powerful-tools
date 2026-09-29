import os
import shlex
import shutil
from urllib.parse import quote_plus

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import core, logic

ENGINES = [('google', 'Google', 'https://www.google.com/search?q='),
           ('bing', 'Bing', 'https://www.bing.com/search?q='),
           ('duckduckgo', 'DuckDuckGo', 'https://duckduckgo.com/?q=')]
MAX_RESULTS = 8


def terminal_command(cmd):
    """Command list that runs `cmd` in a terminal window and waits for Enter."""
    inner = "%s; printf '\\n[Press Enter to close]'; read _x" % cmd
    for term, args in (('x-terminal-emulator', ['-e', 'sh', '-c', inner]), ('gnome-terminal', ['--', 'sh', '-c', inner]),
                       ('konsole', ['-e', 'sh', '-c', inner]), ('xfce4-terminal', ['-x', 'sh', '-c', inner]),
                       ('mate-terminal', ['-x', 'sh', '-c', inner]), ('tilix', ['-e', 'sh -c ' + shlex.quote(inner)]),
                       ('xterm', ['-e', 'sh', '-c', inner])):
        if shutil.which(term):
            return [term] + args
    return None


def system_commands():
    cmds = []
    if shutil.which('loginctl'):
        cmds.append(('Lock screen', 'system-lock-screen', ['loginctl', 'lock-session']))
    if shutil.which('systemctl'):
        cmds.append(('Suspend', 'media-playback-pause', ['systemctl', 'suspend']))
    if shutil.which('gnome-session-quit'):
        cmds += [('Log out', 'system-log-out', ['gnome-session-quit', '--logout']),
                 ('Restart', 'system-reboot', ['gnome-session-quit', '--reboot']),
                 ('Shut down', 'system-shutdown', ['gnome-session-quit', '--power-off'])]
    return cmds


class Result(object):
    def __init__(self, title, subtitle, icon, action, gicon=None, complete=None):
        self.title, self.subtitle, self.icon, self.action, self.gicon = title, subtitle, icon, action, gicon
        self.complete = complete


def app_score(app, q):
    name = (app.get_display_name() or '').lower()
    if name.startswith(q):
        return 0
    if any(w.startswith(q) for w in name.split()):
        return 1
    if q in name:
        return 2
    extra = ' '.join(filter(None, [app.get_description() or '', app.get_executable() or '',
                                   ' '.join(app.get_keywords() or []) if hasattr(app, 'get_keywords') else '']))
    if q in extra.lower():
        return 3
    return None


def search(query, apps, engine_url):
    """Build the result list for a query (pure apart from launching)."""
    q = query.strip()
    res = []
    if not q:
        return res
    if q.startswith('>'):
        cmd = q[1:].strip()
        if cmd:
            res.append(Result('Run: ' + cmd, 'Run command in a terminal', 'utilities-terminal', ('shell', cmd)))
        return res
    if q.startswith('??'):
        term = q[2:].strip()
        if term:
            res.append(Result('Search the web for "%s"' % term, engine_url.split('/')[2], 'web-browser',
                              ('uri', engine_url + quote_plus(term))))
        return res
    if q.startswith('/') or q.startswith('~'):
        path = os.path.expanduser(q)
        d, prefix = (path, '') if path.endswith('/') else os.path.split(path)
        try:
            names = sorted(n for n in os.listdir(d or '/') if n.lower().startswith(prefix.lower())
                           and (not n.startswith('.') or prefix.startswith('.')))
        except OSError:
            names = []
        if os.path.exists(path) and not path.endswith('/'):
            res.append(Result(os.path.basename(path) or path, path, 'folder' if os.path.isdir(path)
                              else 'text-x-generic', ('path', path)))
        for n in names[:MAX_RESULTS]:
            full = os.path.join(d, n)
            if full == path:
                continue
            isdir = os.path.isdir(full)
            res.append(Result(n, full, 'folder' if isdir else 'text-x-generic', ('path', full),
                              complete=full + ('/' if isdir else '')))
        return res[:MAX_RESULTS]
    try:
        val = logic.calculate(q)
        if val != q.lstrip('='):
            res.append(Result('= ' + val, 'Press Enter to copy the result', 'accessories-calculator', ('copy', val)))
    except ValueError:
        pass
    ql = q.lower()
    scored = []
    for a in apps:
        s = app_score(a, ql)
        if s is not None:
            scored.append((s, (a.get_display_name() or '').lower(), a))
    scored.sort(key=lambda x: (x[0], x[1]))
    for _s, _n, a in scored[:MAX_RESULTS]:
        res.append(Result(a.get_display_name(), a.get_description() or 'Application', 'application-x-executable',
                          ('app', a), gicon=a.get_icon()))
    for title, icon, cmd in system_commands():
        if title.lower().startswith(ql) or (len(ql) >= 3 and ql in title.lower()):
            res.append(Result(title, 'System command', icon, ('cmd', cmd)))
    res = res[:MAX_RESULTS - 1]
    res.append(Result('Search the web for "%s"' % q, engine_url.split('/')[2], 'web-browser',
                      ('uri', engine_url + quote_plus(q))))
    return res


class LauncherWindow(Gtk.Window):
    def __init__(self, app):
        Gtk.Window.__init__(self, title='Quick Launcher')
        self.app = app
        if isinstance(app, Gtk.Application):
            self.set_application(app)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        mon = Gdk.Display.get_default().get_primary_monitor() or Gdk.Display.get_default().get_monitor(0)
        wa = mon.get_workarea()
        self.set_default_size(min(720, int(wa.width * 0.92)), -1)
        self.apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        engine = app.settings.get('run_engine', 'google')
        self.engine_url = dict((e[0], e[2]) for e in ENGINES).get(engine, ENGINES[0][2])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(10)
        box.get_style_context().add_class('pt-card')
        self.entry = Gtk.SearchEntry(placeholder_text='Search apps, files (/ or ~), =math, >command, ??web')
        self.entry.get_style_context().add_class('pt-big-entry')
        self.list = Gtk.ListBox()
        self.list.set_activate_on_single_click(True)
        self.list.connect('row-activated', lambda l, r: self.activate(r))
        box.pack_start(self.entry, False, False, 0)
        box.pack_start(self.list, False, False, 0)
        self.add(box)
        self.results = []
        self.entry.connect('changed', self._changed)
        self.entry.connect('activate', lambda *_: self.activate(self.list.get_selected_row()))
        self.connect('key-press-event', self._key)
        self._focused = False
        self.connect('focus-in-event', self._focus_in)
        self.connect('focus-out-event', self._focus_out)

    def _focus_in(self, *_):
        self._focused = True

    def _focus_out(self, *_):
        if self._focused:  # only close after we really had focus
            GLib.timeout_add(150, self._maybe_close)

    def _maybe_close(self):
        if not self.is_active() and self.get_visible():
            self.destroy()
        return False

    def present_run(self):
        self.show_all()
        self.present()
        self.entry.grab_focus()

    def _changed(self, *_):
        for c in self.list.get_children():
            c.destroy()
        self.results = search(self.entry.get_text(), self.apps, self.engine_url)
        for r in self.results:
            row = Gtk.ListBoxRow()
            row.result = r
            b = Gtk.Box(spacing=10)
            b.set_border_width(6)
            img = Gtk.Image.new_from_gicon(r.gicon, Gtk.IconSize.DND) if r.gicon else \
                Gtk.Image.new_from_icon_name(r.icon, Gtk.IconSize.DND)
            img.set_pixel_size(32)
            b.pack_start(img, False, False, 0)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            title = core.label(r.title, wrap=False)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            sub = core.label(r.subtitle, 'pt-dim', wrap=False)
            sub.set_ellipsize(Pango.EllipsizeMode.END)
            t.pack_start(title, False, False, 0)
            t.pack_start(sub, False, False, 0)
            b.pack_start(t, True, True, 0)
            row.add(b)
            self.list.add(row)
        self.list.show_all()
        first = self.list.get_row_at_index(0)
        if first:
            self.list.select_row(first)
        self.resize(self.get_allocated_width(), 1)  # shrink back when fewer results

    def _key(self, w, ev):
        k = ev.keyval
        if k == Gdk.KEY_Escape:
            self.destroy()
            return True
        if k in (Gdk.KEY_Down, Gdk.KEY_Up):
            row = self.list.get_selected_row()
            i = row.get_index() if row else -1
            n = len(self.results)
            if n:
                i = (i + (1 if k == Gdk.KEY_Down else -1)) % n
                self.list.select_row(self.list.get_row_at_index(i))
            return True
        if k == Gdk.KEY_Tab:
            row = self.list.get_selected_row()
            if row and row.result.complete:
                self.entry.set_text(row.result.complete)
                self.entry.set_position(-1)
            return True
        return False

    def activate(self, row):
        if row is None:
            return
        kind, val = row.result.action
        try:
            if kind == 'app':
                ctx = Gdk.Display.get_default().get_app_launch_context()
                val.launch([], ctx)
            elif kind == 'copy':
                core.copy_text(val)
            elif kind in ('uri', 'path'):
                core.open_uri(val if kind == 'uri' else Gio.File.new_for_path(val).get_uri())
            elif kind == 'shell':
                cmd = terminal_command(val)
                core.spawn(cmd if cmd else ['sh', '-c', val])
            elif kind == 'cmd':
                core.spawn(val)
        except (GLib.Error, OSError) as e:
            core.message(self, 'Could not launch', str(e), error=True)
            return
        self.destroy()


class LauncherPage(core.Page):
    ID = 'launcher'
    TITLE = 'Quick Launcher'
    ICON = 'system-search-symbolic'
    DESC = 'A quick launcher: find and start apps, open files, calculate, run commands and search the web.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.add_widget(core.button_row(core.button('Open Quick Launcher', self.open, 'system-search-symbolic',
                                                    suggested=True)))
        tips = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for ex, d in (('app name', 'Launch an application'), ('= 2*(3+4)', 'Calculator (Enter copies the result)'),
                      ('/path or ~/path', 'Browse and open files (Tab completes)'),
                      ('> command', 'Run a command in a terminal'), ('?? words', 'Search the web'),
                      ('lock, suspend, log out', 'System commands')):
            tips.pack_start(core.row(ex, d, None), False, False, 0)
        self.add_widget(core.card(tips, title='How to use'))
        self.add_widget(core.card(core.row('Web search engine', None, core.combo(
            [(e[0], e[1]) for e in ENGINES], app.settings.get('run_engine', 'google'),
            lambda v: app.settings.set('run_engine', v))),
            core.label('Set a global shortcut for Quick Launcher in Keyboard Manager.', 'pt-dim')))

    def open(self):
        LauncherWindow(self.app).present_run()
