#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC_DIR="$ROOT_DIR/src"
CONTROL_DIR="$ROOT_DIR/packaging/control"
RELEASE_DIR="$ROOT_DIR/releases"
WORK_DIR="$ROOT_DIR/build"
INIT_FILE="$SRC_DIR/usr/lib/enigma2/python/Plugins/Extensions/E2Doctor/__init__.py"

VERSION=$(sed -n 's/^PLUGIN_VERSION = "\([^"]*\)"/\1/p' "$INIT_FILE" | head -n1)
BUILD=$(sed -n 's/^PLUGIN_BUILD = "\([^"]*\)"/\1/p' "$INIT_FILE" | head -n1)

[ -n "$VERSION" ] || { echo "Nie odczytano PLUGIN_VERSION."; exit 1; }
[ -n "$BUILD" ] || { echo "Nie odczytano PLUGIN_BUILD."; exit 1; }

PACKAGE_NAME="enigma2-plugin-extensions-e2doctor_${VERSION}_all.ipk"
PACKAGE_PATH="$RELEASE_DIR/$PACKAGE_NAME"

rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/control" "$WORK_DIR/data" "$RELEASE_DIR"
cp -a "$SRC_DIR"/. "$WORK_DIR/data"/
cp "$CONTROL_DIR/control" "$WORK_DIR/control/control"
cp "$CONTROL_DIR/postinst" "$WORK_DIR/control/postinst"

python3 - "$WORK_DIR/control/control" "$VERSION" <<'PY'
import pathlib
import re
import sys
path = pathlib.Path(sys.argv[1])
version = sys.argv[2]
text = path.read_text(encoding="utf-8")
text = re.sub(r"^Version:.*$", "Version: %s" % version, text, flags=re.M)
path.write_text(text, encoding="utf-8")
PY

find "$WORK_DIR/data" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$WORK_DIR/data" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

(
    cd "$WORK_DIR/data"
    find usr -type f -print0 | sort -z | xargs -0 md5sum > "$WORK_DIR/control/md5sums"
)

chmod 755 "$WORK_DIR/control/postinst"
chmod 755 "$WORK_DIR/data/usr/bin/e2doctor-report"
chmod 755 "$WORK_DIR/data/usr/lib/enigma2/python/Plugins/Extensions/E2Doctor/plugin.py"

printf '2.0\n' > "$WORK_DIR/debian-binary"
(
    cd "$WORK_DIR/control"
    tar -czf "$WORK_DIR/control.tar.gz" .
)
(
    cd "$WORK_DIR/data"
    tar -czf "$WORK_DIR/data.tar.gz" .
)
(
    cd "$WORK_DIR"
    rm -f "$PACKAGE_PATH"
    ar r "$PACKAGE_PATH" debian-binary control.tar.gz data.tar.gz >/dev/null
)

SHA256=$(sha256sum "$PACKAGE_PATH" | awk '{print $1}')
SIZE=$(du -h "$PACKAGE_PATH" | awk '{print $1}')

python3 - "$ROOT_DIR/update.json" "$VERSION" "$BUILD" "$PACKAGE_NAME" "$SHA256" <<'PY'
import datetime
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
version, build, filename, sha256 = sys.argv[2:]
data = json.loads(path.read_text(encoding="utf-8"))
data["version"] = version
data["build"] = build
data["release_date"] = datetime.date.today().isoformat()
data["download_url"] = "https://raw.githubusercontent.com/OliOli2013/E2-Doctor-Plugin/main/releases/%s" % filename
data["sha256"] = sha256
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

python3 -m py_compile \
    "$SRC_DIR/usr/lib/enigma2/python/Plugins/Extensions/E2Doctor/plugin.py" \
    "$INIT_FILE"
find "$SRC_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +

printf '\nGotowe:\n  %s\n  wersja: %s\n  build: %s\n  rozmiar: %s\n  SHA-256: %s\n' \
    "$PACKAGE_PATH" "$VERSION" "$BUILD" "$SIZE" "$SHA256"
