import os

from gi.repository import Gtk

from . import core, logic

HOSTS = os.environ.get('PT_HOSTS_FILE', '/etc/hosts')


class HostsPage(core.Page):
    ID = 'hosts'
    TITLE = 'Hosts File Editor'
    ICON = 'network-server-symbolic'
    DESC = ('Edit /etc/hosts: map host names to IP addresses and enable or disable entries. '
            'Saving asks for your password because Linux requires administrator rights for this file.')

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.items = []
        self.filter = Gtk.SearchEntry(placeholder_text='Filter entries')
        self.store = Gtk.ListStore(bool, str, str, str, object)  # enabled, ip, hosts, comment, item dict
        self.fstore = self.store.filter_new()
        self.fstore.set_visible_func(self._visible)
        self.tv = Gtk.TreeView(model=self.fstore)
        tog = Gtk.CellRendererToggle()
        tog.connect('toggled', self._toggled)
        self.tv.append_column(Gtk.TreeViewColumn('Active', tog, active=0))
        for i, t in ((1, 'Address'), (2, 'Hosts'), (3, 'Comment')):
            cell = Gtk.CellRendererText(editable=True)
            cell.connect('edited', self._edited, i)
            col = Gtk.TreeViewColumn(t, cell, text=i)
            col.set_resizable(True)
            col.set_expand(i != 1)
            col.set_min_width(90)
            self.tv.append_column(col)
        self.filter.connect('changed', lambda *_: self.fstore.refilter())
        self.status = core.label('', 'pt-dim')
        self.add_widget(core.card(
            self.filter, core.scrolled(self.tv, 260),
            core.button_row(core.button('Add entry', self.add_entry, 'list-add-symbolic'),
                            core.button('Remove selected', self.remove_entry, 'list-remove-symbolic'),
                            core.button('Reload', self.load, 'view-refresh-symbolic')),
            self.status, title='Entries'))
        self.save_btn = core.button('Save', self.save, 'document-save-symbolic', suggested=True)
        self.add_widget(core.button_row(self.save_btn))
        self.load()

    def _visible(self, model, it, _data):
        q = self.filter.get_text().strip().lower()
        return not q or any(q in (model[it][i] or '').lower() for i in (1, 2, 3))

    def load(self):
        error = None
        try:
            with open(HOSTS) as f:
                self.original = f.read()
        except OSError as e:
            self.original = ''
            error = 'Could not read %s: %s' % (HOSTS, e)
        self.items = logic.parse_hosts(self.original)
        self.store.clear()
        for it in self.items:
            if isinstance(it, dict):
                self.store.append([it['enabled'], it['ip'], it['hosts'], it['comment'], it])
        self.status.set_text(error or '%d entries in %s' % (len(self.store), HOSTS))

    def _row(self, path):
        return self.store[self.fstore.convert_path_to_child_path(Gtk.TreePath(path))]

    def _toggled(self, cell, path):
        r = self._row(path)
        r[0] = not r[0]
        r[4]['enabled'] = r[0]

    def _edited(self, cell, path, text, col):
        r = self._row(path)
        text = text.strip()
        if col == 1 and text and not logic.valid_ip(text):
            self.toast('"%s" is not a valid IP address' % text, error=True)
            return
        if col == 2 and text and not logic.valid_hosts(text):
            self.toast('"%s" contains an invalid host name' % text, error=True)
            return
        if col == 3:
            text = text.replace('\n', ' ')
        r[col] = text
        r[4][{1: 'ip', 2: 'hosts', 3: 'comment'}[col]] = text

    def add_entry(self):
        d = {'enabled': True, 'ip': '127.0.0.1', 'hosts': 'example.local', 'comment': ''}
        self.items.append(d)
        self.filter.set_text('')
        it = self.store.append([True, d['ip'], d['hosts'], '', d])
        path = self.fstore.convert_child_path_to_path(self.store.get_path(it))
        if path is not None:
            self.tv.set_cursor(path, self.tv.get_column(1), True)

    def remove_entry(self):
        model, it = self.tv.get_selection().get_selected()
        if it is None:
            return
        child = self.fstore.convert_iter_to_child_iter(it)
        d = self.store[child][4]
        self.items = [x for x in self.items if x is not d]
        self.store.remove(child)

    def save(self):
        bad = [i + 1 for i, r in enumerate(self.store)
               if not logic.valid_ip(r[1]) or not logic.valid_hosts(r[2])]
        if bad:
            self.toast('Fix the address or host names in row(s): %s' % ', '.join(map(str, bad)), error=True)
            return
        text = logic.serialize_hosts(self.items)
        if text == self.original:
            self.toast('No changes to save')
            return
        try:  # keep a copy of the previous file in the user's config
            core.write_file_atomic(os.path.join(core.CONFIG_DIR, 'hosts.backup'), self.original)
        except OSError:
            pass
        if os.access(HOSTS, os.W_OK):
            try:
                with open(HOSTS, 'w') as f:
                    f.write(text)
            except OSError as e:
                self.toast('Could not save: %s' % e, error=True)
                return
        else:
            if HOSTS != '/etc/hosts':  # PT_HOSTS_FILE is for tests: never write another file as administrator
                self.toast('Cannot write %s' % HOSTS, error=True)
                return
            pkexec, tee = core.system_bin('pkexec'), core.system_bin('tee')
            if not pkexec or not tee:
                self.toast('pkexec is required to save /etc/hosts', error=True)
                return
            rc, _o, err = core.run([pkexec, tee, HOSTS], input_text=text, timeout=300)
            if rc != 0:
                self.toast('Not saved: %s' % ('authentication cancelled' if rc in (126, 127) else err.strip()),
                           error=True)
                return
        self.toast('Hosts file saved')
        self.load()
