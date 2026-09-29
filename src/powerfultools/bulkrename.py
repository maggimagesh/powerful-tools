import os

from gi.repository import Gtk, Pango

from . import core, logic

STATUS_TEXT = {'unchanged': '', 'ok': 'Will rename', 'invalid': 'Invalid name', 'duplicate': 'Duplicate name',
               'exists': 'Name already exists', 'error': 'Error'}


class BulkRenamePage(core.Page):
    ID = 'bulkrename'
    TITLE = 'Bulk Rename'
    ICON = 'document-edit-symbolic'
    DESC = ('Bulk rename files and folders with search & replace, regular expressions, text case and numbering. '
            'Use ${n} in the replacement for a counter.')

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.paths = []
        self.last_undo = []
        self.add_widget(core.button_row(
            core.button('Add files', lambda: self.add_paths(core.choose_files(self.window, 'Add files')),
                        'list-add-symbolic'),
            core.button('Add folders', lambda: self.add_paths(core.choose_files(self.window, 'Add folders',
                                                                                 folders=True)),
                        'folder-new-symbolic'),
            core.button('Clear', self.clear, 'edit-clear-symbolic')))
        core.enable_file_drop(self, self.add_paths)

        self.search = Gtk.SearchEntry(placeholder_text='Search for')
        self.replace = Gtk.Entry(placeholder_text='Replace with (use ${n} for a counter)')
        self.regex = Gtk.CheckButton(label='Use regular expressions')
        self.case = Gtk.CheckButton(label='Case sensitive')
        self.all = Gtk.CheckButton(label='Match all occurrences', active=True)
        self.apply_to = core.combo([('name', 'Name only'), ('ext', 'Extension only'), ('both', 'Name and extension')])
        self.textcase = core.combo([('none', 'Keep text case'), ('lower', 'lowercase'), ('upper', 'UPPERCASE'),
                                    ('title', 'Title Case'), ('capitalize', 'Capitalize first letter')])
        self.start = core.spin(0, 1000000, 1)
        self.inc = core.spin(1, 1000, 1)
        self.pad = core.spin(0, 10, 0)
        checks = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3)
        for w in (self.regex, self.case, self.all):
            checks.add(w)
        counter = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6)
        for w in (core.label('Start', xalign=1), self.start, core.label('Step', xalign=1), self.inc,
                  core.label('Padding', xalign=1), self.pad):
            counter.add(w)
        self.add_widget(core.card(self.search, self.replace, checks,
                                  core.row('Apply to', None, self.apply_to),
                                  core.row('Text case', None, self.textcase),
                                  core.label('Counter ${n}', 'pt-heading'), counter, title='Rename rules'))

        self.store = Gtk.ListStore(str, str, str, str)  # original, new, status text, path
        tv = Gtk.TreeView(model=self.store)
        for i, title in enumerate(('Original', 'Renamed', 'Status')):
            cell = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE if i < 2 else Pango.EllipsizeMode.NONE)
            col = Gtk.TreeViewColumn(title, cell, text=i)
            col.set_resizable(True)
            col.set_expand(i < 2)
            col.set_min_width(80)
            tv.append_column(col)
        self.summary = core.label('', 'pt-dim')
        self.add_widget(core.card(core.scrolled(tv, 220), self.summary, title='Preview'))
        self.apply_btn = core.button('Apply', self.apply, 'object-select-symbolic', suggested=True)
        self.undo_btn = core.button('Undo last rename', self.undo, 'edit-undo-symbolic')
        self.undo_btn.set_sensitive(False)
        self.add_widget(core.button_row(self.apply_btn, self.undo_btn))
        for w in (self.search, self.replace):
            w.connect('changed', self.update)
        for w in (self.regex, self.case, self.all):
            w.connect('toggled', self.update)
        for w in (self.apply_to, self.textcase):
            w.connect('changed', self.update)
        for w in (self.start, self.inc, self.pad):
            w.connect('value-changed', self.update)
        self.update()

    def add_paths(self, paths):
        for p in paths:
            p = os.path.abspath(p)
            if os.path.lexists(p) and p not in self.paths:
                self.paths.append(p)
        self.update()

    def clear(self):
        self.paths = []
        self.update()

    def plan(self):
        names = [os.path.basename(p) for p in self.paths]
        new = logic.rename_plan(
            names, self.search.get_text(), self.replace.get_text(),
            start=int(self.start.get_value()), increment=int(self.inc.get_value()), padding=int(self.pad.get_value()),
            use_regex=self.regex.get_active(), case_sensitive=self.case.get_active(),
            match_all=self.all.get_active(), apply_to=self.apply_to.get_active_id(),
            case_mode=self.textcase.get_active_id())
        return new, logic.validate_plan(self.paths, new)

    def update(self, *_):
        self.store.clear()
        try:
            new, status = self.plan()
        except ValueError as e:
            self.summary.set_text(str(e))
            self.apply_btn.set_sensitive(False)
            for p in self.paths:
                self.store.append([os.path.basename(p), '', '', p])
            return
        for p, n, st in zip(self.paths, new, status):
            self.store.append([os.path.basename(p), n if st != 'unchanged' else '', STATUS_TEXT[st], p])
        ok = status.count('ok')
        bad = len([s for s in status if s not in ('ok', 'unchanged')])
        self.summary.set_text('%d items · %d will be renamed%s' % (
            len(self.paths), ok, (' · %d have problems and will be skipped' % bad) if bad else ''))
        self.apply_btn.set_sensitive(ok > 0)

    def apply(self):
        try:
            new, status = self.plan()
        except ValueError as e:
            self.toast(str(e), error=True)
            return
        pairs = [(p, os.path.join(os.path.dirname(p), n)) for p, n, s in zip(self.paths, new, status) if s == 'ok']
        try:
            steps = logic.apply_renames_nested(pairs)
        except OSError as e:
            self.toast('Rename failed, nothing was changed: %s' % e, error=True)
            return
        self.paths = logic.track_paths(self.paths, steps)
        self.last_undo = [(n, o) for o, n in reversed(steps)]
        self.undo_btn.set_sensitive(True)
        self.toast('Renamed %d item%s' % (len(steps), '' if len(steps) == 1 else 's'))
        self.update()

    def undo(self):
        try:
            steps = logic.apply_renames_nested(self.last_undo, deepest_first=False)
        except OSError as e:
            self.toast('Undo failed: %s' % e, error=True)
            return
        self.paths = logic.track_paths(self.paths, steps)
        self.last_undo = []
        self.undo_btn.set_sensitive(False)
        self.toast('Undid %d rename%s' % (len(steps), '' if len(steps) == 1 else 's'))
        self.update()
