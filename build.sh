#!/bin/sh
# Build dist/powerful-tools_<version>_all.deb.
# xz compression keeps the package readable by dpkg on Ubuntu 18.04 (it cannot read zstd).
set -eu
umask 022
cd "$(dirname "$0")"
VERSION=$(sed -n "s/^VERSION = '\(.*\)'/\1/p" src/powerfultools/core.py)
R=build/pkg
rm -rf build && mkdir -p $R/DEBIAN $R/usr/bin $R/usr/lib/powerful-tools/powerfultools \
    $R/usr/share/applications $R/usr/share/icons/hicolor/scalable/apps $R/usr/share/doc/powerful-tools \
    $R/usr/share/man/man1 dist
install -m755 bin/powerful-tools $R/usr/bin/
install -m644 src/powerfultools/*.py $R/usr/lib/powerful-tools/powerfultools/
install -m644 data/io.github.maggimagesh.PowerfulTools.desktop $R/usr/share/applications/
install -m644 data/powerful-tools.svg $R/usr/share/icons/hicolor/scalable/apps/
install -m644 packaging/copyright $R/usr/share/doc/powerful-tools/
gzip -9n < data/powerful-tools.1 > $R/usr/share/man/man1/powerful-tools.1.gz
printf 'powerful-tools (%s) stable; urgency=medium\n\n  * Initial release.\n\n -- Magesh Kumar A T <maggimagesh995@gmail.com>  Tue, 29 Sep 2026 12:00:00 +0530\n' "$VERSION" \
    | gzip -9n > $R/usr/share/doc/powerful-tools/changelog.gz
chmod 644 $R/usr/share/man/man1/powerful-tools.1.gz $R/usr/share/doc/powerful-tools/changelog.gz
install -m755 packaging/postinst packaging/prerm $R/DEBIAN/
SIZE=$(du -sk --exclude=DEBIAN $R | cut -f1)
sed -e "s/@SIZE@/$SIZE/" -e "s/@VERSION@/$VERSION/" packaging/control > $R/DEBIAN/control
(cd $R && find usr -type f -exec md5sum {} + > DEBIAN/md5sums)
OUT=dist/powerful-tools_${VERSION}_all.deb
dpkg-deb --root-owner-group -Zxz --build $R "$OUT" >/dev/null
echo "$OUT"
