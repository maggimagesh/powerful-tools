# Pin GI versions before any submodule imports gi.repository (GTK 4 may also be installed).
# logic.py must stay importable without GTK (unit tests, root-only file scan), hence the guard.
try:
    import gi
except ImportError:
    gi = None

if gi is not None:
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkPixbuf', '2.0')
    gi.require_version('Pango', '1.0')
