from gi.repository import Gtk

from . import core, logic


class AdvancedPastePage(core.Page):
    ID = 'advancedpaste'
    TITLE = 'Advanced Paste'
    ICON = 'edit-paste-symbolic'
    DESC = ('Transform the text on your clipboard (plain text, JSON, Markdown table, case, Base64…). '
            'The result is put back on the clipboard, ready to paste with Ctrl+V.')

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.src = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.src.set_left_margin(8)
        self.src.set_top_margin(8)
        self.add_widget(core.card(core.scrolled(self.src, 120),
                                  core.button_row(core.button('Read clipboard', self.refresh, 'view-refresh-symbolic')),
                                  title='Clipboard text'))
        buttons = [core.button(label, lambda k=key: self.apply(k)) for key, label, _fn in logic.PASTE_ACTIONS]
        self.add_widget(core.card(core.button_row(*buttons), title='Transform and copy'))
        self.out = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, editable=False)
        self.out.set_left_margin(8)
        self.out.set_top_margin(8)
        self.add_widget(core.card(core.scrolled(self.out, 120), title='Result'))

    def on_shown(self):
        self.refresh()

    def refresh(self):
        text = core.read_clipboard_text()
        self.src.get_buffer().set_text(text or '')

    def apply(self, key):
        b = self.src.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        if not text:
            self.toast('The clipboard has no text', error=True)
            return
        try:
            result = logic.paste_transform(key, text)
        except ValueError as e:
            self.toast(str(e), error=True)
            return
        self.out.get_buffer().set_text(result)
        core.copy_text(result)
        self.toast('Copied. Press Ctrl+V to paste.')
