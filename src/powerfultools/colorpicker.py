from gi.repository import Gdk, Gtk

from . import core, logic

ZOOM_PIX = 11   # sampled pixels per side
ZOOM_CELL = 11  # screen size of each sampled pixel


def _paint(widget, cr, rgb):
    cr.set_source_rgb(*[v / 255.0 for v in rgb])
    cr.paint()
    return False


class PickerOverlay(core.ScreenOverlay):
    def draw_over(self, cr):
        a = self.area.get_allocation()
        core.draw_label(cr, 'Click to pick a color  ·  Arrow keys move 1 px  ·  Esc to cancel',
                        a.width / 2 - 220, 20, a.width, a.height)
        if self.mx < 0:
            return
        px, py = self.to_src(self.mx, self.my)
        size = ZOOM_PIX * ZOOM_CELL
        bx = self.mx + 24 if self.mx + 24 + size < a.width else self.mx - 24 - size
        by = self.my + 24 if self.my + 24 + size + 30 < a.height else self.my - 24 - size - 30
        half = ZOOM_PIX // 2
        for j in range(ZOOM_PIX):
            for i in range(ZOOM_PIX):
                sx, sy = px - half + i, py - half + j
                if 0 <= sx < self.sw and 0 <= sy < self.sh:
                    r, g, b = self.pixel(sx, sy)
                    cr.set_source_rgb(r / 255.0, g / 255.0, b / 255.0)
                else:
                    cr.set_source_rgb(0.2, 0.2, 0.2)
                cr.rectangle(bx + i * ZOOM_CELL, by + j * ZOOM_CELL, ZOOM_CELL, ZOOM_CELL)
                cr.fill()
        cr.set_line_width(2)
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(bx + half * ZOOM_CELL, by + half * ZOOM_CELL, ZOOM_CELL, ZOOM_CELL)
        cr.stroke()
        cr.set_source_rgb(0, 0, 0)
        cr.rectangle(bx, by, size, size)
        cr.stroke()
        r, g, b = self.pixel(px, py)
        core.draw_label(cr, logic.rgb_to_hex(r, g, b), bx, by + size + 4, a.width, a.height)

    def on_press(self, widget, ev):
        if ev.button == 1:
            self.finish(self.pixel(*self.to_src(ev.x, ev.y)))
        elif ev.button == 3:
            self.finish(None)
        return True

    def on_key(self, ev):
        sx, sy = self.scale()
        moves = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0), Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if ev.keyval in moves and self.mx >= 0:
            dx, dy = moves[ev.keyval]
            self.mx = min(self.area.get_allocated_width() - 1, max(0, self.mx + dx * sx))
            self.my = min(self.area.get_allocated_height() - 1, max(0, self.my + dy * sy))
            self.area.queue_draw()
            return True
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space) and self.mx >= 0:
            self.finish(self.pixel(*self.to_src(self.mx, self.my)))
            return True
        return False


class ColorPickerPage(core.Page):
    ID = 'colorpicker'
    TITLE = 'Color Picker'
    ICON = 'applications-graphics-symbolic'
    DESC = 'Pick a color from anywhere on screen, then copy it as HEX, RGB, HSL, HSV, CMYK and more.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        s = app.settings
        self.rgb = tuple(s.get('color_current', [0, 120, 215]))
        self.add_widget(core.button_row(
            core.button('Pick color from screen', self.pick, 'color-select-symbolic', suggested=True),
            core.button('Choose with color wheel', self.choose_dialog, 'preferences-color-symbolic')))
        self.swatch = Gtk.DrawingArea()
        self.swatch.set_size_request(-1, 64)
        self.swatch.connect('draw', self._draw_swatch)
        self.formats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_widget(core.card(self.swatch, self.formats, title='Selected color'))
        self.copy_fmt = core.combo([(n, n) for n, _ in logic.color_formats(0, 0, 0)],
                                   s.get('color_copy_format', 'HEX'),
                                   lambda v: s.set('color_copy_format', v))
        self.add_widget(core.card(core.row('Copy automatically after picking', 'Format copied to the clipboard.',
                                           self.copy_fmt)))
        self.history = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=30)
        self.history.set_row_spacing(6)
        self.history.set_column_spacing(6)
        self.add_widget(core.card(self.history, core.button_row(core.button('Clear history', self.clear_history)),
                                  title='History'))
        self._render()

    def _draw_swatch(self, w, cr):
        r, g, b = self.rgb
        cr.set_source_rgb(r / 255.0, g / 255.0, b / 255.0)
        a = w.get_allocation()
        cr.rectangle(0, 0, a.width, a.height)
        cr.fill()

    def _render(self):
        for c in self.formats.get_children():
            c.destroy()
        for name, text in logic.color_formats(*self.rgb):
            box = Gtk.Box(spacing=8)
            n = core.label(name, 'pt-dim', wrap=False)
            n.set_width_chars(8)
            box.pack_start(n, False, False, 0)
            box.pack_start(core.label(text, 'pt-mono', selectable=True), True, True, 0)
            box.pack_end(core.button('', lambda t=text: self.copy(t), 'edit-copy-symbolic', tooltip='Copy ' + name),
                         False, False, 0)
            self.formats.pack_start(box, False, False, 0)
        self.formats.show_all()
        self.swatch.queue_draw()
        for c in self.history.get_children():
            c.destroy()
        for hx in self.app.settings.get('color_history', []):
            try:
                rgb = logic.hex_to_rgb(hx)
            except ValueError:
                continue
            b = Gtk.Button()
            b.set_tooltip_text(hx)
            da = Gtk.DrawingArea()
            da.set_size_request(28, 28)
            da.connect('draw', _paint, rgb)
            b.add(da)
            b.connect('clicked', lambda _b, c=rgb: self.set_color(c, record=False))
            self.history.add(b)
        self.history.show_all()

    def copy(self, text):
        core.copy_text(text)
        self.toast('Copied %s' % text)

    def set_color(self, rgb, record=True):
        self.rgb = tuple(int(v) for v in rgb)
        s = self.app.settings
        s.data['color_current'] = list(self.rgb)
        if record:
            hx = logic.rgb_to_hex(*self.rgb)
            hist = [h for h in s.get('color_history', []) if h != hx]
            s.data['color_history'] = ([hx] + hist)[:30]
        s.save()
        self._render()

    def clear_history(self):
        self.app.settings.set('color_history', [])
        self._render()

    def choose_dialog(self):
        dlg = Gtk.ColorChooserDialog(title='Choose a color', transient_for=self.window)
        c = Gdk.RGBA()
        c.parse(logic.rgb_to_hex(*self.rgb))
        dlg.set_rgba(c)
        if dlg.run() == Gtk.ResponseType.OK:
            v = dlg.get_rgba()
            self.set_color((round(v.red * 255), round(v.green * 255), round(v.blue * 255)))
        dlg.destroy()

    def pick(self):
        win = self.window

        def got(pb, err):
            if pb is None:
                if win:
                    win.present()
                self.toast(err or 'Screen capture failed', error=True)
                return
            PickerOverlay(pb, done, 'Color Picker').present_overlay()

        def done(rgb):
            if win:
                win.present()
            if rgb is None:
                return
            self.set_color(rgb)
            fmt = self.app.settings.get('color_copy_format', 'HEX')
            text = dict(logic.color_formats(*self.rgb)).get(fmt)
            if text:
                self.copy(text)
        core.capture_screen(got, [win])
