from gi.repository import Gtk

from . import core

SCHEMAS = [('org.gnome.desktop.wm.keybindings', 'Windows'), ('org.gnome.shell.keybindings', 'Desktop shell'),
           ('org.gnome.mutter.keybindings', 'Window tiling'), ('org.gnome.mutter.wayland.keybindings', 'Session'),
           ('org.gnome.settings-daemon.plugins.media-keys', 'System')]
GENERIC = [('Common', [('Copy / Cut / Paste', '<Primary>c  <Primary>x  <Primary>v'), ('Undo', '<Primary>z'),
                       ('Select all', '<Primary>a'), ('Find', '<Primary>f'), ('Close window', '<Alt>F4'),
                       ('Switch windows', '<Alt>Tab'), ('Lock screen', '<Super>l'),
                       ('Open terminal (most desktops)', '<Primary><Alt>t'), ('Screenshot', 'Print')])]


def _nice(key):
    return key.replace('-', ' ').replace('_', ' ').strip().capitalize()


def collect():
    """[(group title, [(action, accelerator string)])] for the running desktop."""
    groups = []
    for schema, title in SCHEMAS:
        s = core.gsettings(schema)
        if s is None:
            continue
        items = []
        for key in sorted(s.list_keys()):
            try:
                val = s.get_value(key).unpack()
            except Exception:
                continue
            if isinstance(val, str):
                val = [val]
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                continue
            accels = [v for v in val if v and v != 'disabled' and Gtk.accelerator_parse(v)[0] != 0]
            if accels:
                items.append((_nice(key), '  '.join(accels)))
        if items:
            groups.append((title, items))
    customs = [(k['name'], k['binding']) for k in core.list_custom_keybindings() if k['binding']]
    if customs:
        groups.append(('Custom and Powerful Tools', customs))
    return groups or GENERIC


class ShortcutGuidePage(core.Page):
    ID = 'shortcutguide'
    TITLE = 'Shortcut Guide'
    ICON = 'preferences-desktop-keyboard-shortcuts-symbolic'
    DESC = 'All keyboard shortcuts of your desktop in one searchable place.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.search = Gtk.SearchEntry(placeholder_text='Search shortcuts')
        self.search.connect('changed', lambda *_: self.render())
        self.add_widget(self.search)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.add_widget(self.box)
        self.groups = None

    def on_shown(self):
        self.groups = collect()
        self.render()
        self.search.grab_focus()

    def render(self):
        if self.groups is None:
            return
        for c in self.box.get_children():
            c.destroy()
        q = self.search.get_text().strip().lower()
        shown = 0
        for title, items in self.groups:
            rows = []
            for action, accels in items:
                labels = '  ·  '.join(core.accel_label(a) for a in accels.split('  '))
                if q and q not in action.lower() and q not in labels.lower():
                    continue
                lab = core.label(labels, 'pt-mono', wrap=True, xalign=1)
                rows.append(core.row(action, None, lab))
            if rows:
                shown += len(rows)
                self.box.pack_start(core.card(*rows, title=title, spacing=6), False, False, 0)
        if not shown:
            self.box.pack_start(core.label('No shortcuts match.', 'pt-dim'), False, False, 0)
        self.box.show_all()
