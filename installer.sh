#!/bin/sh
set -eu

REPO_RAW="https://raw.githubusercontent.com/OliOli2013/E2-Doctor-Plugin/main"
MANIFEST_URL="$REPO_RAW/update.json"
TMP_MANIFEST="/tmp/e2doctor-update.json"
TMP_IPK="/tmp/e2doctor-latest.ipk"

cleanup() {
    rm -f "$TMP_MANIFEST" "$TMP_IPK"
}
trap cleanup EXIT INT TERM

command -v python3 >/dev/null 2>&1 || {
    echo "BŁĄD: E2 Doctor wymaga systemu Enigma2 z Pythonem 3."
    exit 1
}

command -v opkg >/dev/null 2>&1 || {
    echo "BŁĄD: Nie znaleziono menedżera pakietów OPKG."
    exit 1
}

if command -v wget >/dev/null 2>&1; then
    wget -q -O "$TMP_MANIFEST" "$MANIFEST_URL"
elif command -v curl >/dev/null 2>&1; then
    curl -fsSL "$MANIFEST_URL" -o "$TMP_MANIFEST"
else
    echo "BŁĄD: Nie znaleziono wget ani curl."
    exit 1
fi

python3 - "$TMP_MANIFEST" "$TMP_IPK" <<'PY'
import hashlib
import json
import os
import ssl
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

manifest_path, output_path = sys.argv[1:3]
with open(manifest_path, "r", encoding="utf-8") as handle:
    manifest = json.load(handle)

url = str(manifest.get("download_url", ""))
sha_expected = str(manifest.get("sha256", "")).lower().strip()
version = str(manifest.get("version", "")).strip()
allowed = {"raw.githubusercontent.com", "github.com", "objects.githubusercontent.com"}
parsed = urlparse(url)

if parsed.scheme != "https" or parsed.hostname not in allowed:
    raise SystemExit("BŁĄD: Niedozwolony adres paczki aktualizacji.")
if len(sha_expected) != 64 or any(c not in "0123456789abcdef" for c in sha_expected):
    raise SystemExit("BŁĄD: Nieprawidłowa suma SHA-256 w update.json.")

request = Request(url, headers={"User-Agent": "E2Doctor-Installer/%s" % version})
context = ssl.create_default_context()
with urlopen(request, timeout=30, context=context) as response, open(output_path, "wb") as output:
    digest = hashlib.sha256()
    while True:
        block = response.read(1024 * 256)
        if not block:
            break
        output.write(block)
        digest.update(block)

with open(output_path, "rb") as handle:
    if handle.read(8) != b"!<arch>\n":
        raise SystemExit("BŁĄD: Pobrany plik nie jest prawidłową paczką IPK.")

sha_actual = digest.hexdigest()
if sha_actual != sha_expected:
    os.unlink(output_path)
    raise SystemExit("BŁĄD: Suma SHA-256 pobranej paczki jest niezgodna.")

print("Pobrano i zweryfikowano E2 Doctor %s." % version)
PY

opkg install --force-reinstall "$TMP_IPK"

echo
echo "E2 Doctor został zainstalowany poprawnie."
echo "Wykonaj restart GUI Enigma2."
exit 0
