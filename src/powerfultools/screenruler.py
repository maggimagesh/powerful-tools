from gi.repository import Gdk, Gtk

from . import core, logic

MODES = ['spacing', 'horizontal', 'vertical', 'bounds']


class RulerOverlay(core.ScreenOverlay):
    def __init__(self, pixbuf, on_done, tolerance=30):
        core.ScreenOverlay.__init__(self, pixbuf, on_done, 'Screen Ruler')
        self.mode = 'spacing'
        self.tol = tolerance
        self.start = None
        self.flash = ''
        self.measure = None  # (text, lines in src px)

    def compute(self):
        if self.mx < 0:
            return None
        px, py = self.to_src(self.mx, self.my)
        if self.mode == 'bounds':
            if not self.start:
                return None
            (x0, y0) = self.start
            x1, y1 = px, py
            w, h = abs(x1 - x0) + 1, abs(y1 - y0) + 1
            return '%d × %d' % (w, h), [('rect', min(x0, x1), min(y0, y1), w, h)]
        args = (self.pixels, self.rowstride, self.nch, self.sw, self.sh, px, py)
        lines, parts = [], []
        if self.mode in ('spacing', 'horizontal'):
            l = logic.scan_edge(*(args + (-1, 0, self.tol)))
            r = logic.scan_edge(*(args + (1, 0, self.tol)))
            lines.append(('h', px - l, py, px + r, py))
            parts.append(l + r + 1)
        if self.mode in ('spacing', 'vertical'):
            u = logic.scan_edge(*(args + (0, -1, self.tol)))
            d = logic.scan_edge(*(args + (0, 1, self.tol)))
            lines.append(('v', px, py - u, px, py + d))
            parts.append(u + d + 1)
        return ' × '.join(str(p) for p in parts), lines

    def draw_over(self, cr):
        a = self.area.get_allocation()
        core.draw_label(cr, '1 Spacing  2 Horizontal  3 Vertical  4 Bounds (drag)  ·  Click copies  ·  Esc exits'
                        '  ·  Mode: %s' % self.mode.title(), a.width / 2 - 330, 20, a.width, a.height)
        m = self.compute()
        self.measure = m
        if not m:
            return
        text, shapes = m
        sx, sy = self.scale()
        cr.set_line_width(2)
        for s in shapes:
            if s[0] == 'rect':
                x, y = self.to_widget(s[1], s[2])
                cr.set_source_rgba(0.1, 0.5, 1, 0.25)
                cr.rectangle(x, y, s[3] * sx, s[4] * sy)
                cr.fill_preserve()
                cr.set_source_rgb(0.1, 0.5, 1)
                cr.stroke()
            else:
                x0, y0 = self.to_widget(s[1] + 0.5, s[2] + 0.5)
                x1, y1 = self.to_widget(s[3] + 0.5, s[4] + 0.5)
                cr.set_source_rgb(1, 0.2, 0.4)
                cr.move_to(x0, y0)
                cr.line_to(x1, y1)
                cr.stroke()
                for (ex, ey) in ((x0, y0), (x1, y1)):  # end caps
                    if s[0] == 'h':
                        cr.move_to(ex, ey - 6)
                        cr.line_to(ex, ey + 6)
                    else:
                        cr.move_to(ex - 6, ey)
                        cr.line_to(ex + 6, ey)
                    cr.stroke()
        core.draw_label(cr, text + ('   ' + self.flash if self.flash else ''), self.mx + 16, self.my + 16,
                        a.width, a.height)

    def on_press(self, widget, ev):
        if ev.button == 3:
            self.finish(None)
        elif ev.button == 1:
            self.mx, self.my = ev.x, ev.y
            if self.mode == 'bounds':
                self.start = self.to_src(ev.x, ev.y)
            else:
                self._copy()
        return True

    def on_release(self, widget, ev):
        if ev.button == 1 and self.mode == 'bounds' and self.start:
            self._copy()
        return True

    def _copy(self):
        m = self.compute()
        if m:
            core.copy_text(m[0])
            self.flash = '(copied)'
            self.area.queue_draw()

    def on_key(self, ev):
        keys = {Gdk.KEY_1: 0, Gdk.KEY_2: 1, Gdk.KEY_3: 2, Gdk.KEY_4: 3,
                Gdk.KEY_KP_1: 0, Gdk.KEY_KP_2: 1, Gdk.KEY_KP_3: 2, Gdk.KEY_KP_4: 3}
        if ev.keyval in keys:
            self.mode = MODES[keys[ev.keyval]]
            self.start = None
            self.flash = ''
            self.area.queue_draw()
            return True
        return False

    def on_motion(self, ev):
        self.flash = ''


class ScreenRulerPage(core.Page):
    ID = 'screenruler'
    TITLE = 'Screen Ruler'
    ICON = 'zoom-fit-best-symbolic'
    DESC = 'Measure distances on screen in pixels, with automatic edge detection.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        self.add_widget(core.button_row(core.button('Launch Screen Ruler', self.launch, 'zoom-fit-best-symbolic',
                                                    suggested=True)))
        self.tol = core.spin(0, 255, app.settings.get('ruler_tolerance', 30),
                             on_change=lambda v: app.settings.set('ruler_tolerance', int(v)))
        self.add_widget(core.card(core.row('Edge detection tolerance',
                                           'How different a pixel must be to count as an edge (0–255).', self.tol)))
        tips = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for k, d in (('1  Spacing', 'Measure to the nearest edges horizontally and vertically'),
                     ('2  Horizontal', 'Only horizontal spacing'), ('3  Vertical', 'Only vertical spacing'),
                     ('4  Bounds', 'Drag a rectangle'), ('Click', 'Copy the measurement'), ('Esc', 'Exit')):
            tips.pack_start(core.row(k, d, None), False, False, 0)
        self.add_widget(core.card(tips, title='Controls'))

    def launch(self):
        win = self.window

        def got(pb, err):
            if pb is None:
                if win:
                    win.present()
                self.toast(err or 'Screen capture failed', error=True)
                return
            RulerOverlay(pb, lambda r: win.present() if win else None,
                         int(self.tol.get_value())).present_overlay()
        core.capture_screen(got, [win])
