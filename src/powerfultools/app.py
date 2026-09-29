import argparse
import os
import sys

from . import core
from .core import Gdk, Gio, GLib, Gtk
from . import (advancedpaste, alwaysontop, awake, colorpicker, envvars, fileunlocker, hosts, imageresizer,
               keyboard, launcher, peek, bulkrename, screenruler, templates, shortcutguide, textextractor)

FM_SCRIPTS = [('Powerful Tools Image Resizer', '--resize'), ('Powerful Tools Bulk Rename', '--rename'),
              ('Powerful Tools File Unlocker', '--unlocker'), ('Powerful Tools Peek', '--peek')]
FM_DIRS = ['~/.local/share/nautilus/scripts', '~/.local/share/nemo/scripts', '~/.config/caja/scripts']


def fm_script_paths():
    out = []
    for d in FM_DIRS:
        d = os.path.expanduser(d)
        for name, flag in FM_SCRIPTS:
            out.append((d, os.path.join(d, name), flag))
    return out


def install_fm_scripts():
    n = 0
    for d, path, flag in fm_script_paths():
        if not os.path.isdir(os.path.dirname(d)):  # that file manager is not installed/used
            continue
        os.makedirs(d, exist_ok=True)
        with open(path, 'w') as f:
            f.write('#!/bin/sh\nexec "%s" %s "$@"\n' % (core.ENTRY, flag))
        os.chmod(path, 0o755)
        n += 1
    return n


def remove_fm_scripts():
    for _d, path, _f in fm_script_paths():
        if os.path.exists(path):
            os.unlink(path)


# Names used by pre-release builds (package "mageshs-powertoys"), migrated once on upgrade.
LEGACY_COMMAND = 'powertoys-linux'
LEGACY_CONFIG = os.path.join(GLib.get_user_config_dir(), 'mageshs-powertoys')
LEGACY_FM_SCRIPTS = ['PowerToys Image Resizer', 'PowerToys PowerRename', 'PowerToys File Locksmith', 'PowerToys Peek']


def migrate_legacy():
    """Carry settings, shortcuts and file-manager scripts over from pre-release builds. Safe to run every start."""
    if os.path.isdir(LEGACY_CONFIG) and not os.path.exists(core.CONFIG_DIR):
        try:
            os.rename(LEGACY_CONFIG, core.CONFIG_DIR)
        except OSError:
            pass
    if core.keybindings_supported():
        titles = dict((flag, title) for _i, title, flag, _a in keyboard.ACTIONS)
        for k in core.list_custom_keybindings():
            parts = k['command'].split()
            if parts and os.path.basename(parts[0]) == LEGACY_COMMAND:
                flag = parts[1] if len(parts) > 1 else ''
                name = 'Powerful Tools: ' + titles.get(flag, flag or 'Open')
                core.set_custom_keybinding(name, ' '.join([core.ENTRY] + parts[1:]), k['binding'], k['path'])
    old = [os.path.join(os.path.expanduser(d), n) for d in FM_DIRS for n in LEGACY_FM_SCRIPTS]
    old = [p for p in old if os.path.exists(p)]
    if old:
        for p in old:
            os.unlink(p)
        install_fm_scripts()


class GeneralPage(core.Page):
    ID = 'general'
    TITLE = 'General'
    ICON = 'preferences-system-symbolic'
    DESC = 'Appearance, file manager integration and information about Powerful Tools.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        theme = core.combo([('system', 'Use system setting'), ('light', 'Light'), ('dark', 'Dark')],
                           app.settings.get('theme', 'system'), self._theme)
        self.add_widget(core.card(core.row('App theme', None, theme), title='Appearance'))
        installed = any(os.path.exists(p) for _d, p, _f in fm_script_paths())
        self.fm_status = core.label('Installed' if installed else 'Not installed', 'pt-dim')
        self.add_widget(core.card(
            core.label('Adds Image Resizer, Bulk Rename, File Unlocker and Peek to the right-click Scripts menu '
                       'of Files (Nautilus), Nemo and Caja.'),
            self.fm_status,
            core.button_row(core.button('Install', self._fm_install, 'list-add-symbolic'),
                            core.button('Remove', self._fm_remove, 'list-remove-symbolic')),
            title='File manager integration'))
        self.add_widget(core.card(
            core.label('%s %s' % (core.APP_NAME, core.VERSION), 'pt-heading'),
            core.label('Desktop: %s · Display: %s' % (core.desktop_name(),
                                                      'Wayland' if core.is_wayland() else 'X11')),
            core.label('Free and open-source software (MIT License). Source code, updates and bug reports: '
                       'github.com/maggimagesh/powerful-tools', 'pt-dim', selectable=True),
            core.label('Settings: %s' % core.CONFIG_DIR, 'pt-dim pt-mono', selectable=True), title='About'))

    def _theme(self, v):
        self.app.settings.set('theme', v)
        self.app.apply_theme()

    def _fm_install(self):
        try:
            n = install_fm_scripts()
        except OSError as e:
            self.toast('Could not install: %s' % e, error=True)
            return
        if n:
            self.fm_status.set_text('Installed')
            self.toast('Added to the file manager: right-click files → Scripts')
        else:
            self.toast('No supported file manager found (Nautilus, Nemo or Caja)', error=True)

    def _fm_remove(self):
        remove_fm_scripts()
        self.fm_status.set_text('Not installed')
        self.toast('File manager scripts removed')


