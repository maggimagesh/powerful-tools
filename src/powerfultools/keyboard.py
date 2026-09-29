import shutil

from gi.repository import Gtk

from . import core

# (id, title, command-line flag, suggested accelerator)
ACTIONS = [
    ('run', 'Quick Launcher', '--run', '<Primary><Alt>space'),
    ('colorpicker', 'Color Picker', '--pick-color', '<Shift><Super>c'),
    ('textextractor', 'Text Extractor', '--text-extract', '<Shift><Super>t'),
    ('ruler', 'Screen Ruler', '--ruler', '<Shift><Super>m'),
    ('aot', 'Always On Top (toggle focused window)', '--always-on-top', '<Primary><Super>t'),
    ('paste', 'Advanced Paste', '--advanced-paste', '<Shift><Super>v'),
    ('guide', 'Shortcut Guide', '--shortcut-guide', '<Shift><Super>slash'),
]

REMAPS = [
    ('caps:escape', 'Caps Lock acts as Escape', 'caps'),
    ('caps:swapescape', 'Swap Caps Lock and Escape', 'caps'),
    ('ctrl:nocaps', 'Caps Lock acts as Ctrl', 'caps'),
    ('ctrl:swapcaps', 'Swap Caps Lock and left Ctrl', 'caps'),
    ('caps:none', 'Disable Caps Lock', 'caps'),
    ('altwin:swap_alt_win', 'Swap Alt and Super (Windows) keys', 'altwin'),
    ('compose:ralt', 'Right Alt is the Compose key', 'compose'),
    ('shift:both_capslock', 'Both Shift keys together toggle Caps Lock', 'shift'),
]
INPUT_SOURCES = 'org.gnome.desktop.input-sources'


def action_command(flag):
    return '%s %s' % (core.ENTRY, flag)


def xkb_backend():
    if core.schema_exists(INPUT_SOURCES):
        return 'gsettings'
    if core.is_x11() and shutil.which('setxkbmap'):
        return 'setxkbmap'
    return None


def get_xkb_options():
    b = xkb_backend()
    if b == 'gsettings':
        return list(core.gsettings(INPUT_SOURCES).get_strv('xkb-options'))
    if b == 'setxkbmap':
        rc, out, _ = core.run(['setxkbmap', '-query'])
        for line in out.splitlines():
            if line.startswith('options:'):
                return [o for o in line.split(':', 1)[1].strip().split(',') if o]
    return []


def set_xkb_options(opts):
    b = xkb_backend()
    if b == 'gsettings':
        core.gsettings(INPUT_SOURCES).set_strv('xkb-options', opts)
        core.Gio.Settings.sync()
        return True
    if b == 'setxkbmap':
        return core.run(['setxkbmap', '-option', '', '-option', ','.join(opts)])[0] == 0
    return False


