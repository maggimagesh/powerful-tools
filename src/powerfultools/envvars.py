import os

from gi.repository import Gtk, Pango

from . import core, logic


def profile_path():
    return os.path.join(os.path.expanduser('~'), '.profile')


class EnvVarsPage(core.Page):
    ID = 'envvars'
    TITLE = 'Environment Variables'
    ICON = 'utilities-terminal-symbolic'
    DESC = ('Manage your user environment variables. They are saved in ~/.profile (no administrator rights '
            'needed) and apply after you log out and back in. Values may reference other variables, '
            'e.g. PATH = $PATH:$HOME/bin')

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.user = Gtk.ListStore(str, str)
        tv = Gtk.TreeView(model=self.user)
        self.utv = tv
        for i, t in enumerate(('Name', 'Value')):
            cell = Gtk.CellRendererText(editable=True, ellipsize=Pango.EllipsizeMode.END)
            cell.connect('edited', self._edited, i)
            col = Gtk.TreeViewColumn(t, cell, text=i)
            col.set_resizable(True)
            col.set_expand(i == 1)
            col.set_min_width(100)
            tv.append_column(col)
        self.add_widget(core.card(
            core.scrolled(tv, 180),
            core.button_row(core.button('New variable', self.add_var, 'list-add-symbolic'),
                            core.button('Delete selected', self.delete, 'list-remove-symbolic'),
                            core.button('Reload', self.load, 'view-refresh-symbolic'),
                            core.button('Save', self.save, 'document-save-symbolic', suggested=True)),
            title='User variables (~/.profile)'))

        self.search = Gtk.SearchEntry(placeholder_text='Filter current variables')
        self.cur = Gtk.ListStore(str, str)
        self.fcur = self.cur.filter_new()
        self.fcur.set_visible_func(lambda m, it, d: not self.search.get_text() or
                                   self.search.get_text().lower() in (m[it][0] + ' ' + m[it][1]).lower())
        self.search.connect('changed', lambda *_: self.fcur.refilter())
        ctv = Gtk.TreeView(model=self.fcur)
        for i, t in enumerate(('Name', 'Value')):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(t, cell, text=i)
            col.set_resizable(True)
            col.set_expand(i == 1)
            col.set_min_width(100)
            ctv.append_column(col)
        for k in sorted(os.environ):
            self.cur.append([k, os.environ[k]])
        self.add_widget(core.card(self.search, core.scrolled(ctv, 220),
                                  title='Current session (read-only)'))
        self.load()

    def load(self):
        self.user.clear()
        try:
            with open(profile_path()) as f:
                text = f.read()
        except FileNotFoundError:
            text = ''
        except OSError as e:
            self.toast('Could not read ~/.profile: %s' % e, error=True)
            return
        for n, v in logic.env_block_parse(text):
            self.user.append([n, v])

    def _edited(self, cell, path, text, col):
        if col == 0:
            text = text.strip()
            if not logic.valid_env_name(text):
                self.toast('Names may only contain letters, digits and _ and must not start with a digit',
                           error=True)
                return
        elif not logic.valid_env_value(text):
            self.toast('Values must be a single line', error=True)
            return
        self.user[path][col] = text

    def add_var(self):
        names = set(r[0] for r in self.user)
        n, i = 'NEW_VARIABLE', 1
        while n in names:
            i += 1
            n = 'NEW_VARIABLE_%d' % i
        it = self.user.append([n, ''])
        self.utv.set_cursor(self.user.get_path(it), self.utv.get_column(0), True)

    def delete(self):
        model, it = self.utv.get_selection().get_selected()
        if it is not None:
            model.remove(it)

    def save(self):
        variables = [(r[0], r[1]) for r in self.user]
        names = [n for n, _ in variables]
        dup = sorted(set(n for n in names if names.count(n) > 1))
        if dup:
            self.toast('Duplicate names: %s' % ', '.join(dup), error=True)
            return
        path = profile_path()
        try:
            try:
                with open(path) as f:
                    text = f.read()
            except FileNotFoundError:
                text = ''
            new = logic.env_block_render(text, variables)
            if new == text:
                self.toast('No changes to save')
                return
            bak = path + '.powerful-tools.bak'
            if text and not os.path.exists(bak):
                core.write_file_atomic(bak, text)
            core.write_file_atomic(path, new)
        except (OSError, ValueError) as e:
            self.toast('Not saved: %s' % e, error=True)
            return
        self.toast('Saved. Log out and back in for changes to apply everywhere.')