PAGES = [awake.AwakePage, colorpicker.ColorPickerPage, textextractor.TextExtractorPage, launcher.LauncherPage,
         bulkrename.BulkRenamePage, imageresizer.ImageResizerPage, fileunlocker.FileUnlockerPage,
         peek.PeekPage, screenruler.ScreenRulerPage, alwaysontop.AlwaysOnTopPage, advancedpaste.AdvancedPastePage,
         keyboard.KeyboardPage, shortcutguide.ShortcutGuidePage, hosts.HostsPage, envvars.EnvVarsPage,
         templates.TemplatesPage, GeneralPage]


class DashboardPage(core.Page):
    ID = 'dashboard'
    TITLE = 'Dashboard'
    ICON = 'user-home-symbolic'
    DESC = 'A set of utilities to tune your Linux desktop and work faster.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=4,
                         min_children_per_line=1)
        fb.set_row_spacing(12)
        fb.set_column_spacing(12)
        for cls in PAGES:
            if cls.ID == 'general':
                continue
            head = Gtk.Box(spacing=8)
            img = Gtk.Image.new_from_icon_name(cls.ICON, Gtk.IconSize.LARGE_TOOLBAR)
            head.pack_start(img, False, False, 0)
            head.pack_start(core.label(cls.TITLE, 'pt-heading'), True, True, 0)
            desc = core.label(cls.DESC, 'pt-dim')
            desc.set_lines(4)
            desc.set_ellipsize(3)  # Pango END
            desc.set_max_width_chars(28)
            desc.set_valign(Gtk.Align.START)
            c = core.card(head, desc, spacing=6)
            c.set_size_request(200, -1)
            ev = Gtk.Button()
            ev.set_relief(Gtk.ReliefStyle.NONE)
            ev.add(c)
            ev.connect('clicked', lambda _b, pid=cls.ID: app.window.show_page(pid))
            fb.add(ev)
        self.add_widget(fb)


