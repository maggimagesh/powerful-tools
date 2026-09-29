import os
import shutil

from gi.repository import GLib, Gtk

from . import core

QUICK = [('Text document.txt', ''), ('Markdown document.md', '# Title\n\n'),
         ('Web page.html', '<!DOCTYPE html>\n<html>\n<head>\n  <meta charset="utf-8">\n  <title>Untitled</title>\n'
                           '</head>\n<body>\n\n</body>\n</html>\n'),
         ('Python script.py', '#!/usr/bin/env python3\n\n\ndef main():\n    pass\n\n\nif __name__ == "__main__":\n'
                              '    main()\n'),
         ('Shell script.sh', '#!/bin/sh\nset -eu\n\n'),
         ('CSV spreadsheet.csv', 'Column A,Column B\n')]


def templates_dir():
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_TEMPLATES)
    home = os.path.expanduser('~')
    if not d or os.path.realpath(d) == os.path.realpath(home):
        return None
    return d


def unique_path(d, name):
    base, ext = os.path.splitext(name)
    p, i = os.path.join(d, name), 2
    while os.path.lexists(p):
        p = os.path.join(d, '%s (%d)%s' % (base, i, ext))
        i += 1
    return p


class TemplatesPage(core.Page):
    ID = 'templates'
    TITLE = 'File Templates'
    ICON = 'document-new-symbolic'
    DESC = ('Create new files and folders from your own templates. Templates appear in the file manager\'s '
            '"New Document" menu (right-click in a folder).')

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.dir_label = core.label('', 'pt-mono', selectable=True)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_widget(core.card(self.dir_label, core.button_row(
            core.button('Open templates folder', self.open_dir, 'folder-open-symbolic'),
            core.button('Add template from file', self.add_from_file, 'list-add-symbolic')),
            title='Templates folder'))
        self.quick = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_widget(core.card(self.list, title='Your templates'))
        buttons = [core.button(n, lambda n=n, c=c: self.add_quick(n, c)) for n, c in QUICK]
        self.add_widget(core.card(core.button_row(*buttons), title='Add a ready-made template'))
        self.refresh()

    def _ensure_dir(self):
        d = templates_dir()
        if d:
            os.makedirs(d, exist_ok=True)
            return d
        d = os.path.join(os.path.expanduser('~'), 'Templates')
        os.makedirs(d, exist_ok=True)
        if shutil.which('xdg-user-dirs-update'):
            core.run(['xdg-user-dirs-update', '--set', 'TEMPLATES', d])
            GLib.reload_user_special_dirs_cache()
        return d

    def refresh(self):
        d = templates_dir()
        self.dir_label.set_text(d or 'Not configured yet. A ~/Templates folder is created when you add one.')
        for c in self.list.get_children():
            c.destroy()
        names = []
        if d and os.path.isdir(d):
            names = sorted(os.listdir(d), key=str.lower)
        if not names:
            self.list.pack_start(core.label('No templates yet.', 'pt-dim'), False, False, 0)
        for n in names:
            full = os.path.join(d, n)
            box = Gtk.Box(spacing=6)
            box.pack_start(core.button('', lambda f=full: self.create_from(f), 'document-new-symbolic',
                                       tooltip='Create a new file from this template in a folder…'), False, False, 0)
            box.pack_start(core.button('', lambda f=full: self.delete(f), 'user-trash-symbolic',
                                       tooltip='Delete template'), False, False, 0)
            self.list.pack_start(core.row(n, 'Folder' if os.path.isdir(full) else None, box), False, False, 0)
        self.list.show_all()

    def open_dir(self):
        core.open_path(self._ensure_dir())
        self.refresh()

    def add_from_file(self):
        for src in core.choose_files(self.window, 'Choose files to use as templates'):
            try:
                dest = unique_path(self._ensure_dir(), os.path.basename(src))
                if os.path.isdir(src):
                    shutil.copytree(src, dest, symlinks=True)
                else:
                    shutil.copy2(src, dest)
            except OSError as e:
                self.toast('Could not add %s: %s' % (os.path.basename(src), e), error=True)
        self.refresh()

    def add_quick(self, name, content):
        try:
            p = unique_path(self._ensure_dir(), name)
            with open(p, 'w') as f:
                f.write(content)
            if p.endswith(('.sh', '.py')):
                os.chmod(p, 0o755)
        except OSError as e:
            self.toast('Could not create template: %s' % e, error=True)
            return
        self.toast('Template "%s" added' % os.path.basename(p))
        self.refresh()

    def create_from(self, template):
        dirs = core.choose_files(self.window, 'Create in folder', folders=True, multiple=False)
        if not dirs:
            return
        try:
            dest = unique_path(dirs[0], os.path.basename(template))
            if os.path.isdir(template):
                shutil.copytree(template, dest, symlinks=True)
            else:
                shutil.copy2(template, dest)
        except OSError as e:
            self.toast('Could not create: %s' % e, error=True)
            return
        self.toast('Created %s' % dest)

    def delete(self, path):
        if not core.confirm(self.window, 'Delete template "%s"?' % os.path.basename(path), None, 'Delete'):
            return
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
        except OSError as e:
            self.toast('Could not delete: %s' % e, error=True)
        self.refresh()
