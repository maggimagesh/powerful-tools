import os
import threading

from gi.repository import GdkPixbuf, GLib, Gtk

from . import core, logic

PRESETS = [('small', 'Small', 854, 480), ('medium', 'Medium', 1366, 768), ('large', 'Large', 1920, 1080),
           ('phone', 'Phone', 320, 568), ('custom', 'Custom', 1024, 768)]
SAVERS = {'.jpg': 'jpeg', '.jpeg': 'jpeg', '.png': 'png', '.bmp': 'bmp', '.tif': 'tiff', '.tiff': 'tiff'}
IMAGE_MIMES = ['image/png', 'image/jpeg', 'image/bmp', 'image/tiff', 'image/gif', 'image/webp', 'image/svg+xml',
               'image/x-icon']


def resize_file(path, opts):
    """Resize one image according to opts. Returns the output path. Raises on error."""
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    pb = pb.apply_embedded_orientation() or pb
    sw, sh = pb.get_width(), pb.get_height()
    nw, nh, fw, fh = logic.compute_size(sw, sh, opts['w'], opts['h'], opts['mode'], opts['unit'],
                                        opts['shrink_only'])
    out = pb.scale_simple(nw, nh, GdkPixbuf.InterpType.HYPER) if (nw, nh) != (sw, sh) else pb
    if (fw, fh) != (nw, nh):  # fill mode: centre crop
        out = out.new_subpixbuf((nw - fw) // 2, (nh - fh) // 2, fw, fh).copy()
    ext = os.path.splitext(path)[1].lower()
    fmt = opts['format']
    if fmt == 'keep':
        new_ext = ext if ext in SAVERS else '.png'
    else:
        new_ext = {'png': '.png', 'jpeg': '.jpg'}[fmt]
    saver = SAVERS[new_ext]
    if saver == 'jpeg' and out.get_has_alpha():
        flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, out.get_width(), out.get_height())
        flat.fill(0xffffffff)
        out.composite(flat, 0, 0, out.get_width(), out.get_height(), 0, 0, 1, 1,
                      GdkPixbuf.InterpType.NEAREST, 255)
        out = flat
    if opts['overwrite'] and new_ext == ext:
        dest = path
    else:
        dest = logic.output_path(path, opts['size_name'], opts['pattern'], new_ext)
    keys, vals = ([], [])
    if saver == 'jpeg':
        keys, vals = ['quality'], [str(int(opts['quality']))]
    tmp = dest + '.pt-tmp'
    try:
        out.savev(tmp, saver, keys, vals)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


