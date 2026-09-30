#!/bin/sh
# Install the .deb in a clean Ubuntu container and run all tests as an unprivileged user.
# Usage: tests/docker_test.sh 18.04
set -u
V="$1"
cd "$(dirname "$0")/.."
DEB="${DEB:-$(ls -t dist/*.deb | head -1)}"
mkdir -p "${SHOTS_DIR:-/tmp/pt-shots-$V}" && chmod 777 "${SHOTS_DIR:-/tmp/pt-shots-$V}"
docker run --rm -e DEBIAN_FRONTEND=noninteractive -e DEB="$DEB" -v "$PWD":/w:ro -v "${SHOTS_DIR:-/tmp/pt-shots-$V}":/shots ubuntu:"$V" sh -c '
set -e
apt-get update -qq >/dev/null
# the package itself, exactly as a user would install it (with recommends)
apt-get install -y -qq /w/$DEB >/tmp/install.log 2>&1 || { tail -30 /tmp/install.log; exit 1; }
echo "== installed: $(dpkg-query -W -f="\${Package} \${Version} \${Status}" powerful-tools)"
# test-only tools
apt-get install -y -qq xvfb xauth dbus dbus-x11 desktop-file-utils gsettings-desktop-schemas >/dev/null 2>&1
apt-get install -y -qq gnome-settings-daemon-common >/dev/null 2>&1 || apt-get install -y -qq gnome-settings-daemon >/dev/null 2>&1 || true
desktop-file-validate /usr/share/applications/io.github.maggimagesh.PowerfulTools.desktop && echo "== desktop file valid"
set +e
useradd -m tester
cp -r /w/tests /home/tester/tests && chown -R tester /home/tester/tests
E="env -i PATH=/usr/bin:/bin HOME=/home/tester LANG=C.UTF-8 PT_SRC=/usr/lib/powerful-tools PT_SHOTS=/shots"
runuser -u tester -- sh -c "cd /home/tester && powerful-tools --version && \
  PT_SRC=/usr/lib/powerful-tools python3 tests/test_logic.py && \
  $E xvfb-run -a -s \"-screen 0 3840x2160x24\" dbus-run-session -- python3 -u tests/test_gui.py" > /tmp/gui.log 2>&1
rc=$?
# attacks on every tool: each check passes when the attack is refused
runuser -u tester -- sh -c "cd /home/tester && $E xvfb-run -a -s \"-screen 0 1920x1080x24\" python3 -u tests/test_security.py" >> /tmp/gui.log 2>&1 || rc=1
[ $rc -ne 0 ] && ! grep -q "checks," /tmp/gui.log && tail -40 /tmp/gui.log
grep -E "^(PASS|FAIL|[0-9]+ (checks|logic|security)|Powerful Tools)|UNCAUGHT|^(Traceback|AssertionError|  File )" /tmp/gui.log
# any GTK warning/critical from our own process is a failure (a container has no notification service: not ours)
if grep -E "\((python3|test_gui|test_security).*(CRITICAL|WARNING)" /tmp/gui.log | grep -v "unable to send notifications"; then echo "== GTK warnings found"; rc=1; fi
dpkg -r powerful-tools >/dev/null && [ ! -e /usr/lib/powerful-tools ] && echo "== removed cleanly"
exit $rc
'
