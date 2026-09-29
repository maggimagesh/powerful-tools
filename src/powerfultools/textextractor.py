import os
import shutil
import tempfile
import threading

from gi.repository import GdkPixbuf, GLib, Gtk

from . import core


def tesseract_langs():
    if not shutil.which('tesseract'):
        return []
    rc, out, err = core.run(['tesseract', '--list-langs'], timeout=15)
    langs = []
    for line in (out + '\n' + err).splitlines():
        line = line.strip()
        if line and ' ' not in line and ':' not in line and line != 'osd':
            langs.append(line)
    return sorted(set(langs))


def ocr_pixbuf(pb, lang):
    """Run tesseract on a pixbuf. Returns (text, error)."""
    if pb.get_height() < 200:  # small crops read far better upscaled
        f = max(2, int(400 / max(1, pb.get_height())))
        f = min(f, 4)
        pb = pb.scale_simple(pb.get_width() * f, pb.get_height() * f, GdkPixbuf.InterpType.BILINEAR)
    fd, path = tempfile.mkstemp(suffix='.png', prefix='pt-ocr-')
    os.close(fd)
    try:
        pb.savev(path, 'png', [], [])
        rc, out, err = core.run(['tesseract', path, 'stdout', '-l', lang], timeout=120)
    finally:
        os.unlink(path)
    if rc != 0:
        return None, (err.strip().splitlines() or ['tesseract failed'])[-1]
    return out.strip(), None


class TextExtractorPage(core.Page):
    ID = 'textextractor'
    TITLE = 'Text Extractor'
    ICON = 'edit-select-all-symbolic'
    DESC = 'Select any area of the screen and copy the text in it (OCR).'

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.langs = tesseract_langs()
        if not self.langs:
            self.add_widget(core.card(
                core.label('The OCR engine (Tesseract) is not installed.', 'pt-error pt-heading'),
                core.label('Install it with:  sudo apt install tesseract-ocr tesseract-ocr-eng', 'pt-mono',
                           selectable=True),
                title='Setup needed'))
        self.capture_btn = core.button('Capture text from screen', self.capture, 'edit-select-all-symbolic',
                                       suggested=True)
        self.capture_btn.set_sensitive(bool(self.langs))
        self.add_widget(core.button_row(self.capture_btn))
        opts = [(l, l) for l in self.langs] or [('eng', 'eng')]
        want = app.settings.get('ocr_lang', 'eng')
        self.lang = core.combo(opts, want if want in [o[0] for o in opts] else opts[0][0],
                               lambda v: app.settings.set('ocr_lang', v))
        self.add_widget(core.card(core.row('Language', 'Install more with apt: tesseract-ocr-<lang>', self.lang)))
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, editable=True)
        self.view.set_left_margin(8)
        self.view.set_top_margin(8)
        self.spinner = Gtk.Spinner()
        self.add_widget(core.card(core.scrolled(self.view, 180),
                                  core.button_row(core.button('Copy', self.copy, 'edit-copy-symbolic'), self.spinner),
                                  title='Result'))

    def copy(self):
        b = self.view.get_buffer()
        text = b.get_text(b.get_start_iter(), b.get_end_iter(), False)
        if text:
            core.copy_text(text)
            self.toast('Text copied to clipboard')

    def capture(self):
        win = self.window

        def got(pb, err):
            if pb is None:
                if win:
                    win.present()
                self.toast(err or 'Screen capture failed', error=True)
                return
            core.RegionSelectOverlay(pb, selected, 'Text Extractor').present_overlay()

        def selected(crop):
            if win:
                win.present()
            if crop is not None:
                self.recognize(crop)
        core.capture_screen(got, [win])

    def recognize(self, pb):
        self.spinner.start()
        self.capture_btn.set_sensitive(False)
        lang = self.lang.get_active_id() or 'eng'

        def work():
            text, err = ocr_pixbuf(pb, lang)
            GLib.idle_add(done, text, err)

        def done(text, err):
            self.spinner.stop()
            self.capture_btn.set_sensitive(True)
            if err:
                self.toast('OCR failed: ' + err, error=True)
            elif not text:
                self.toast('No text found in the selected area', error=True)
            else:
                self.view.get_buffer().set_text(text)
                core.copy_text(text)
                self.toast('Text copied to clipboard')
            return False
        threading.Thread(target=work, daemon=True).start()