class KeyboardPage(core.Page):
    ID = 'keyboard'
    TITLE = 'Keyboard Manager'
    ICON = 'input-keyboard-symbolic'
    DESC = 'Set activation shortcuts for Powerful Tools, remap keys and create your own global shortcuts.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.kb_ok = core.keybindings_supported()
        if not self.kb_ok:
            self.add_widget(core.card(core.label(
                'Global shortcuts can be registered automatically on GNOME, Ubuntu, Budgie and Unity. On %s, '
                'add them in your system keyboard settings using these commands:' % core.desktop_name()),
                core.label('\n'.join('%s:  %s' % (t, action_command(f)) for _i, t, f, _a in ACTIONS),
                           'pt-mono', selectable=True), title='Shortcuts'))
        self.actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        if self.kb_ok:
            self.add_widget(core.card(self.actions_box, title='Powerful Tools activation shortcuts'))

        self.remap_checks = {}
        remap_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        backend = xkb_backend()
        if backend is None:
            remap_box.pack_start(core.label('Key remapping is not available on this desktop. Use your system '
                                            'keyboard settings instead.', 'pt-dim'), False, False, 0)
        else:
            current = get_xkb_options()
            for opt, text, _g in REMAPS:
                cb = Gtk.CheckButton(label=text, active=opt in current)
                cb.connect('toggled', self._remap_toggled, opt)
                self.remap_checks[opt] = cb
                remap_box.pack_start(cb, False, False, 0)
            if backend == 'setxkbmap':
                remap_box.pack_start(core.label('Applied to the current session only (X11).', 'pt-dim'),
                                     False, False, 0)
        self.add_widget(core.card(remap_box, title='Remap keys'))

        self.custom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        if self.kb_ok:
            self.c_name = Gtk.Entry(placeholder_text='Name, e.g. Open terminal')
            self.c_cmd = Gtk.Entry(placeholder_text='Command, e.g. gnome-terminal')
            self.c_accel = ''
            self.c_btn = core.button('Choose shortcut…', self._pick_custom_accel, 'input-keyboard-symbolic')
            self.add_widget(core.card(self.custom_box, core.label('Add a shortcut', 'pt-heading'),
                                      self.c_name, self.c_cmd,
                                      core.button_row(self.c_btn, core.button('Add', self._add_custom,
                                                                              'list-add-symbolic',
                                                                              suggested=True)),
                                      title='Custom shortcuts'))
        self.refresh()

    def refresh(self):
        if not self.kb_ok:
            return
        existing = core.list_custom_keybindings()
        for c in self.actions_box.get_children():
            c.destroy()
        for aid, title, flag, default in ACTIONS:
            cmd = action_command(flag)
            kb = next((k for k in existing if k['command'].split()[-1:] == [flag]
                       and 'powerful-tools' in k['command']), None)
            box = Gtk.Box(spacing=6)
            box.pack_start(core.button('Change' if kb else 'Enable',
                                       lambda t=title, c=cmd, k=kb, d=default: self._set_action(t, c, k, d)),
                           False, False, 0)
            if kb:
                box.pack_start(core.button('', lambda k=kb: self._remove(k), 'user-trash-symbolic',
                                           tooltip='Remove shortcut'), False, False, 0)
            sub = core.accel_label(kb['binding']) if kb else 'Off (suggested: %s)' % core.accel_label(default)
            self.actions_box.pack_start(core.row(title, sub, box), False, False, 0)
        self.actions_box.show_all()
        for c in self.custom_box.get_children():
            c.destroy()
        others = [k for k in existing if 'powerful-tools' not in k['command']]
        if not others:
            self.custom_box.pack_start(core.label('No custom shortcuts yet.', 'pt-dim'), False, False, 0)
        for k in others:
            self.custom_box.pack_start(core.row(k['name'] or '(unnamed)', '%s  ·  %s' % (
                core.accel_label(k['binding']), k['command']),
                core.button('', lambda k=k: self._remove(k), 'user-trash-symbolic', tooltip='Delete')),
                False, False, 0)
        self.custom_box.show_all()

    def _set_action(self, title, cmd, kb, default):
        accel = core.ShortcutCapture(self.window).get()
        if accel is None:
            return
        if accel == '':
            if kb:
                self._remove(kb)
            return
        if self._conflict(accel, kb):
            return
        core.set_custom_keybinding('Powerful Tools: ' + title, cmd, accel, kb['path'] if kb else None)
        self.toast('%s shortcut set to %s' % (title, core.accel_label(accel)))
        self.refresh()

    def _conflict(self, accel, own=None):
        for k in core.list_custom_keybindings():
            if k['binding'] == accel and (own is None or k['path'] != own['path']):
                self.toast('%s is already used by "%s"' % (core.accel_label(accel), k['name']), error=True)
                return True
        return False

    def _remove(self, kb):
        core.remove_custom_keybinding(kb['path'])
        self.toast('Shortcut removed')
        self.refresh()

    def _pick_custom_accel(self):
        accel = core.ShortcutCapture(self.window).get()
        if accel:
            self.c_accel = accel
            self.c_btn.get_child().get_children()[1].set_text(core.accel_label(accel))

    def _add_custom(self):
        name, cmd = self.c_name.get_text().strip(), self.c_cmd.get_text().strip()
        if not name or not cmd or not self.c_accel:
            self.toast('Enter a name, a command and choose a shortcut', error=True)
            return
        if self._conflict(self.c_accel):
            return
        core.set_custom_keybinding(name, cmd, self.c_accel)
        self.c_name.set_text('')
        self.c_cmd.set_text('')
        self.c_accel = ''
        self.c_btn.get_child().get_children()[1].set_text('Choose shortcut…')
        self.toast('Shortcut added')
        self.refresh()

    def _remap_toggled(self, cb, opt):
        group = [g for o, _t, g in REMAPS if o == opt][0]
        opts = get_xkb_options()
        opts = [o for o in opts if o != opt]
        if cb.get_active():
            for o, _t, g in REMAPS:  # options in the same group are mutually exclusive
                if g == group and o != opt:
                    opts = [x for x in opts if x != o]
                    other = self.remap_checks.get(o)
                    if other and other.get_active():
                        other.handler_block_by_func(self._remap_toggled)
                        other.set_active(False)
                        other.handler_unblock_by_func(self._remap_toggled)
            opts.append(opt)
        if not set_xkb_options(opts):
            self.toast('Could not change keyboard options', error=True)