class MainWindow(Gtk.ApplicationWindow):
    NARROW = 760

    def __init__(self, app):
        Gtk.ApplicationWindow.__init__(self, application=app, title=core.APP_NAME)
        self.app = app
        self.set_icon_name('powerful-tools')
        disp = Gdk.Display.get_default()
        mon = disp.get_primary_monitor() or disp.get_monitor(0)
        wa = mon.get_workarea()
        self.set_default_size(min(1180, max(360, int(wa.width * 0.85))), min(820, max(480, int(wa.height * 0.85))))
        self.set_size_request(340, 400)
        self.header = Gtk.HeaderBar(show_close_button=True, title=core.APP_NAME)
        self.back = core.button('', self.show_list, 'go-previous-symbolic', tooltip='Back')
        self.back.set_no_show_all(True)
        self.header.pack_start(self.back)
        self.set_titlebar(self.header)

        self.pages = {}
        self.page_classes = dict((c.ID, c) for c in [DashboardPage] + PAGES)
        self.order = [DashboardPage] + PAGES
        self.sidebar = Gtk.ListBox()
        self.sidebar.get_style_context().add_class('pt-sidebar')
        for cls in self.order:
            r = Gtk.ListBoxRow()
            r.page_id = cls.ID
            b = Gtk.Box(spacing=10)
            b.pack_start(Gtk.Image.new_from_icon_name(cls.ICON, Gtk.IconSize.MENU), False, False, 0)
            b.pack_start(core.label(cls.TITLE, wrap=False), True, True, 0)
            r.add(b)
            self.sidebar.add(r)
        self.sidebar.connect('row-activated', lambda lb, r: self.show_page(r.page_id))
        self.side_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.side_scroll.add(self.sidebar)
        self.side_scroll.set_size_request(230, -1)
        self.sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, hexpand=True)
        box = Gtk.Box()
        box.pack_start(self.side_scroll, False, False, 0)
        box.pack_start(self.sep, False, False, 0)
        box.pack_start(self.stack, True, True, 0)
        self.box = box

        self.toast_label = Gtk.Label()
        self.toast_label.set_line_wrap(True)
        self.toast_label.set_max_width_chars(60)
        tb = Gtk.Box(spacing=8)
        tb.get_style_context().add_class('pt-toast')
        tb.pack_start(self.toast_label, True, True, 0)
        self.toast_box = tb
        self.revealer = Gtk.Revealer(halign=Gtk.Align.CENTER, valign=Gtk.Align.START)
        self.revealer.add(tb)
        overlay = Gtk.Overlay()
        self.footer = core.label('Thank you for Downloading! With Love Magesh\u00a0Kumar\u00a0A\u00a0T\u00a0\u2764', 'pt-footer',
                                 xalign=0.5)
        self.footer.set_justify(Gtk.Justification.CENTER)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main.pack_start(box, True, True, 0)
        main.pack_start(Gtk.Separator(), False, False, 0)
        main.pack_start(self.footer, False, False, 0)  # its own row: never covers page content
        overlay.add(main)
        overlay.add_overlay(self.revealer)
        self.add(overlay)
        self._toast_timer = 0

        self.narrow = False
        self.showing_list = True
        self.current = None
        self.connect('size-allocate', self._on_size)
        self.connect('delete-event', self._on_delete)
        self.show_all()
        self.show_page('dashboard', from_user=False)

    def _on_delete(self, *_):
        if self.app.pins.pinned:  # the app stays running (held) to keep windows on top
            alwaysontop.notify_background(self.app)
        if self.app.awake.active:
            self.hide()
            n = Gio.Notification.new('Awake is still running')
            n.set_body('Open Powerful Tools again to turn it off.')
            self.app.send_notification('awake', n)
            return True
        return False

    def _on_size(self, w, alloc):
        want = alloc.width < self.NARROW
        if want != self.narrow:
            self.narrow = want
            GLib.idle_add(self._apply_layout)

    def _apply_layout(self):
        n = self.narrow
        if n:
            self.side_scroll.set_visible(self.showing_list)
            self.side_scroll.set_hexpand(True)
            self.side_scroll.set_size_request(-1, -1)
            self.box.child_set_property(self.side_scroll, 'expand', True)
            self.sep.hide()
            self.stack.set_visible(not self.showing_list)
            self.back.set_visible(not self.showing_list)
        else:
            self.side_scroll.show()
            self.side_scroll.set_hexpand(False)
            self.side_scroll.set_size_request(230, -1)
            self.box.child_set_property(self.side_scroll, 'expand', False)
            self.sep.show()
            self.stack.show()
            self.back.hide()
        for p in self.pages.values():
            p.set_narrow(n)
        return False

    def show_list(self):
        self.showing_list = True
        self._apply_layout()

    def show_page(self, pid, from_user=True):
        if pid not in self.pages:
            page = self.page_classes[pid](self.app)
            page.set_narrow(self.narrow)
            self.pages[pid] = page
            self.stack.add_named(page, pid)
            page.show_all()
        page = self.pages[pid]
        self.stack.set_visible_child(page)
        self.current = pid
        self.header.set_subtitle(page.TITLE if pid != 'dashboard' else None)
        for r in self.sidebar.get_children():
            if r.page_id == pid:
                self.sidebar.select_row(r)
        if from_user:
            self.showing_list = False
        self._apply_layout()
        page.on_shown()
        return page

    def toast(self, text, error=False):
        self.toast_label.set_text(text)
        ctx = self.toast_box.get_style_context()
        (ctx.add_class if error else ctx.remove_class)('error')
        self.revealer.set_reveal_child(True)
        if self._toast_timer:
            GLib.source_remove(self._toast_timer)
        self._toast_timer = GLib.timeout_add(4500 if error else 3000, self._hide_toast)

    def _hide_toast(self):
        self._toast_timer = 0
        self.revealer.set_reveal_child(False)
        return False


