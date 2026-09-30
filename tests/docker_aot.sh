#!/bin/sh
# Always On Top and Fancy Zones tests against a real X11 window manager (Openbox) inside a container,
# so no test windows appear on the developer's desktop. Usage: tests/docker_aot.sh 24.04
set -u
V="$1"
cd "$(dirname "$0")/.."
DEB="${DEB:-$(ls -t dist/*.deb | head -1)}"
docker run --rm -e DEBIAN_FRONTEND=noninteractive -e DEB="$DEB" -v "$PWD":/w:ro ubuntu:"$V" sh -c '
apt-get update -qq >/dev/null
apt-get install -y -qq /w/$DEB xvfb xauth openbox >/tmp/i.log 2>&1 || { tail -20 /tmp/i.log; exit 1; }
useradd -m tester
runuser -u tester -- env -i PATH=/usr/bin:/bin HOME=/home/tester PT_SRC=/usr/lib/powerful-tools \
  xvfb-run -a -s "-screen 0 1920x1080x24" sh -c "openbox >/dev/null 2>&1 & sleep 2; python3 /w/tests/test_alwaysontop_x11.py; python3 /w/tests/test_fancyzones_x11.py" >/tmp/wm.log 2>&1
grep -E "PASS|FAIL|ALL|SOME|Error|ERROR|Traceback|File " /tmp/wm.log
# both tests must reach their last line: a crash or a failed check fails this script
[ "$(grep -c "^ALL OK" /tmp/wm.log)" = 2 ]
'