class ImageResizerPage(core.Page):
    ID = 'imageresizer'
    TITLE = 'Image Resizer'
    ICON = 'image-x-generic-symbolic'
    DESC = 'Resize one or many images at once. Drop images here or add them with the button.'

    def __init__(self, app):
        core.Page.__init__(self, app)
        s = app.settings
        self.files = []
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.placeholder = core.label('No images yet. Drag and drop images here.', 'pt-dim', xalign=0.5)
        self.placeholder.set_margin_top(20)
        self.placeholder.set_margin_bottom(20)
        self.placeholder.show()
        self.list.set_placeholder(self.placeholder)
        self.add_widget(core.card(
            core.button_row(core.button('Add images', self.add_dialog, 'list-add-symbolic'),
                            core.button('Clear', self.clear, 'edit-clear-symbolic')),
            core.scrolled(self.list, 120), title='Images'))
        core.enable_file_drop(self, self.add_files)

        self.preset = core.combo([(p[0], '%s (%d × %d)' % (p[1], p[2], p[3]) if p[0] != 'custom' else 'Custom')
                                  for p in PRESETS], s.get('resize_preset', 'medium'), self._preset_changed)
        self.w = core.spin(1, 20000, s.get('resize_w', 1024))
        self.h = core.spin(0, 20000, s.get('resize_h', 768))
        self.unit = core.combo([('px', 'Pixels'), ('percent', 'Percent')], s.get('resize_unit', 'px'))
        self.mode = core.combo([('fit', 'Fit (keep aspect ratio)'), ('fill', 'Fill (crop to size)'),
                                ('stretch', 'Stretch')], s.get('resize_mode', 'fit'))
        dims = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6)
        for wdg in (core.label('Width', xalign=1), self.w, core.label('Height', xalign=1), self.h, self.unit):
            dims.add(wdg)
        self.dims = dims
        self.add_widget(core.card(core.row('Size', None, self.preset), dims,
                                  core.row('Resize mode', None, self.mode), title='Size'))
        self.shrink = Gtk.Switch(active=s.get('resize_shrink', False))
        self.overwrite = Gtk.Switch(active=s.get('resize_overwrite', False))
        self.pattern = Gtk.Entry(text=s.get('resize_pattern', '%1 (%2)'))
        self.pattern.set_width_chars(10)
        self.format = core.combo([('keep', 'Same as original'), ('png', 'PNG'), ('jpeg', 'JPEG')],
                                 s.get('resize_format', 'keep'))
        self.quality = core.spin(1, 100, s.get('resize_quality', 90))
        self.add_widget(core.card(
            core.row('Make pictures smaller but not larger', None, self.shrink),
            core.row('Overwrite original files', 'Otherwise a new file is created next to each image.',
                     self.overwrite),
            core.row('File name', '%1 = original name, %2 = size name', self.pattern),
            core.row('Output format', None, self.format),
            core.row('JPEG quality', None, self.quality), title='Options'))
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_no_show_all(True)
        self.go = core.button('Resize', self.resize, 'media-playback-start-symbolic', suggested=True)
        self.add_widget(core.button_row(self.go))
        self.add_widget(self.progress)
        self._preset_changed(self.preset.get_active_id())

    def _preset_changed(self, pid):
        custom = pid == 'custom'
        self.dims.set_sensitive(custom)
        if not custom:
            for p in PRESETS:
                if p[0] == pid:
                    self.w.set_value(p[2])
                    self.h.set_value(p[3])
                    self.unit.set_active_id('px')

    def add_dialog(self):
        self.add_files(core.choose_files(self.window, 'Add images', mime_filter=('Images', IMAGE_MIMES)))

    def add_files(self, paths):
        added = 0
        for p in paths:
            if os.path.isdir(p):
                subs = sorted(os.path.join(p, n) for n in os.listdir(p))
                self.add_files([x for x in subs if os.path.isfile(x)])
                continue
            info = GdkPixbuf.Pixbuf.get_file_info(p)
            if not info or not info[0] or p in self.files:
                continue
            self.files.append(p)
            added += 1
            r = Gtk.Box(spacing=8)
            r.set_border_width(6)
            r.pack_start(Gtk.Image.new_from_icon_name('image-x-generic-symbolic', Gtk.IconSize.BUTTON),
                         False, False, 0)
            r.pack_start(core.label(os.path.basename(p)), True, True, 0)
            r.pack_start(core.label('%d × %d' % (info[1], info[2]), 'pt-dim', wrap=False), False, False, 0)
            self.list.add(r)
        self.list.show_all()
        if paths and not added:
            self.toast('No new supported images were added', error=True)

    def clear(self):
        self.files = []
        for c in self.list.get_children():
            c.destroy()

    def _opts(self):
        pid = self.preset.get_active_id()
        name = [p[1] for p in PRESETS if p[0] == pid][0]
        if pid == 'custom':
            name = '%dx%d' % (self.w.get_value(), self.h.get_value())
        o = {'w': self.w.get_value(), 'h': self.h.get_value(), 'unit': self.unit.get_active_id(),
             'mode': self.mode.get_active_id(), 'shrink_only': self.shrink.get_active(),
             'overwrite': self.overwrite.get_active(), 'pattern': self.pattern.get_text() or '%1 (%2)',
             'format': self.format.get_active_id(), 'quality': self.quality.get_value(), 'size_name': name}
        s = self.app.settings
        s.data.update(resize_preset=pid, resize_w=o['w'], resize_h=o['h'], resize_unit=o['unit'],
                      resize_mode=o['mode'], resize_shrink=o['shrink_only'], resize_overwrite=o['overwrite'],
                      resize_pattern=o['pattern'], resize_format=o['format'], resize_quality=o['quality'])
        s.save()
        return o

    def resize(self):
        if not self.files:
            self.toast('Add some images first', error=True)
            return
        opts = self._opts()
        if opts['overwrite'] and not core.confirm(self.window, 'Overwrite the original images?',
                                                  'This cannot be undone.', 'Overwrite'):
            return
        files = list(self.files)
        self.go.set_sensitive(False)
        self.progress.show()
        self.progress.set_fraction(0)

        def work():
            errors = []
            for i, p in enumerate(files):
                try:
                    resize_file(p, opts)
                except Exception as e:  # report per-file, keep going
                    errors.append('%s: %s' % (os.path.basename(p), getattr(e, 'message', None) or e))
                GLib.idle_add(self.progress.set_fraction, (i + 1) / float(len(files)))
            GLib.idle_add(done, errors)

        def done(errors):
            self.go.set_sensitive(True)
            self.progress.hide()
            ok = len(files) - len(errors)
            if errors:
                core.message(self.window, 'Resized %d of %d images' % (ok, len(files)), '\n'.join(errors[:10]),
                             error=True)
            else:
                self.toast('Resized %d image%s' % (ok, '' if ok == 1 else 's'))
            return False
        threading.Thread(target=work, daemon=True).start()