def build_parser():
    p = argparse.ArgumentParser(prog='powerful-tools', description='%s %s' % (core.APP_NAME, core.VERSION))
    g = p.add_mutually_exclusive_group()
    g.add_argument('--run', action='store_true', help='open the Quick Launcher launcher')
    g.add_argument('--pick-color', action='store_true', help='pick a color from the screen')
    g.add_argument('--text-extract', action='store_true', help='capture text from the screen (OCR)')
    g.add_argument('--ruler', action='store_true', help='open the Screen Ruler')
    g.add_argument('--always-on-top', action='store_true', help='toggle always-on-top for the focused window')
    g.add_argument('--advanced-paste', action='store_true', help='open Advanced Paste')
    g.add_argument('--shortcut-guide', action='store_true', help='open the Shortcut Guide')
    g.add_argument('--peek', action='store_true', help='preview FILES')
    g.add_argument('--rename', action='store_true', help='bulk rename FILES')
    g.add_argument('--resize', action='store_true', help='resize image FILES')
    g.add_argument('--unlocker', action='store_true', help='show processes using FILES')
    g.add_argument('--page', choices=sorted(c.ID for c in [DashboardPage] + PAGES), help='open a tool page')
    p.add_argument('--version', action='version', version='%s %s' % (core.APP_NAME, core.VERSION))
    p.add_argument('files', nargs='*', help='files for --peek/--rename/--resize/--unlocker')
    return p


class Application(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, application_id=core.APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        migrate_legacy()  # before loading settings, which may be moved from the old location
        self.settings = core.Settings()
        self.window = None
        self.awake = awake.AwakeController(self)
        self.pins = alwaysontop.PinKeeper(self)
        self.connect('shutdown', lambda *_: self.awake.stop(notify=False))

    def do_startup(self):
        Gtk.Application.do_startup(self)
        prov = Gtk.CssProvider()
        prov.load_from_data(core.CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.apply_theme()
        Gtk.IconTheme.get_default().append_search_path(os.path.join(os.path.dirname(__file__), 'icons'))

    def apply_theme(self):
        s = Gtk.Settings.get_default()
        if not hasattr(self, '_default_dark'):
            self._default_dark = s.get_property('gtk-application-prefer-dark-theme')
        t = self.settings.get('theme', 'system')
        s.set_property('gtk-application-prefer-dark-theme', self._default_dark if t == 'system' else t == 'dark')

    def main_window(self, present=True):
        if self.window is None:
            self.window = MainWindow(self)
            self.window.connect('destroy', self._window_gone)
        if present:
            self.window.present()
        return self.window

    def _window_gone(self, *_):
        self.window = None

    def open_page(self, pid):
        return self.main_window().show_page(pid)

    def do_activate(self):
        self.main_window()

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        cwd = cmdline.get_cwd() or os.getcwd()
        try:
            ns = build_parser().parse_args(args)
        except SystemExit as e:  # --help / --version / bad args print and exit
            return int(e.code or 0)
        files = [os.path.normpath(os.path.join(cwd, f)) for f in ns.files]
        files = [f for f in files if os.path.lexists(f)]
        self.handle(ns, files)
        return 0

    def handle(self, ns, files):
        if ns.run:
            launcher.LauncherWindow(self).present_run()
        elif ns.pick_color:
            self.open_page('colorpicker').pick()
        elif ns.text_extract:
            self.open_page('textextractor').capture()
        elif ns.ruler:
            self.open_page('screenruler').launch()
        elif ns.always_on_top:
            if alwaysontop.supported():
                self.pins.toggle()
            else:
                self.open_page('alwaysontop')
        elif ns.advanced_paste:
            self.open_page('advancedpaste')
        elif ns.shortcut_guide:
            self.open_page('shortcutguide')
        elif ns.peek and files:
            peek.PeekWindow(self, files).show_all()
        elif ns.rename:
            self.open_page('bulkrename').add_paths(files)
        elif ns.resize:
            self.open_page('imageresizer').add_files(files)
        elif ns.unlocker:
            self.open_page('fileunlocker').add_paths(files)
        elif ns.page:
            self.open_page(ns.page)
        else:
            self.main_window()



def main(argv=None, entry=None):
    argv = list(sys.argv if argv is None else argv)
    if entry:
        core.ENTRY = entry
    build_parser().parse_args(argv[1:])  # --help, --version and bad arguments are handled right here
    GLib.set_application_name(core.APP_NAME)
    GLib.set_prgname('powerful-tools')
    return Application().run(argv)
