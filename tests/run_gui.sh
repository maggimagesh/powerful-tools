#!/bin/sh
# Run the GUI test in a clean environment with its own X server and D-Bus session.
# Usage: tests/run_gui.sh [screenshot-dir]
cd "$(dirname "$0")/.."
exec env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="$HOME" LANG=C.UTF-8 PT_SHOTS="${1:-/tmp/powerful-tools-shots}" \
    PT_SRC="${PT_SRC:-$PWD/src}" PT_HANG_SECS="${PT_HANG_SECS:-600}" \
    xvfb-run -a -s '-screen 0 3840x2160x24' dbus-run-session -- python3 -u tests/test_gui.py
