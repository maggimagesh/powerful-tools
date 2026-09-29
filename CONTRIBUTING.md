# Contributing to Powerful Tools

Thanks for helping! Bug reports, ideas and pull requests are all welcome.

## Reporting a bug
Open an [issue](https://github.com/maggimagesh/powerful-tools/issues) and include your distribution and
version, your desktop (GNOME, KDE…), whether you use X11 or Wayland (`echo $XDG_SESSION_TYPE`), and the
steps that show the problem.

## Project layout

```text
bin/powerful-tools        launcher installed to /usr/bin
src/powerfultools/        the application (one module per tool)
  logic.py                pure, GUI-free logic: unit-tested, Python 3.6 compatible
  core.py                 shared GTK helpers: settings, screen capture, overlays, widgets
  app.py                  main window, dashboard, command line
data/                     desktop entry, icon, man page
packaging/                Debian control files
tests/                    unit, GUI and container tests
build.sh                  builds dist/powerful_tools_<version>.deb
```

## Guidelines
- **Keep it compatible.** The app must run on Ubuntu 18.04: Python 3.6 and GTK 3.22. Avoid newer
  Python syntax (walrus operator, positional-only parameters, `str.removeprefix`, `capture_output=`…)
  and GTK 4 APIs.
- **No new runtime dependencies** unless they're packaged in Ubuntu 18.04 or newer and have an
  open-source license compatible with MIT.
- **Put logic in `logic.py`** where possible, with a test in `tests/test_logic.py`.
- **Test before sending a pull request:**

  ```bash
  python3 tests/test_logic.py
  ./build.sh && tests/docker_test.sh 18.04 && tests/docker_test.sh 24.04
  ```
- Don't use other products' names, logos or artwork. Keep all assets original.

By contributing you agree that your contribution is released under the project's [MIT License](LICENSE).
