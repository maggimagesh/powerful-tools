# Pin GI versions before any submodule imports gi.repository (GTK 4 may also be installed).
# logic.py must stay importable without GTK (unit tests, root-only file scan): PyGObject or the
# GTK typelibs may be missing there, so failures are ignored here. core.py pins again and
# raises a clear error if the GUI really cannot start.
try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('GdkPixbuf', '2.0')
    gi.require_version('Pango', '1.0')
except (ImportError, ValueError):
    pass
