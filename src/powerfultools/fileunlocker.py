import json
import os
import shutil
import signal

from gi.repository import GLib, Gtk, Pango

from . import core, logic


def root_safe(path):
    """True if only root can change this file: it and every folder above it belong to root and nobody else
    may write to them."""
    path = os.path.realpath(path)
    while True:
        try:
            st = os.stat(path)
        except OSError:
            return False
        if st.st_uid != 0 or st.st_mode & 0o022:
            return False
        if path == '/':
            return True
        path = os.path.dirname(path)


def scan_as_root(paths):
    """Run the scan through pkexec (asks for the admin password). Returns (results, error)."""
    pkexec = core.system_bin('pkexec')
    if not pkexec:
        return None, 'pkexec is not installed'
    entry = os.path.realpath(core.ENTRY if os.path.isabs(core.ENTRY) else shutil.which(core.ENTRY) or core.ENTRY)
    # root runs this program and the code it imports: never from a place an ordinary user can write to
    code = [entry, logic.__file__, os.path.join(os.path.dirname(logic.__file__), '__init__.py')]
    if not all(root_safe(p) for p in code):
        return None, 'Scanning as administrator needs the installed package (%s is not owned by root)' % entry
    rc, out, err = core.run([pkexec, entry, '--unlocker-scan'] + paths, timeout=300)
    if rc in (126, 127):
        return None, 'Authentication was cancelled'
    if rc != 0:
        return None, err.strip() or 'Scan failed'
    try:
        return json.loads(out)['results'], None
    except (ValueError, KeyError):
        return None, 'Unexpected output from scan'


class FileUnlockerPage(core.Page):
    ID = 'fileunlocker'
    TITLE = 'File Unlocker'
    ICON = 'system-lock-screen-symbolic'
    DESC = 'Find out which processes are using a file or folder, and end them if needed.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.targets = []
        self.targets_label = core.label('Nothing selected. Drop files or folders here.', 'pt-dim')
        self.add_widget(core.card(
            core.button_row(core.button('Add files', lambda: self.add_paths(core.choose_files(self.window)),
                                        'list-add-symbolic'),
                            core.button('Add folder', lambda: self.add_paths(core.choose_files(self.window, folders=True,
                                                                                         multiple=False)),
                                        'folder-symbolic'),
                            core.button('Clear', self.clear, 'edit-clear-symbolic')),
            self.targets_label, title='Files and folders'))
        core.enable_file_drop(self, self.add_paths)
        self.scan_btn = core.button('Scan', self.scan, 'system-search-symbolic', suggested=True)
        self.root_btn = core.button('Scan as administrator', lambda: self.scan(root=True),
                                    'dialog-password-symbolic')
        self.add_widget(core.button_row(self.scan_btn, self.root_btn))
        self.store = Gtk.ListStore(int, str, str, str, str)  # pid, name, user, files, cmdline
        self.tv = Gtk.TreeView(model=self.store)
        for i, t in ((1, 'Process'), (0, 'PID'), (2, 'User'), (3, 'Files in use'), (4, 'Command')):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(t, cell, text=i)
            col.set_resizable(True)
            col.set_expand(i in (3, 4))
            col.set_min_width(60)
            self.tv.append_column(col)
        self.info = core.label('', 'pt-dim')
        self.kill_btn = core.button('End selected process', self.kill, 'process-stop-symbolic', destructive=True)
        self.kill_btn.set_sensitive(False)
        self.tv.get_selection().connect('changed', lambda s: self.kill_btn.set_sensitive(
            s.get_selected()[1] is not None))
        self.add_widget(core.card(core.scrolled(self.tv, 220), self.info, core.button_row(self.kill_btn),
                                  title='Processes'))
        self._set_enabled()

    def _set_enabled(self):
        self.scan_btn.set_sensitive(bool(self.targets))
        self.root_btn.set_sensitive(bool(self.targets) and bool(core.system_bin('pkexec')))
        self.targets_label.set_text('\n'.join(self.targets) or 'Nothing selected. Drop files or folders here.')

    def add_paths(self, paths):
        for p in paths:
            p = os.path.abspath(p)
            if os.path.lexists(p) and p not in self.targets:
                self.targets.append(p)
        self._set_enabled()
        if self.targets:
            self.scan()

    def clear(self):
        self.targets = []
        self.store.clear()
        self.info.set_text('')
        self._set_enabled()

    def scan(self, root=False):
        if not self.targets:
            return
        if root:
            results, err = scan_as_root(self.targets)
            if err:
                self.toast(err, error=True)
                return
            denied = 0
        else:
            results, denied = logic.find_lockers(self.targets)
        self.store.clear()
        for r in results:
            self.store.append([r['pid'], r['name'], r['user'], ', '.join(r['files']), r['cmdline']])
        msg = 'No process is using these items.' if not results else '%d process%s found.' % (
            len(results), '' if len(results) == 1 else 'es')
        if denied:
            msg += ' %d processes owned by other users could not be checked; use "Scan as administrator".' % denied
        self.info.set_text(msg)

    def kill(self):
        model, it = self.tv.get_selection().get_selected()
        if it is None:
            return
        pid, name = model[it][0], model[it][1]
        if not core.confirm(self.window, 'End "%s" (PID %d)?' % (name, pid),
                            'Unsaved work in that program will be lost.', 'End process'):
            return
        try:  # the process may have ended since the scan and its number been given to another program
            with open('/proc/%d/comm' % pid) as f:
                same = f.read().strip() == name
        except OSError:
            same = False
        if not same:
            self.toast('That process has already ended')
            self.scan()
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            pkexec, kill = core.system_bin('pkexec'), core.system_bin('kill')
            if not pkexec or not kill:
                self.toast('Permission denied', error=True)
                return
            rc, _o, err = core.run([pkexec, kill, '-TERM', str(pid)], timeout=120)
            if rc != 0:
                self.toast('Could not end the process: %s' % (err.strip() or 'cancelled'), error=True)
                return
        GLib.timeout_add(700, lambda: self.scan() and False)
