# -*- coding: utf-8 -*-
from __future__ import absolute_import

import datetime
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback

from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from Components.ScrollLabel import ScrollLabel
from Components.Sources.StaticText import StaticText
from enigma import eListboxPythonMultiContent, gFont, RT_HALIGN_LEFT, RT_VALIGN_CENTER

try:
    from enigma import eDVBDB
except Exception:
    eDVBDB = None

try:
    from . import PLUGIN_VERSION, PLUGIN_AUTHOR, PLUGIN_EMAIL, PLUGIN_BUILD
except Exception:
    PLUGIN_VERSION = "2.3"
    PLUGIN_AUTHOR = "Paweł Pawełek"
    PLUGIN_EMAIL = "aio-iptv@wp.pl"
    PLUGIN_BUILD = "20260711-4"

PLUGIN_PATH = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = "/etc/enigma2/settings"
SOLUTIONS_FILE = os.path.join(PLUGIN_PATH, "data", "solutions.json")

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_ERROR = "ERROR"
STATUS_INFO = "INFO"

TEXTS = {
    "title": "E2 Doctor",
    "subtitle": "Diagnostyka, wyjaśnienia i bezpieczne narzędzia Enigma2",
    "scan": "Skanuj",
    "details": "Odczyt / pomoc",
    "report": "Raport",
    "exit": "Wyjście",
    "menu": "Narzędzia",
    "scanning": "Trwa diagnostyka...",
    "done": "Zakończono: OK {ok} | Informacje {info} | Ostrzeżenia {warn} | Błędy {err}",
    "no_result": "Brak wyników. Uruchom diagnostykę.",
    "report_saved": "Raport zapisano w:\n{path}",
    "report_failed": "Nie udało się utworzyć raportu:\n{error}",
    "tool_title": "Bezpieczne narzędzia",
    "tool_reload": "Przeładuj listę kanałów",
    "tool_lock": "Usuń nieaktywną blokadę OPKG",
    "tool_logs": "Usuń stare crashlogi (pozostaw 3 najnowsze)",
    "tool_oscam": "Uruchom ponownie OSCam",
    "tool_gui": "Uruchom ponownie GUI",
    "cancel": "Anuluj",
    "confirm_logs": "Usunąć stare crashlogi i pozostawić 3 najnowsze?",
    "confirm_gui": "Uruchomić ponownie GUI Enigma2?",
    "success": "Operacja zakończona poprawnie.",
    "failed": "Operacja nie powiodła się:\n{error}",
    "lock_active": "OPKG jest obecnie uruchomiony. Blokada nie została usunięta.",
    "lock_missing": "Nie znaleziono blokady OPKG.",
    "oscam_missing": "Nie znaleziono skryptu ani procesu OSCam.",
    "footer": "Wersja {version} | Python 3 | by {author}",
    "solution_title": "E2 Doctor — możliwe rozwiązanie",
    "back": "Wróć",
    "technical": "Dane techniczne",
    "save_help": "Zapisz instrukcję",
    "instruction_saved": "Instrukcję zapisano w:\n{path}",
    "confirm_repair_bouquets": "Naprawić brakujące odwołania do bukietów?\n\nPrzed zmianą E2 Doctor utworzy kopię plików indeksu w /etc/enigma2.",
    "confirm_remove_lock": "Usunąć nieaktywną blokadę OPKG?",
    "confirm_restart_oscam": "Uruchomić ponownie OSCam?",
    "confirm_sync_time": "Spróbować zsynchronizować datę i czas systemowy?",
    "no_safe_action": "Dla tego wyniku nie ma bezpiecznej automatycznej naprawy. Wykonaj podane kroki ręcznie.",
}


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{%s}" % key


def tr(key, **kwargs):
    text = TEXTS.get(key, key)
    try:
        return text.format(**kwargs)
    except Exception:
        return text


def safe_format(value, context):
    if not isinstance(value, str):
        return value
    try:
        return value.format_map(SafeFormatDict(context or {}))
    except Exception:
        return value


def read_text(path, limit=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            if limit:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit), os.SEEK_SET)
            return handle.read()
    except Exception:
        return ""


def write_text_atomic(path, content):
    temp_path = "%s.e2doctor.tmp" % path
    original_stat = None
    try:
        original_stat = os.stat(path)
    except Exception:
        pass
    with open(temp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except Exception:
            pass
    if original_stat is not None:
        try:
            os.chmod(temp_path, original_stat.st_mode)
        except Exception:
            pass
        try:
            os.chown(temp_path, original_stat.st_uid, original_stat.st_gid)
        except Exception:
            pass
    os.replace(temp_path, path)


def format_bytes(value):
    try:
        value = float(value)
    except Exception:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while value >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return "%.1f %s" % (value, units[idx])


def run_command(command, timeout=8):
    process = None
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout.strip(), stderr.strip()
    except subprocess.TimeoutExpired:
        try:
            if process is not None:
                process.kill()
        except Exception:
            pass
        return 124, "", "Przekroczono limit czasu"
    except Exception as error:
        return 255, "", str(error)


def process_running(name):
    code, output, _ = run_command("pidof %s" % name, timeout=3)
    return code == 0 and bool(output.strip())


def add_result(results, status, title, summary, details="", solution_id=None, context=None, safe_action=None):
    results.append({
        "status": status,
        "title": title,
        "summary": summary,
        "details": details or summary,
        "solution_id": solution_id,
        "context": context or {},
        "safe_action": safe_action,
    })


def load_solutions():
    try:
        with open(SOLUTIONS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


SOLUTIONS = load_solutions()


def get_solution(item):
    solution_id = item.get("solution_id")
    raw = SOLUTIONS.get(solution_id, {}) if solution_id else {}
    context = dict(item.get("context") or {})
    context.setdefault("title", item.get("title", ""))
    context.setdefault("summary", item.get("summary", ""))
    context.setdefault("plugin", "nie ustalono")
    context.setdefault("module", "nie ustalono")
    context.setdefault("error", item.get("summary", "nie ustalono"))
    solution = {}
    for key, value in raw.items():
        if isinstance(value, list):
            solution[key] = [safe_format(entry, context) for entry in value]
        else:
            solution[key] = safe_format(value, context)
    if item.get("safe_action"):
        solution["action"] = item.get("safe_action")
    return solution


def get_image_info():
    values = {}
    for path in ("/etc/image-version", "/etc/os-release", "/etc/issue"):
        content = read_text(path)
        if not content:
            continue
        for line in content.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip().lower()] = value.strip().strip('"')
        if path == "/etc/issue" and "issue" not in values:
            values["issue"] = content.strip().splitlines()[0]
    distro = values.get("distro") or values.get("id") or values.get("creator") or values.get("issue") or "Enigma2"
    version = values.get("imageversion") or values.get("version_id") or values.get("version") or "nieznana"
    build = values.get("compiledate") or values.get("build") or values.get("date") or ""
    return distro, version, build


def check_system(results):
    distro, version, build = get_image_info()
    python_version = sys.version.split()[0]
    machine = os.uname().machine if hasattr(os, "uname") else "nieznana"
    details = "System: %s %s\nKompilacja: %s\nPython: %s\nArchitektura: %s" % (
        distro, version, build or "nieznana", python_version, machine
    )
    if sys.version_info[0] == 3:
        add_result(results, STATUS_OK, "System / Python", "%s %s | Python %s" % (distro, version, python_version), details)
    else:
        add_result(results, STATUS_ERROR, "System / Python", "Wtyczka wymaga środowiska Python 3", details, "python3_required")


def check_flash(results):
    try:
        stats = os.statvfs("/")
        total = stats.f_blocks * stats.f_frsize
        free = stats.f_bavail * stats.f_frsize
        percent = (free * 100.0 / total) if total else 0
        inode_free = (stats.f_favail * 100.0 / stats.f_files) if stats.f_files else 100
        details = "Pojemność: %s\nWolne miejsce: %s (%.1f%%)\nWolne i-węzły: %.1f%%" % (
            format_bytes(total), format_bytes(free), percent, inode_free
        )
        context = {"free": format_bytes(free), "percent": "%.1f" % percent, "inode_percent": "%.1f" % inode_free}
        if free < 25 * 1024 * 1024 or percent < 3 or inode_free < 2:
            add_result(results, STATUS_ERROR, "Pamięć flash", "Krytycznie mało wolnego miejsca: %s" % format_bytes(free), details, "flash_critical", context)
        elif free < 100 * 1024 * 1024 or percent < 10 or inode_free < 8:
            add_result(results, STATUS_WARN, "Pamięć flash", "Mało wolnego miejsca: %s" % format_bytes(free), details, "flash_low", context)
        else:
            add_result(results, STATUS_OK, "Pamięć flash", "Wolne: %s (%.1f%%)" % (format_bytes(free), percent), details)
    except Exception as error:
        add_result(results, STATUS_ERROR, "Pamięć flash", "Nie można odczytać informacji o systemie plików", str(error), "flash_read_error", {"error": str(error)})


def check_memory(results):
    data = {}
    for line in read_text("/proc/meminfo").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            try:
                data[key] = int(value.strip().split()[0]) * 1024
            except Exception:
                pass
    total = data.get("MemTotal", 0)
    available = data.get("MemAvailable", data.get("MemFree", 0) + data.get("Buffers", 0) + data.get("Cached", 0))
    swap_total = data.get("SwapTotal", 0)
    swap_free = data.get("SwapFree", 0)
    percent = (available * 100.0 / total) if total else 0
    details = "RAM łącznie: %s\nRAM dostępny: %s (%.1f%%)\nSWAP wolny: %s z %s" % (
        format_bytes(total), format_bytes(available), percent, format_bytes(swap_free), format_bytes(swap_total)
    )
    context = {"available": format_bytes(available), "percent": "%.1f" % percent, "swap_free": format_bytes(swap_free)}
    if total and available < 8 * 1024 * 1024 and swap_free < 16 * 1024 * 1024:
        add_result(results, STATUS_ERROR, "Pamięć RAM", "Krytycznie mało dostępnej pamięci RAM: %s" % format_bytes(available), details, "ram_critical", context)
    elif total and (available < 50 * 1024 * 1024 or percent < 6):
        add_result(results, STATUS_WARN, "Pamięć RAM", "Mało dostępnej pamięci RAM: %s" % format_bytes(available), details, "ram_low", context)
    else:
        add_result(results, STATUS_OK, "Pamięć RAM", "Dostępne: %s" % format_bytes(available), details)


def check_time(results):
    now = datetime.datetime.now()
    if now.year < 2024:
        add_result(results, STATUS_ERROR, "Data i czas systemowy", now.strftime("%Y-%m-%d %H:%M:%S"), "Nieprawidłowa data może powodować błędy HTTPS, EPG i aktualizacji.", "time_invalid")
    else:
        add_result(results, STATUS_OK, "Data i czas systemowy", now.strftime("%Y-%m-%d %H:%M:%S"), "Lokalny czas systemowy: %s" % now.isoformat(" "))


def check_network(results):
    try:
        addresses = socket.getaddrinfo("github.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        resolved = sorted(set(item[4][0] for item in addresses))
        add_result(results, STATUS_OK, "DNS", "Domena github.com została poprawnie rozwiązana", "Odnalezione adresy: %s" % ", ".join(resolved[:6]))
    except Exception as error:
        add_result(results, STATUS_ERROR, "DNS", "Nie można rozwiązać domeny github.com", str(error), "dns_error", {"error": str(error)})
        return
    try:
        connection = socket.create_connection(("github.com", 443), timeout=3)
        connection.close()
        add_result(results, STATUS_OK, "Połączenie z internetem", "Połączenie HTTPS działa poprawnie", "Połączenie TCP z github.com:443 zakończono poprawnie.")
    except Exception as error:
        add_result(results, STATUS_WARN, "Połączenie z internetem", "DNS działa, ale połączenie HTTPS nie powiodło się", str(error), "https_error", {"error": str(error)})


def check_opkg(results):
    opkg = shutil.which("opkg") or "/usr/bin/opkg"
    if not os.path.exists(opkg):
        add_result(results, STATUS_ERROR, "Menedżer pakietów OPKG", "Nie znaleziono programu OPKG", opkg, "opkg_missing")
        return
    lock_paths = ["/var/lib/opkg/lock", "/var/lock/opkg.lock", "/run/opkg.lock"]
    existing = [path for path in lock_paths if os.path.exists(path)]
    status_file = "/var/lib/opkg/status"
    details = "Program: %s\nBaza pakietów: %s\nBlokady: %s" % (
        opkg,
        status_file if os.path.exists(status_file) else "brak",
        ", ".join(existing) if existing else "brak",
    )
    if not os.path.exists(status_file):
        add_result(results, STATUS_WARN, "Menedżer pakietów OPKG", "Nie znaleziono bazy zainstalowanych pakietów", details, "opkg_db_missing")
    elif existing and not process_running("opkg") and not process_running("opkg-cl"):
        add_result(results, STATUS_WARN, "Menedżer pakietów OPKG", "Możliwa nieaktywna blokada OPKG", details, "opkg_lock")
    else:
        add_result(results, STATUS_OK, "Menedżer pakietów OPKG", "OPKG jest dostępny", details)


def parse_bouquet_references(index_path):
    references = []
    pattern = re.compile(r'FROM BOUQUET\s+"([^"]+)"', re.IGNORECASE)
    for line in read_text(index_path).splitlines():
        match = pattern.search(line)
        if match:
            references.append(match.group(1))
    return references


def find_missing_bouquet_refs():
    base = "/etc/enigma2"
    missing = []
    for index in (os.path.join(base, "bouquets.tv"), os.path.join(base, "bouquets.radio")):
        if not os.path.exists(index):
            continue
        for filename in parse_bouquet_references(index):
            if not os.path.exists(os.path.join(base, filename)):
                missing.append((index, filename))
    return missing


def check_bouquets(results):
    base = "/etc/enigma2"
    missing_pairs = find_missing_bouquet_refs()
    missing = [entry[1] for entry in missing_pairs]
    references = []
    indexes = [os.path.join(base, "bouquets.tv"), os.path.join(base, "bouquets.radio")]
    existing_indexes = [path for path in indexes if os.path.exists(path)]
    for index in existing_indexes:
        references.extend(parse_bouquet_references(index))
    lamedb = os.path.join(base, "lamedb")
    lamedb_size = os.path.getsize(lamedb) if os.path.exists(lamedb) else 0
    bouquet_files = glob.glob(os.path.join(base, "userbouquet.*"))
    details = "Indeksy bukietów: %d\nOdwołania do bukietów: %d\nPliki bukietów: %d\nBrakujące odwołania: %s\nPlik lamedb: %s" % (
        len(existing_indexes), len(references), len(bouquet_files), ", ".join(missing[:30]) if missing else "brak", format_bytes(lamedb_size) if lamedb_size else "brak lub pusty"
    )
    if not existing_indexes or lamedb_size == 0:
        add_result(results, STATUS_ERROR, "Listy kanałów", "Brakuje głównych plików listy kanałów lub są one puste", details, "bouquet_core_missing")
    elif missing:
        add_result(results, STATUS_WARN, "Listy kanałów", "Brakujące odwołania do bukietów: %d" % len(missing), details, "bouquet_missing_refs", {"missing_count": len(missing), "missing": ", ".join(missing[:30])})
    else:
        add_result(results, STATUS_OK, "Listy kanałów", "Bukiety: %d, brak błędnych odwołań" % len(references), details)


def check_tuner_config(results):
    settings = read_text(SETTINGS_FILE)
    nim_lines = [line for line in settings.splitlines() if line.startswith("config.Nims.")]
    scan_files = [path for path in ("/etc/tuxbox/satellites.xml", "/etc/tuxbox/cables.xml", "/etc/tuxbox/terrestrial.xml") if os.path.exists(path)]
    details = "Wpisy konfiguracji głowic: %d\nPliki danych skanowania:\n%s" % (len(nim_lines), "\n".join(scan_files) if scan_files else "brak")
    if not nim_lines:
        add_result(results, STATUS_WARN, "Konfiguracja głowic", "Nie znaleziono wpisów konfiguracji głowic", details, "tuner_missing")
    elif not scan_files:
        add_result(results, STATUS_WARN, "Konfiguracja głowic", "Ustawienia głowic istnieją, ale brakuje plików XML skanowania", details, "tuner_xml_missing")
    else:
        add_result(results, STATUS_OK, "Konfiguracja głowic", "Wykryto wpisy konfiguracji: %d" % len(nim_lines), details)


def get_mounts():
    mounts = []
    for line in read_text("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) >= 4:
            device, mountpoint, fstype, options = parts[:4]
            mounts.append((device, mountpoint.replace("\\040", " "), fstype, options))
    return mounts


def check_mounts(results):
    media_mounts = []
    readonly = []
    for device, mountpoint, fstype, options in get_mounts():
        if mountpoint.startswith("/media/") and fstype not in ("tmpfs", "devtmpfs"):
            media_mounts.append((device, mountpoint, fstype, options))
            if "ro" in options.split(","):
                readonly.append(mountpoint)
    lines = ["%s -> %s (%s, %s)" % item for item in media_mounts]
    details = "\n".join(lines) if lines else "Nie znaleziono zewnętrznych nośników zamontowanych w /media."
    if readonly:
        add_result(results, STATUS_WARN, "Nośniki i punkty montowania", "Nośniki tylko do odczytu: %s" % ", ".join(readonly), details, "mount_readonly", {"mounts": ", ".join(readonly)})
    elif media_mounts:
        add_result(results, STATUS_OK, "Nośniki i punkty montowania", "Wykryto zewnętrzne nośniki: %d" % len(media_mounts), details)
    else:
        add_result(results, STATUS_INFO, "Nośniki i punkty montowania", "Nie wykryto zewnętrznego nośnika", details)


def check_epg(results):
    settings = read_text(SETTINGS_FILE)
    path = "/etc/enigma2/epg.dat"
    for line in settings.splitlines():
        if line.startswith("config.misc.epgcache_filename="):
            value = line.split("=", 1)[1].strip()
            if value:
                path = value
                break
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S") if exists else "brak"
    details = "Plik EPG: %s\nRozmiar: %s\nOstatnia modyfikacja: %s" % (path, format_bytes(size), mtime)
    if not exists:
        add_result(results, STATUS_INFO, "Pamięć EPG", "Plik EPG nie został jeszcze utworzony", details)
    elif size < 1024:
        add_result(results, STATUS_WARN, "Pamięć EPG", "Plik EPG jest pusty lub nietypowo mały", details, "epg_small", {"path": path})
    else:
        add_result(results, STATUS_OK, "Pamięć EPG", "Rozmiar: %s" % format_bytes(size), details)


def check_picons(results):
    candidates = ["/usr/share/enigma2/picon", "/media/hdd/picon", "/media/usb/picon", "/media/mmc/picon", "/picon"]
    found = []
    total = 0
    for path in candidates:
        if os.path.isdir(path):
            try:
                count = len([name for name in os.listdir(path) if name.lower().endswith((".png", ".svg"))])
            except Exception:
                count = 0
            found.append("%s: %d" % (path, count))
            total += count
    details = "\n".join(found) if found else "Nie znaleziono standardowego katalogu piconów."
    if found and total > 0:
        add_result(results, STATUS_OK, "Picony", "Wykryto picony: %d" % total, details)
    elif found:
        add_result(results, STATUS_INFO, "Picony", "Katalog piconów istnieje, ale jest pusty", details)
    else:
        add_result(results, STATUS_INFO, "Picony", "Nie wykryto piconów", details)


def find_oscam_configs():
    found = []
    for base in ("/etc/tuxbox/config/oscam", "/etc/tuxbox/config", "/usr/keys", "/etc/oscam"):
        for name in ("oscam.conf", "oscam.server", "oscam.user", "oscam.dvbapi"):
            path = os.path.join(base, name)
            if os.path.exists(path):
                found.append(path)
    return sorted(set(found))


def check_oscam(results):
    running = process_running("oscam") or process_running("oscam-emu")
    configs = find_oscam_configs()
    details = "Proces uruchomiony: %s\nPliki konfiguracyjne:\n%s" % ("tak" if running else "nie", "\n".join(configs) if configs else "nie znaleziono")
    if running:
        add_result(results, STATUS_OK, "OSCam", "Proces OSCam jest uruchomiony", details)
    elif configs:
        add_result(results, STATUS_WARN, "OSCam", "Konfiguracja istnieje, ale OSCam nie jest uruchomiony", details, "oscam_stopped")
    else:
        add_result(results, STATUS_INFO, "OSCam", "OSCam nie jest zainstalowany lub skonfigurowany", details)


def find_crashlogs():
    patterns = [
        "/home/root/logs/*crash*.log", "/home/root/logs/enigma2*.log", "/media/hdd/*crash*.log",
        "/media/hdd/enigma2*.log", "/tmp/*crash*.log", "/tmp/enigma2*.log", "/var/log/enigma2*.log",
    ]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))
    valid = []
    for path in sorted(set(files)):
        try:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                valid.append(path)
        except Exception:
            pass
    return sorted(valid, key=lambda item: os.path.getmtime(item), reverse=True)


def analyze_crashlog(content):
    rules = [
        ("missing_module", r"ModuleNotFoundError:\s*No module named ['\"]?([^'\"\s]+)", "Brak modułu Python: {0}", "crash_python_module", "module"),
        ("missing_module", r"No module named ['\"]?([^'\"\s]+)", "Brak modułu Python: {0}", "crash_python_module", "module"),
        ("import_error", r"ImportError:\s*(.+)", "Błąd importu: {0}", "crash_import", "error"),
        ("skin_error", r"SkinError:\s*(.+)", "Błąd skina: {0}", "crash_skin", "error"),
        ("no_space", r"No space left on device", "Brak wolnego miejsca na urządzeniu", "crash_no_space", None),
        ("syntax_error", r"SyntaxError:\s*(.+)", "Błąd składni Python: {0}", "crash_python_error", "error"),
        ("indent_error", r"IndentationError:\s*(.+)", "Błąd wcięć Python: {0}", "crash_python_error", "error"),
        ("type_error", r"TypeError:\s*(.+)", "Błąd typu danych: {0}", "crash_python_error", "error"),
        ("runtime_error", r"RuntimeError:\s*(.+)", "Błąd wykonania: {0}", "crash_python_error", "error"),
        ("key_error", r"KeyError:\s*(.+)", "Brak klucza w danych wtyczki: {0}", "crash_python_error", "error"),
        ("index_error", r"IndexError:\s*(.+)", "Błąd indeksu lub listy we wtyczce: {0}", "crash_python_error", "error"),
        ("attribute_error", r"AttributeError:\s*(.+)", "Błąd zgodności wtyczki lub API: {0}", "crash_python_error", "error"),
        ("permission", r"Permission denied", "Brak uprawnień do pliku lub katalogu", "crash_permission", None),
        ("readonly", r"Read-only file system", "System plików jest zamontowany tylko do odczytu", "crash_readonly", None),
        ("ssl", r"certificate verify failed", "Błąd weryfikacji certyfikatu HTTPS", "crash_ssl", None),
        ("network", r"Network is unreachable", "Sieć jest niedostępna", "crash_network", None),
        ("segfault", r"Segmentation fault", "Błąd segmentacji składnika systemowego", "crash_segfault", None),
        ("fatal", r"FATAL.*?(.+)", "Błąd krytyczny: {0}", "crash_generic", "error"),
    ]
    plugin_match = re.findall(r"Plugins/Extensions/([^/\s]+)/", content)
    plugin_name = plugin_match[-1] if plugin_match else "nie ustalono"
    findings = []
    seen = set()
    for code, pattern, message, solution_id, context_key in rules:
        match = re.search(pattern, content, re.IGNORECASE)
        if not match:
            continue
        value = ""
        if match.lastindex:
            try:
                value = match.group(1).strip()[:180]
            except Exception:
                value = ""
        text = message.format(value) if "{0}" in message else message
        if text in seen:
            continue
        context = {"plugin": plugin_name, "error": value or text}
        if context_key:
            context[context_key] = value or "nie ustalono"
        findings.append({"code": code, "message": text, "solution_id": solution_id, "context": context})
        seen.add(text)
    return findings


def check_crashlogs(results):
    logs = find_crashlogs()
    if not logs:
        add_result(results, STATUS_OK, "Crashlogi Enigma2", "Nie znaleziono crashlogów", "Sprawdzono standardowe katalogi logów.")
        return
    newest = logs[0]
    content = read_text(newest, limit=700000)
    findings = analyze_crashlog(content)
    modified = os.path.getmtime(newest)
    stamp = datetime.datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M:%S")
    age_hours = max(0.0, (time.time() - modified) / 3600.0)
    has_traceback = "Traceback (most recent call last)" in content or "Segmentation fault" in content or "FATAL" in content
    finding_lines = [item["message"] for item in findings]
    details = "Najnowszy log: %s\nOstatnia modyfikacja: %s\nLiczba wykrytych logów: %d\nWiek najnowszego logu: %.1f godz.\n\nAnaliza:\n%s" % (
        newest, stamp, len(logs), age_hours, "\n".join(finding_lines) if finding_lines else "Nie rozpoznano znanego wzorca błędu."
    )
    if findings:
        first = findings[0]
        context = dict(first.get("context") or {})
        context.update({"log_path": newest, "log_count": len(logs), "age_hours": "%.1f" % age_hours})
        if has_traceback and age_hours <= 48:
            add_result(results, STATUS_ERROR, "Crashlogi Enigma2", first["message"], details, first["solution_id"], context)
        else:
            add_result(results, STATUS_WARN, "Crashlogi Enigma2", first["message"], details, first["solution_id"], context)
    else:
        solution_id = "crash_generic" if has_traceback else None
        status = STATUS_WARN if has_traceback and age_hours <= 48 else STATUS_INFO
        add_result(results, status, "Crashlogi Enigma2", "Crashlogi: %d, brak rozpoznanego wzorca" % len(logs), details, solution_id, {"log_path": newest})


def check_temperature(results):
    candidates = glob.glob("/sys/class/thermal/thermal_zone*/temp") + ["/proc/stb/sensors/temp0/value", "/proc/stb/fp/temp_sensor"]
    readings = []
    for path in candidates:
        raw = read_text(path).strip()
        if not raw:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", raw)
        if not match:
            continue
        value = float(match.group(0))
        if value > 1000:
            value /= 1000.0
        if -20 < value < 150:
            readings.append((path, value))
    if not readings:
        add_result(results, STATUS_INFO, "Temperatura", "Czujnik temperatury jest niedostępny", "Nie znaleziono czytelnego czujnika temperatury.")
        return
    highest = max(value for _, value in readings)
    details = "\n".join("%s: %.1f °C" % item for item in readings)
    if highest >= 90:
        add_result(results, STATUS_ERROR, "Temperatura", "Temperatura krytyczna: %.1f °C" % highest, details, "temperature_critical", {"temperature": "%.1f" % highest})
    elif highest >= 75:
        add_result(results, STATUS_WARN, "Temperatura", "Wysoka temperatura: %.1f °C" % highest, details, "temperature_high", {"temperature": "%.1f" % highest})
    else:
        add_result(results, STATUS_OK, "Temperatura", "%.1f °C" % highest, details)


def run_all_checks():
    results = []
    checks = [
        check_system, check_flash, check_memory, check_time, check_network, check_opkg, check_bouquets,
        check_tuner_config, check_mounts, check_epg, check_picons, check_oscam, check_crashlogs, check_temperature,
    ]
    for check in checks:
        try:
            check(results)
        except Exception as error:
            add_result(results, STATUS_ERROR, check.__name__, "Moduł diagnostyczny zakończył się błędem", "%s\n%s" % (error, traceback.format_exc()), "diagnostic_error", {"error": str(error), "module": check.__name__})
    return results


def status_prefix(status):
    return {STATUS_OK: "[ OK ]", STATUS_WARN: "[ !  ]", STATUS_ERROR: "[ X  ]", STATUS_INFO: "[ i  ]"}.get(status, "[ ?  ]")


def status_name(status):
    return {STATUS_OK: "WYNIK PRAWIDŁOWY", STATUS_WARN: "OSTRZEŻENIE", STATUS_ERROR: "WYKRYTY BŁĄD", STATUS_INFO: "INFORMACJA"}.get(status, "WYNIK")


def choose_writable_report_dir():
    for candidate in ("/media/hdd", "/media/usb", "/media/mmc", "/media/sda1"):
        if os.path.ismount(candidate) and os.access(candidate, os.W_OK):
            return candidate
    return "/tmp"


def build_solution_text(item, include_technical=False):
    solution = get_solution(item)
    lines = [
        status_name(item.get("status")),
        "",
        item.get("title", ""),
        "Wykryto: %s" % item.get("summary", ""),
    ]
    if solution:
        lines.extend(["", "MOŻLIWA PRZYCZYNA", "", solution.get("cause", "Brak dodatkowego opisu przyczyny.")])
        consequences = solution.get("consequences")
        if consequences:
            lines.extend(["", "MOŻLIWE SKUTKI", "", consequences])
        steps = solution.get("steps") or []
        if steps:
            lines.extend(["", "CO NALEŻY ZROBIĆ", ""])
            for index, step in enumerate(steps, 1):
                lines.append("%d. %s" % (index, step))
        restart = solution.get("restart")
        if restart:
            lines.extend(["", "RESTART", "", restart])
        action = solution.get("action")
        if action:
            lines.extend(["", "BEZPIECZNE DZIAŁANIE", "", "Zielony przycisk: %s" % solution.get("action_label", "Wykonaj działanie")])
        elif item.get("status") in (STATUS_WARN, STATUS_ERROR):
            lines.extend(["", "DZIAŁANIE AUTOMATYCZNE", "", tr("no_safe_action")])
    else:
        if item.get("status") in (STATUS_OK, STATUS_INFO):
            lines.extend(["", "Nie wykryto problemu wymagającego naprawy."])
        else:
            lines.extend(["", "Brak gotowej instrukcji dla tego wyniku. Zapisz raport i sprawdź dane techniczne."])
    if include_technical:
        lines.extend(["", "DANE TECHNICZNE", "", item.get("details", "Brak danych technicznych.")])
    return "\n".join(lines)


def make_report(results):
    now = datetime.datetime.now()
    path = os.path.join(choose_writable_report_dir(), "E2Doctor_Raport_%s.txt" % now.strftime("%Y%m%d_%H%M%S"))
    distro, version, build = get_image_info()
    lines = [
        "Raport diagnostyczny E2 Doctor", "Utworzono: %s" % now.strftime("%Y-%m-%d %H:%M:%S"),
        "Wersja wtyczki: %s" % PLUGIN_VERSION, "Autor: %s" % PLUGIN_AUTHOR,
        "System: %s %s" % (distro, version), "Kompilacja: %s" % (build or "nieznana"),
        "Python: %s" % sys.version.replace("\n", " "),
        "Architektura: %s" % (os.uname().machine if hasattr(os, "uname") else "nieznana"), "",
        "UWAGA: Raport nie zawiera haseł, linii serwerów OSCam ani pełnego pliku ustawień.", "",
    ]
    for item in results:
        lines.extend(["=" * 72, "%s %s" % (status_prefix(item["status"]), item["title"]), item["summary"], "-" * 72, item["details"]])
        if item.get("status") in (STATUS_WARN, STATUS_ERROR) and item.get("solution_id"):
            lines.extend(["", "MOŻLIWE ROZWIĄZANIE", "-" * 72, build_solution_text(item, include_technical=False)])
        lines.append("")
    code, uptime, _ = run_command("uptime", timeout=3)
    if code == 0:
        lines.extend(["=" * 72, "Czas pracy systemu", uptime, ""])
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def save_solution_instruction(item):
    now = datetime.datetime.now()
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", item.get("title", "wynik"))[:50]
    path = os.path.join(choose_writable_report_dir(), "E2Doctor_Instrukcja_%s_%s.txt" % (safe_name, now.strftime("%Y%m%d_%H%M%S")))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(build_solution_text(item, include_technical=True))
        handle.write("\n")
    return path


def create_backup(paths, label):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = "/etc/enigma2/e2doctor_backup_%s_%s" % (label, timestamp)
    os.makedirs(backup_dir, exist_ok=False)
    copied = 0
    for path in paths:
        if os.path.isfile(path):
            shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))
            copied += 1
    if copied == 0:
        try:
            os.rmdir(backup_dir)
        except Exception:
            pass
        raise RuntimeError("Nie znaleziono plików do wykonania kopii")
    return backup_dir


def repair_missing_bouquet_refs():
    base = "/etc/enigma2"
    indexes = [path for path in (os.path.join(base, "bouquets.tv"), os.path.join(base, "bouquets.radio")) if os.path.isfile(path)]
    missing_pairs = find_missing_bouquet_refs()
    missing_set = set((index, filename) for index, filename in missing_pairs)
    if not missing_set:
        return 0, "Nie znaleziono brakujących odwołań."
    backup_dir = create_backup(indexes, "bukiety")
    pattern = re.compile(r'FROM BOUQUET\s+"([^"]+)"', re.IGNORECASE)
    removed = 0
    for index_path in indexes:
        content = read_text(index_path)
        output = []
        for line in content.splitlines(True):
            match = pattern.search(line)
            if match and (index_path, match.group(1)) in missing_set:
                removed += 1
                continue
            output.append(line)
        write_text_atomic(index_path, "".join(output))
    if eDVBDB is not None:
        db = eDVBDB.getInstance()
        db.reloadServicelist()
        db.reloadBouquets()
    return removed, backup_dir


def remove_inactive_opkg_locks():
    if process_running("opkg") or process_running("opkg-cl"):
        raise RuntimeError(tr("lock_active"))
    removed = []
    for path in ("/var/lib/opkg/lock", "/var/lock/opkg.lock", "/run/opkg.lock"):
        if os.path.exists(path):
            os.remove(path)
            removed.append(path)
    return removed


def cleanup_old_crashlogs(keep=3):
    logs = find_crashlogs()
    removed = []
    for path in logs[keep:]:
        try:
            os.remove(path)
            removed.append(path)
        except Exception:
            pass
    return removed


def restart_oscam_service():
    commands = [
        "/etc/init.d/softcam.oscam restart", "/etc/init.d/oscam restart", "systemctl restart oscam", "killall -HUP oscam",
    ]
    errors = []
    for command in commands:
        executable = command.split()[0]
        if executable.startswith("/") and not os.path.exists(executable):
            continue
        code, output, error = run_command(command, timeout=12)
        if code == 0:
            return command, output
        errors.append("%s: %s" % (command, error or output or "kod %s" % code))
    raise RuntimeError("Nie udało się uruchomić OSCam.\n%s" % "\n".join(errors[-3:]))


def sync_system_time():
    commands = [
        "/etc/init.d/chronyd restart", "/etc/init.d/ntpd restart", "systemctl restart chronyd", "systemctl restart ntpd", "ntpd -q -p pool.ntp.org",
    ]
    errors = []
    for command in commands:
        executable = command.split()[0]
        if executable.startswith("/") and not os.path.exists(executable):
            continue
        code, output, error = run_command(command, timeout=20)
        if code == 0:
            return command, output
        errors.append("%s: %s" % (command, error or output or "kod %s" % code))
    raise RuntimeError("Nie udało się zsynchronizować czasu.\n%s" % "\n".join(errors[-3:]))


def network_diagnostic_text():
    lines = ["TEST SIECI E2 DOCTOR", ""]
    code, routes, error = run_command("ip route 2>/dev/null || route -n 2>/dev/null", timeout=5)
    lines.extend(["Trasy sieciowe:", routes if code == 0 and routes else error or "brak danych", ""])
    resolv = read_text("/etc/resolv.conf").strip()
    lines.extend(["Konfiguracja DNS:", resolv or "brak danych", ""])
    gateway = None
    match = re.search(r"default\s+via\s+([0-9.]+)", routes or "")
    if not match:
        match = re.search(r"^0\.0\.0\.0\s+([0-9.]+)", routes or "", re.MULTILINE)
    if match:
        gateway = match.group(1)
        code, output, error = run_command("ping -c 1 -W 2 %s" % gateway, timeout=4)
        lines.extend(["Brama %s: %s" % (gateway, "OK" if code == 0 else "BŁĄD"), output or error or "brak odpowiedzi", ""])
    else:
        lines.extend(["Brama: nie wykryto trasy domyślnej", ""])
    try:
        addresses = socket.getaddrinfo("github.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        resolved = sorted(set(item[4][0] for item in addresses))
        lines.extend(["DNS github.com: OK", ", ".join(resolved[:6]), ""])
    except Exception as error:
        lines.extend(["DNS github.com: BŁĄD", str(error), ""])
    try:
        connection = socket.create_connection(("github.com", 443), timeout=4)
        connection.close()
        lines.extend(["Połączenie github.com:443: OK"])
    except Exception as error:
        lines.extend(["Połączenie github.com:443: BŁĄD", str(error)])
    return "\n".join(lines)


def top_memory_processes_text(limit=12):
    rows = []
    for pid in glob.glob("/proc/[0-9]*"):
        try:
            status = read_text(os.path.join(pid, "status"))
            name_match = re.search(r"^Name:\s*(.+)$", status, re.MULTILINE)
            rss_match = re.search(r"^VmRSS:\s*(\d+)\s*kB", status, re.MULTILINE)
            if not rss_match:
                continue
            process_id = os.path.basename(pid)
            name = name_match.group(1).strip() if name_match else "proces"
            rss_kb = int(rss_match.group(1))
            cmdline = read_text(os.path.join(pid, "cmdline")).replace("\x00", " ").strip()
            rows.append((rss_kb, process_id, name, cmdline[:90]))
        except Exception:
            pass
    rows.sort(reverse=True)
    lines = ["PROCESY ZUŻYWAJĄCE NAJWIĘCEJ RAM", "", "RAM       PID     PROCES"]
    for rss_kb, process_id, name, cmdline in rows[:limit]:
        description = cmdline or name
        lines.append("%-9s %-7s %s" % (format_bytes(rss_kb * 1024), process_id, description))
    if len(lines) == 3:
        lines.append("Nie udało się odczytać procesów.")
    lines.extend(["", "Nie kończ procesów systemowych bez rozpoznania ich przeznaczenia."])
    return "\n".join(lines)


def largest_files_text(limit=20):
    roots = ["/usr", "/etc", "/home", "/var"]
    skip_prefixes = ("/var/volatile", "/var/run", "/var/lock")
    files = []
    visited = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for current, dirs, names in os.walk(root):
            if current.startswith(skip_prefixes):
                dirs[:] = []
                continue
            dirs[:] = [entry for entry in dirs if not os.path.islink(os.path.join(current, entry))]
            for name in names:
                path = os.path.join(current, name)
                visited += 1
                if visited > 60000:
                    break
                try:
                    if os.path.islink(path) or not os.path.isfile(path):
                        continue
                    size = os.path.getsize(path)
                    if size >= 512 * 1024:
                        files.append((size, path))
                except Exception:
                    pass
            if visited > 60000:
                break
        if visited > 60000:
            break
    files.sort(reverse=True)
    lines = ["NAJWIĘKSZE PLIKI W PAMIĘCI SYSTEMOWEJ", ""]
    for size, path in files[:limit]:
        lines.append("%-10s %s" % (format_bytes(size), path))
    if not files:
        lines.append("Nie znaleziono plików większych niż 512 KB.")
    lines.extend(["", "UWAGA: lista służy wyłącznie do analizy. Nie usuwaj bibliotek ani plików systemowych bez pewności, czym są."])
    return "\n".join(lines)


class E2DoctorResultList(MenuList):
    COLORS = {STATUS_OK: 0x0055FF55, STATUS_WARN: 0x00FFFF55, STATUS_ERROR: 0x00FF5555, STATUS_INFO: 0x00BBDDEE}

    def __init__(self, entries=None):
        MenuList.__init__(self, entries or [], enableWrapAround=False, content=eListboxPythonMultiContent)
        self.l.setFont(0, gFont("Regular", 25))
        self.l.setItemHeight(42)
        self.l.setBuildFunc(self.build_entry)

    def build_entry(self, status, text):
        color = self.COLORS.get(status, 0x00FFFFFF)
        return [None, MultiContentEntryText(pos=(8, 0), size=(1058, 42), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=text, color=color, color_sel=color)]


class E2DoctorTextScreen(Screen):
    skin = """
    <screen name="E2DoctorTextScreen" position="center,center" size="1120,650" title="E2 Doctor">
        <widget name="title" position="35,20" size="1050,48" font="Regular;34" halign="center" />
        <widget name="body" position="45,85" size="1030,475" font="Regular;24" scrollbarMode="showOnDemand" />
        <widget source="key_red" render="Label" position="60,590" size="230,40" font="Regular;25" halign="center" foregroundColor="#ff5555" />
        <widget source="key_blue" render="Label" position="830,590" size="230,40" font="Regular;25" halign="center" foregroundColor="#5599ff" />
    </screen>
    """

    def __init__(self, session, title, text):
        Screen.__init__(self, session)
        self["title"] = Label(title)
        self["body"] = ScrollLabel(text)
        self["key_red"] = StaticText(tr("back"))
        self["key_blue"] = StaticText(tr("exit"))
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {"cancel": self.close, "red": self.close, "blue": self.close, "ok": self.close, "up": self["body"].pageUp, "down": self["body"].pageDown, "left": self["body"].pageUp, "right": self["body"].pageDown},
            -1,
        )


class E2DoctorSolutionScreen(Screen):
    skin = """
    <screen name="E2DoctorSolutionScreen" position="center,center" size="1180,690" title="E2 Doctor">
        <widget name="title" position="35,18" size="1110,45" font="Regular;34" halign="center" />
        <widget name="status" position="45,70" size="1090,35" font="Regular;24" halign="center" />
        <widget name="body" position="45,120" size="1090,455" font="Regular;24" scrollbarMode="showOnDemand" />
        <widget source="key_red" render="Label" position="35,615" size="240,42" font="Regular;24" halign="center" foregroundColor="#ff5555" />
        <widget source="key_green" render="Label" position="305,615" size="260,42" font="Regular;24" halign="center" foregroundColor="#55ff55" />
        <widget source="key_yellow" render="Label" position="595,615" size="250,42" font="Regular;24" halign="center" foregroundColor="#ffff55" />
        <widget source="key_blue" render="Label" position="875,615" size="270,42" font="Regular;24" halign="center" foregroundColor="#5599ff" />
    </screen>
    """

    def __init__(self, session, item):
        Screen.__init__(self, session)
        self.item = item
        self.solution = get_solution(item)
        self.action_name = self.solution.get("action")
        self["title"] = Label(tr("solution_title"))
        self["status"] = Label("%s — %s" % (status_name(item.get("status")), item.get("title", "")))
        self["body"] = ScrollLabel(build_solution_text(item, include_technical=False))
        self["key_red"] = StaticText(tr("back"))
        self["key_green"] = StaticText(self.solution.get("action_label", "") if self.action_name else "")
        self["key_yellow"] = StaticText(tr("technical"))
        self["key_blue"] = StaticText(tr("save_help"))
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "cancel": self.close, "red": self.close, "green": self.perform_action, "ok": self.perform_action,
                "yellow": self.show_technical, "blue": self.save_instruction,
                "up": self["body"].pageUp, "down": self["body"].pageDown, "left": self["body"].pageUp, "right": self["body"].pageDown,
            },
            -1,
        )

    def show_technical(self):
        self.session.open(E2DoctorTextScreen, "Dane techniczne — %s" % self.item.get("title", ""), self.item.get("details", "Brak danych technicznych."))

    def save_instruction(self):
        try:
            path = save_solution_instruction(self.item)
            self.session.open(MessageBox, tr("instruction_saved", path=path), MessageBox.TYPE_INFO, timeout=8)
        except Exception as error:
            self.session.open(MessageBox, tr("failed", error=str(error)), MessageBox.TYPE_ERROR)

    def perform_action(self):
        if not self.action_name:
            self.session.open(MessageBox, tr("no_safe_action"), MessageBox.TYPE_INFO, timeout=7)
            return
        confirmations = {
            "repair_bouquet_refs": tr("confirm_repair_bouquets"),
            "remove_opkg_lock": tr("confirm_remove_lock"),
            "restart_oscam": tr("confirm_restart_oscam"),
            "sync_time": tr("confirm_sync_time"),
        }
        if self.action_name in confirmations:
            self.session.openWithCallback(self._confirmed_action, MessageBox, confirmations[self.action_name], MessageBox.TYPE_YESNO)
        else:
            self._execute_action()

    def _confirmed_action(self, answer):
        if answer:
            self._execute_action()

    def _show_success_and_close(self, message):
        self.session.openWithCallback(lambda *args: self.close(True), MessageBox, message, MessageBox.TYPE_INFO, timeout=8)

    def _execute_action(self):
        try:
            if self.action_name == "repair_bouquet_refs":
                removed, backup_dir = repair_missing_bouquet_refs()
                self._show_success_and_close("Usunięto błędne odwołania: %d\nKopia bezpieczeństwa:\n%s" % (removed, backup_dir))
            elif self.action_name == "remove_opkg_lock":
                removed = remove_inactive_opkg_locks()
                if removed:
                    self._show_success_and_close("Usunięto blokady OPKG:\n%s" % "\n".join(removed))
                else:
                    self.session.open(MessageBox, tr("lock_missing"), MessageBox.TYPE_INFO, timeout=6)
            elif self.action_name == "restart_oscam":
                command, _ = restart_oscam_service()
                self._show_success_and_close("OSCam został uruchomiony ponownie.\nUżyte polecenie: %s" % command)
            elif self.action_name == "sync_time":
                command, _ = sync_system_time()
                self._show_success_and_close("Uruchomiono synchronizację czasu.\nUżyte polecenie: %s\nAktualny czas: %s" % (command, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            elif self.action_name == "network_test":
                self.session.open(E2DoctorTextScreen, "Test sieci", network_diagnostic_text())
            elif self.action_name == "show_processes":
                self.session.open(E2DoctorTextScreen, "Zużycie pamięci RAM", top_memory_processes_text())
            elif self.action_name == "find_large_files":
                self.session.open(E2DoctorTextScreen, "Największe pliki", largest_files_text())
            else:
                self.session.open(MessageBox, "Nieznane działanie: %s" % self.action_name, MessageBox.TYPE_ERROR)
        except Exception as error:
            self.session.open(MessageBox, tr("failed", error=str(error)), MessageBox.TYPE_ERROR)


class E2DoctorTools(Screen):
    skin = """
    <screen name="E2DoctorTools" position="center,center" size="900,520" title="E2 Doctor">
        <widget name="title" position="35,25" size="830,50" font="Regular;34" halign="center" />
        <widget name="list" position="45,95" size="810,320" font="Regular;26" itemHeight="46" scrollbarMode="showOnDemand" />
        <widget source="key_green" render="Label" position="250,455" size="180,40" font="Regular;24" halign="center" foregroundColor="#55ff55" />
        <widget source="key_blue" render="Label" position="650,455" size="180,40" font="Regular;24" halign="center" foregroundColor="#5599ff" />
    </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self["title"] = Label(tr("tool_title"))
        self["key_green"] = StaticText("OK")
        self["key_blue"] = StaticText(tr("exit"))
        self.tool_entries = [
            (tr("tool_reload"), "reload"), (tr("tool_lock"), "lock"), (tr("tool_logs"), "logs"),
            (tr("tool_oscam"), "oscam"), (tr("tool_gui"), "gui"),
        ]
        self["list"] = MenuList([item[0] for item in self.tool_entries])
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {"ok": self.execute, "green": self.execute, "cancel": self.close, "blue": self.close}, -1)

    def execute(self):
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.tool_entries):
            return
        action = self.tool_entries[index][1]
        if action == "reload":
            self.reload_bouquets()
        elif action == "lock":
            self.remove_opkg_lock()
        elif action == "logs":
            self.session.openWithCallback(self.logs_confirmed, MessageBox, tr("confirm_logs"), MessageBox.TYPE_YESNO)
        elif action == "oscam":
            self.session.openWithCallback(self.oscam_confirmed, MessageBox, tr("confirm_restart_oscam"), MessageBox.TYPE_YESNO)
        elif action == "gui":
            self.session.openWithCallback(self.gui_confirmed, MessageBox, tr("confirm_gui"), MessageBox.TYPE_YESNO)

    def show_result(self, success=True, error=""):
        text = tr("success") if success else tr("failed", error=error)
        self.session.open(MessageBox, text, MessageBox.TYPE_INFO if success else MessageBox.TYPE_ERROR, timeout=7)

    def reload_bouquets(self):
        try:
            if eDVBDB is None:
                raise RuntimeError("Interfejs eDVBDB jest niedostępny")
            db = eDVBDB.getInstance()
            db.reloadServicelist()
            db.reloadBouquets()
            self.show_result(True)
        except Exception as error:
            self.show_result(False, str(error))

    def remove_opkg_lock(self):
        try:
            removed = remove_inactive_opkg_locks()
            if removed:
                self.session.open(MessageBox, "Usunięto:\n%s" % "\n".join(removed), MessageBox.TYPE_INFO, timeout=7)
            else:
                self.session.open(MessageBox, tr("lock_missing"), MessageBox.TYPE_INFO, timeout=6)
        except Exception as error:
            self.show_result(False, str(error))

    def logs_confirmed(self, answer):
        if not answer:
            return
        try:
            removed = cleanup_old_crashlogs(3)
            self.session.open(MessageBox, "Usunięto starych crashlogów: %d" % len(removed), MessageBox.TYPE_INFO, timeout=7)
        except Exception as error:
            self.show_result(False, str(error))

    def oscam_confirmed(self, answer):
        if not answer:
            return
        try:
            command, _ = restart_oscam_service()
            self.session.open(MessageBox, "OSCam został uruchomiony ponownie.\n%s" % command, MessageBox.TYPE_INFO, timeout=7)
        except Exception as error:
            self.show_result(False, str(error))

    def gui_confirmed(self, answer):
        if answer:
            try:
                from Screens.Standby import TryQuitMainloop
                self.session.open(TryQuitMainloop, 3)
            except Exception as error:
                self.show_result(False, str(error))


class E2DoctorMain(Screen):
    skin = """
    <screen name="E2DoctorMain" position="center,center" size="1180,680" title="E2 Doctor">
        <widget name="title" position="35,18" size="1110,50" font="Regular;38" halign="center" />
        <widget name="subtitle" position="35,70" size="1110,34" font="Regular;23" halign="center" foregroundColor="#bbbbbb" />
        <widget name="status" position="45,115" size="1090,42" font="Regular;23" halign="center" />
        <widget name="list" position="45,170" size="1090,380" scrollbarMode="showOnDemand" />
        <widget source="key_red" render="Label" position="25,580" size="220,42" font="Regular;24" halign="center" foregroundColor="#ff5555" />
        <widget source="key_green" render="Label" position="270,580" size="285,42" font="Regular;24" halign="center" foregroundColor="#55ff55" />
        <widget source="key_yellow" render="Label" position="580,580" size="220,42" font="Regular;24" halign="center" foregroundColor="#ffff55" />
        <widget source="key_blue" render="Label" position="825,580" size="220,42" font="Regular;24" halign="center" foregroundColor="#5599ff" />
        <widget name="footer" position="35,635" size="1110,28" font="Regular;20" halign="center" foregroundColor="#999999" />
    </screen>
    """

    def __init__(self, session):
        Screen.__init__(self, session)
        self.results = []
        self["title"] = Label(tr("title"))
        self["subtitle"] = Label(tr("subtitle"))
        self["status"] = Label(tr("no_result"))
        self["footer"] = Label(tr("footer", version=PLUGIN_VERSION, author=PLUGIN_AUTHOR))
        self["key_red"] = StaticText(tr("scan"))
        self["key_green"] = StaticText(tr("details"))
        self["key_yellow"] = StaticText(tr("report"))
        self["key_blue"] = StaticText(tr("exit"))
        self["list"] = E2DoctorResultList([])
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "MenuActions", "InfoActions"],
            {"red": self.scan, "green": self.show_details, "yellow": self.create_report, "blue": self.close, "ok": self.show_details, "cancel": self.close, "menu": self.open_tools, "info": self.open_tools},
            -1,
        )
        self.onShown.append(self.first_scan)
        self._first_scan_done = False

    def first_scan(self):
        if not self._first_scan_done:
            self._first_scan_done = True
            self.scan()

    def scan(self):
        self["status"].setText(tr("scanning"))
        try:
            self.results = run_all_checks()
            rows = []
            for item in self.results:
                text = "%s  %s — %s" % (status_prefix(item["status"]), item["title"], item["summary"])
                rows.append((item["status"], text))
            self["list"].setList(rows)
            ok = len([item for item in self.results if item["status"] == STATUS_OK])
            info = len([item for item in self.results if item["status"] == STATUS_INFO])
            warn = len([item for item in self.results if item["status"] == STATUS_WARN])
            err = len([item for item in self.results if item["status"] == STATUS_ERROR])
            self["status"].setText(tr("done", ok=ok, info=info, warn=warn, err=err))
        except Exception as error:
            self["status"].setText("Błąd diagnostyki: %s" % error)
            self.session.open(MessageBox, traceback.format_exc(), MessageBox.TYPE_ERROR)

    def show_details(self):
        if not self.results:
            self.session.open(MessageBox, tr("no_result"), MessageBox.TYPE_INFO, timeout=5)
            return
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.results):
            return
        self.session.openWithCallback(self.solution_closed, E2DoctorSolutionScreen, self.results[index])

    def solution_closed(self, changed=False):
        if changed:
            self.scan()

    def create_report(self):
        if not self.results:
            self.scan()
        try:
            path = make_report(self.results)
            self.session.open(MessageBox, tr("report_saved", path=path), MessageBox.TYPE_INFO)
        except Exception as error:
            self.session.open(MessageBox, tr("report_failed", error=str(error)), MessageBox.TYPE_ERROR)

    def open_tools(self):
        self.session.open(E2DoctorTools)


def main(session, **kwargs):
    session.open(E2DoctorMain)


def Plugins(**kwargs):
    return [
        PluginDescriptor(name="E2 Doctor", description=tr("subtitle"), where=PluginDescriptor.WHERE_PLUGINMENU, icon="plugin.png", fnc=main),
        PluginDescriptor(name="E2 Doctor", description=tr("subtitle"), where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
    ]

# -----------------------------------------------------------------------------
# E2 Doctor 2.1 - panel diagnostyczny, centrum naprawy i tryb awaryjny
# -----------------------------------------------------------------------------

import ast
import hashlib
import io
import tarfile

from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar

try:
    from enigma import eTimer, getDesktop, RT_HALIGN_RIGHT, RT_VALIGN_TOP
except Exception:
    eTimer = None
    getDesktop = None
    RT_HALIGN_RIGHT = 1
    RT_VALIGN_TOP = 0

TEXTS.update({
    "subtitle": "Centrum diagnostyki i bezpiecznej naprawy Enigma2",
    "footer": "E2 Doctor {version} | Python 3 | by {author}",
    "dashboard": "Panel główny",
    "open": "Otwórz",
    "settings": "Ustawienia",
    "rollback": "Cofnij zmianę",
    "emergency_report": "Raport awaryjny",
})

E2D_STATE_DIR = "/etc/enigma2/e2doctor"
E2D_HISTORY_FILE = os.path.join(E2D_STATE_DIR, "history.json")
E2D_SETTINGS_FILE = os.path.join(E2D_STATE_DIR, "settings.json")
E2D_OPERATIONS_FILE = os.path.join(E2D_STATE_DIR, "operations.json")
E2D_BACKUP_DIR = os.path.join(E2D_STATE_DIR, "backups")
E2D_LAST_NOTICE_FILE = os.path.join(E2D_STATE_DIR, "last_notice")
E2D_CLI = "/usr/bin/e2doctor-report"

DEFAULT_SETTINGS = {
    "auto_scan": True,
    "monitor_enabled": True,
    "monitor_interval_hours": 6,
    "history_limit": 20,
}

MODULE_BY_TITLE = {
    "System / Python": "system",
    "Pamięć flash": "system",
    "Pamięć RAM": "system",
    "Data i czas systemowy": "system",
    "Temperatura": "system",
    "Obciążenie systemu": "system",
    "DNS": "network",
    "Połączenie z internetem": "network",
    "Listy kanałów": "channels",
    "Konfiguracja głowic": "tuners",
    "Wykryte głowice": "tuners",
    "Aktywna głowica i sygnał": "tuners",
    "Nośniki i punkty montowania": "storage",
    "Stan systemów plików": "storage",
    "Menedżer pakietów OPKG": "packages",
    "Spójność pakietów OPKG": "packages",
    "OSCam": "oscam",
    "Crashlogi Enigma2": "crashlogs",
    "Pamięć EPG": "media",
    "Picony": "media",
}

STATUS_RANK = {STATUS_OK: 0, STATUS_INFO: 1, STATUS_WARN: 2, STATUS_ERROR: 3}
STATUS_COLORS = {
    STATUS_OK: 0x0046D369,
    STATUS_INFO: 0x0044B5E5,
    STATUS_WARN: 0x00F0C94D,
    STATUS_ERROR: 0x00F05B62,
}


def ensure_state_dirs():
    try:
        if not os.path.isdir(E2D_STATE_DIR):
            os.makedirs(E2D_STATE_DIR)
        if not os.path.isdir(E2D_BACKUP_DIR):
            os.makedirs(E2D_BACKUP_DIR)
    except Exception:
        pass


def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except Exception:
        return default


def save_json_file(path, value):
    ensure_state_dirs()
    temp = "%s.tmp" % path
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except Exception:
            pass
    os.replace(temp, path)


def load_e2doctor_settings():
    value = load_json_file(E2D_SETTINGS_FILE, {})
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(value, dict):
        settings.update(value)
    try:
        settings["monitor_interval_hours"] = max(1, min(48, int(settings.get("monitor_interval_hours", 6))))
    except Exception:
        settings["monitor_interval_hours"] = 6
    try:
        settings["history_limit"] = max(5, min(50, int(settings.get("history_limit", 20))))
    except Exception:
        settings["history_limit"] = 20
    return settings


def save_e2doctor_settings(settings):
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings or {})
    save_json_file(E2D_SETTINGS_FILE, merged)


def issue_key(item):
    return "%s|%s" % (item.get("module", "other"), item.get("title", ""))


def calculate_health_score(results):
    score = 100
    for item in results:
        status = item.get("status")
        title = item.get("title", "")
        summary = item.get("summary", "").lower()
        if status == STATUS_ERROR:
            penalty = 16
            if "kryty" in summary or title in ("Pamięć flash", "Temperatura"):
                penalty = 22
            score -= penalty
        elif status == STATUS_WARN:
            score -= 6
        elif status == STATUS_INFO and title == "Data i czas systemowy":
            score -= 2
    return max(0, min(100, score))


def health_grade(score):
    if score >= 92:
        return "ZNAKOMITY"
    if score >= 78:
        return "DOBRY"
    if score >= 58:
        return "WYMAGA UWAGI"
    return "KRYTYCZNY"


def result_counts(results):
    return {
        STATUS_OK: len([x for x in results if x.get("status") == STATUS_OK]),
        STATUS_INFO: len([x for x in results if x.get("status") == STATUS_INFO]),
        STATUS_WARN: len([x for x in results if x.get("status") == STATUS_WARN]),
        STATUS_ERROR: len([x for x in results if x.get("status") == STATUS_ERROR]),
    }


def assign_modules(results):
    for item in results:
        if not item.get("module"):
            item["module"] = MODULE_BY_TITLE.get(item.get("title"), "other")
    return results


def compact_snapshot(results):
    counts = result_counts(results)
    score = calculate_health_score(results)
    issues = []
    for item in results:
        if item.get("status") in (STATUS_WARN, STATUS_ERROR):
            issues.append({
                "key": issue_key(item),
                "title": item.get("title", ""),
                "module": item.get("module", "other"),
                "status": item.get("status", STATUS_INFO),
                "summary": item.get("summary", ""),
            })
    distro, version, build = get_image_info()
    return {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": int(time.time()),
        "score": score,
        "grade": health_grade(score),
        "counts": counts,
        "issues": issues,
        "system": "%s %s" % (distro, version),
        "build": build or "nieznana",
        "python": sys.version.split()[0],
    }


def load_history():
    value = load_json_file(E2D_HISTORY_FILE, [])
    return value if isinstance(value, list) else []


def snapshot_signature(snapshot):
    issues = snapshot.get("issues") or []
    normalized = sorted("%s:%s:%s" % (x.get("key"), x.get("status"), x.get("summary")) for x in issues)
    return hashlib.sha256((str(snapshot.get("score")) + "|" + "|".join(normalized)).encode("utf-8", "replace")).hexdigest()


def save_history_snapshot(results, force=False):
    settings = load_e2doctor_settings()
    limit = settings.get("history_limit", 20)
    history = load_history()
    snapshot = compact_snapshot(results)
    if history and not force:
        last = history[0]
        same = snapshot_signature(last) == snapshot_signature(snapshot)
        age = int(time.time()) - int(last.get("epoch", 0) or 0)
        if same and age < 6 * 3600:
            return last
    history.insert(0, snapshot)
    history = history[:limit]
    save_json_file(E2D_HISTORY_FILE, history)
    return snapshot


def compare_snapshots(current, previous):
    if not current or not previous:
        return "To pierwszy zapisany skan E2 Doctor."
    current_map = {x.get("key"): x for x in current.get("issues", [])}
    previous_map = {x.get("key"): x for x in previous.get("issues", [])}
    new_items = []
    resolved = []
    worsened = []
    for key, item in current_map.items():
        old = previous_map.get(key)
        if old is None:
            new_items.append(item)
        elif STATUS_RANK.get(item.get("status"), 0) > STATUS_RANK.get(old.get("status"), 0):
            worsened.append(item)
    for key, item in previous_map.items():
        if key not in current_map:
            resolved.append(item)
    diff = int(current.get("score", 0)) - int(previous.get("score", 0))
    lines = ["Zmiana wyniku: %+d pkt" % diff]
    if new_items:
        lines.append("Nowe problemy: %s" % ", ".join(x.get("title", "") for x in new_items[:4]))
    if worsened:
        lines.append("Pogorszenie: %s" % ", ".join(x.get("title", "") for x in worsened[:4]))
    if resolved:
        lines.append("Rozwiązane: %s" % ", ".join(x.get("title", "") for x in resolved[:4]))
    if not new_items and not worsened and not resolved:
        lines.append("Nie wykryto zmian w problemach.")
    return " | ".join(lines)


def current_change_summary(results):
    history = load_history()
    current = compact_snapshot(results)
    previous = None
    if history:
        if snapshot_signature(history[0]) == snapshot_signature(current) and len(history) > 1:
            previous = history[1]
        else:
            previous = history[0]
    return compare_snapshots(current, previous)


def load_operations():
    value = load_json_file(E2D_OPERATIONS_FILE, [])
    return value if isinstance(value, list) else []


def record_operation(label, operation_type, data, reversible=True):
    operations = load_operations()
    operations.insert(0, {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": int(time.time()),
        "label": label,
        "type": operation_type,
        "data": data or {},
        "reversible": bool(reversible),
        "undone": False,
    })
    save_json_file(E2D_OPERATIONS_FILE, operations[:30])


def last_reversible_operation():
    for operation in load_operations():
        if operation.get("reversible") and not operation.get("undone"):
            return operation
    return None


def mark_operation_undone(target):
    operations = load_operations()
    for operation in operations:
        if operation.get("epoch") == target.get("epoch") and operation.get("type") == target.get("type"):
            operation["undone"] = True
            operation["undone_timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    save_json_file(E2D_OPERATIONS_FILE, operations)


def rollback_last_operation():
    operation = last_reversible_operation()
    if not operation:
        raise RuntimeError("Nie znaleziono operacji, którą można bezpiecznie cofnąć.")
    data = operation.get("data") or {}
    operation_type = operation.get("type")
    if operation_type == "restore_files":
        restored = 0
        for entry in data.get("files", []):
            source = entry.get("backup")
            target = entry.get("original")
            if source and target and os.path.isfile(source):
                parent = os.path.dirname(target)
                if parent and not os.path.isdir(parent):
                    os.makedirs(parent)
                shutil.copy2(source, target)
                restored += 1
        if restored == 0:
            raise RuntimeError("Kopia plików nie jest już dostępna.")
        if eDVBDB is not None and data.get("reload_bouquets"):
            db = eDVBDB.getInstance()
            db.reloadServicelist()
            db.reloadBouquets()
        message = "Przywrócono plików: %d" % restored
    elif operation_type == "rename_plugin":
        disabled = data.get("disabled")
        original = data.get("original")
        if not disabled or not original or not os.path.isdir(disabled):
            raise RuntimeError("Wyłączony katalog wtyczki nie istnieje.")
        if os.path.exists(original):
            raise RuntimeError("Nie można przywrócić wtyczki, ponieważ katalog docelowy już istnieje.")
        os.rename(disabled, original)
        message = "Przywrócono wtyczkę: %s" % os.path.basename(original)
    else:
        raise RuntimeError("Ten typ operacji nie obsługuje cofania.")
    mark_operation_undone(operation)
    return "%s\nOperacja: %s\nData: %s" % (message, operation.get("label", ""), operation.get("timestamp", ""))


def check_system_load(results):
    try:
        load_raw = read_text("/proc/loadavg").strip().split()
        load1 = float(load_raw[0]) if load_raw else 0.0
        load5 = float(load_raw[1]) if len(load_raw) > 1 else 0.0
        load15 = float(load_raw[2]) if len(load_raw) > 2 else 0.0
        cpus = os.cpu_count() or 1
        uptime_seconds = 0.0
        try:
            uptime_seconds = float(read_text("/proc/uptime").split()[0])
        except Exception:
            pass
        uptime_days = uptime_seconds / 86400.0
        details = "Rdzenie CPU: %d\nObciążenie 1/5/15 min: %.2f / %.2f / %.2f\nCzas pracy: %.1f dnia" % (
            cpus, load1, load5, load15, uptime_days
        )
        context = {"load": "%.2f" % load1, "cpus": cpus}
        if load1 > cpus * 3.0:
            add_result(results, STATUS_ERROR, "Obciążenie systemu", "Bardzo wysokie obciążenie CPU: %.2f" % load1, details, "system_load_high", context)
        elif load1 > cpus * 1.8:
            add_result(results, STATUS_WARN, "Obciążenie systemu", "Wysokie obciążenie CPU: %.2f" % load1, details, "system_load_high", context)
        else:
            add_result(results, STATUS_OK, "Obciążenie systemu", "Obciążenie 1 min: %.2f" % load1, details)
    except Exception as error:
        add_result(results, STATUS_INFO, "Obciążenie systemu", "Nie udało się odczytać obciążenia", str(error))


def parse_nim_sockets():
    content = read_text("/proc/bus/nim_sockets")
    sockets = []
    current = None
    for raw in content.splitlines():
        line = raw.strip()
        match = re.match(r"NIM Socket\s+(\d+):", line, re.IGNORECASE)
        if match:
            if current:
                sockets.append(current)
            current = {"number": match.group(1)}
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip().lower().replace(" ", "_")] = value.strip()
    if current:
        sockets.append(current)
    return sockets


def check_tuner_hardware(results):
    sockets = parse_nim_sockets()
    if not sockets:
        add_result(results, STATUS_WARN, "Wykryte głowice", "System nie udostępnił listy głowic", "Plik /proc/bus/nim_sockets jest pusty lub niedostępny.", "tuner_hardware_missing")
        return
    lines = []
    for socket_item in sockets:
        number = socket_item.get("number", "?")
        tuner_type = socket_item.get("type", "nieznany")
        name = socket_item.get("name", "nieznana")
        frontend = socket_item.get("frontend_device", "?")
        lines.append("Głowica %s: %s | %s | frontend %s" % (number, tuner_type, name, frontend))
    add_result(results, STATUS_OK, "Wykryte głowice", "Liczba wykrytych głowic: %d" % len(sockets), "\n".join(lines))


def check_live_tuner(results, session=None):
    if session is None:
        add_result(results, STATUS_INFO, "Aktywna głowica i sygnał", "Brak sesji Enigma2 do odczytu sygnału", "Uruchom diagnostykę z panelu E2 Doctor podczas oglądania kanału.")
        return
    try:
        service = session.nav.getCurrentService()
        reference = session.nav.getCurrentlyPlayingServiceReference()
        ref_text = reference.toString() if reference is not None else "brak"
        if service is None:
            add_result(results, STATUS_INFO, "Aktywna głowica i sygnał", "Nie jest odtwarzany kanał", "Brak aktywnej usługi.\nReferencja: %s" % ref_text)
            return
        frontend = service.frontendInfo()
        data = frontend.getAll(True) if frontend is not None else None
        if not data:
            add_result(results, STATUS_INFO, "Aktywna głowica i sygnał", "Aktualna usługa nie korzysta z głowicy DVB", "Może to być kanał IPTV, nagranie lub odtwarzany plik.\nReferencja: %s" % ref_text)
            return
        locked = data.get("tuner_locked")
        if locked is None:
            locked = data.get("lock")
        snr = data.get("snr")
        snr_db = data.get("snr_db")
        agc = data.get("agc")
        ber = data.get("ber")
        tuner_number = data.get("tuner_number", data.get("frontend_number", "?"))
        system = data.get("system", data.get("tuner_type", "DVB"))
        frequency = data.get("frequency", "?")
        symbol_rate = data.get("symbol_rate", "?")
        lines = [
            "Aktywna głowica: %s" % tuner_number,
            "System: %s" % system,
            "LOCK: %s" % ("tak" if locked else "nie"),
            "SNR: %s" % (snr_db if snr_db is not None else snr if snr is not None else "brak danych"),
            "AGC: %s" % (agc if agc is not None else "brak danych"),
            "BER: %s" % (ber if ber is not None else "brak danych"),
            "Częstotliwość: %s" % frequency,
            "Symbol rate: %s" % symbol_rate,
            "Referencja: %s" % ref_text,
        ]
        summary = "Głowica %s | LOCK: %s" % (tuner_number, "tak" if locked else "nie")
        if locked is False:
            add_result(results, STATUS_WARN, "Aktywna głowica i sygnał", summary, "\n".join(lines), "tuner_no_lock")
        else:
            add_result(results, STATUS_OK, "Aktywna głowica i sygnał", summary, "\n".join(lines))
    except Exception as error:
        add_result(results, STATUS_INFO, "Aktywna głowica i sygnał", "Odczyt parametrów sygnału jest niedostępny", str(error))


def check_storage_health(results):
    warnings = []
    details = []
    for device, mountpoint, fstype, options in get_mounts():
        if mountpoint == "/" or mountpoint.startswith("/media/") or mountpoint == "/boot":
            try:
                stats = os.statvfs(mountpoint)
                total = stats.f_blocks * stats.f_frsize
                free = stats.f_bavail * stats.f_frsize
                percent = (free * 100.0 / total) if total else 0.0
                details.append("%s | %s | %s | wolne %s (%.1f%%)" % (device, mountpoint, fstype, format_bytes(free), percent))
                if "ro" in options.split(","):
                    warnings.append("%s jest tylko do odczytu" % mountpoint)
                if mountpoint.startswith("/media/") and total and (percent < 3.0 or free < 256 * 1024 * 1024):
                    warnings.append("mało miejsca na %s" % mountpoint)
            except Exception as error:
                details.append("%s | %s | błąd odczytu: %s" % (device, mountpoint, error))
    code, dmesg, _ = run_command("dmesg 2>/dev/null | tail -n 500", timeout=5)
    kernel_findings = []
    if code == 0 and dmesg:
        patterns = [
            r"I/O error, dev (?!mmcblk0rpmb)[^\n]+",
            r"EXT4-fs error[^\n]+",
            r"Buffer I/O error[^\n]+",
            r"FAT-fs \([^\)]+\): Volume was not properly unmounted[^\n]*",
            r"Remounting filesystem read-only[^\n]*",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, dmesg, re.IGNORECASE):
                text = match if isinstance(match, str) else " ".join(match)
                if text and text not in kernel_findings:
                    kernel_findings.append(text[:220])
    if kernel_findings:
        warnings.extend(kernel_findings[:4])
        details.extend(["Log kernela: %s" % item for item in kernel_findings[:8]])
    if not details:
        details.append("Nie udało się odczytać informacji o systemach plików.")
    if warnings:
        add_result(results, STATUS_WARN, "Stan systemów plików", "Wykryto ostrzeżenia dotyczące nośników: %d" % len(warnings), "\n".join(details), "storage_warning", {"errors": "; ".join(warnings[:6])})
    else:
        add_result(results, STATUS_OK, "Stan systemów plików", "Nie wykryto bieżących błędów nośników", "\n".join(details))


def parse_opkg_status():
    content = read_text("/var/lib/opkg/status")
    packages = []
    current = {}
    for line in content.splitlines() + [""]:
        if not line.strip():
            if current:
                packages.append(current)
                current = {}
            continue
        if line.startswith(" ") and current:
            last_key = current.get("_last")
            if last_key:
                current[last_key] = current.get(last_key, "") + " " + line.strip()
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            current[key] = value.strip()
            current["_last"] = key
    for package in packages:
        package.pop("_last", None)
    return packages


def check_opkg_integrity(results):
    packages = parse_opkg_status()
    if not packages:
        add_result(results, STATUS_INFO, "Spójność pakietów OPKG", "Nie można przeanalizować bazy pakietów", "Brak czytelnych wpisów w /var/lib/opkg/status.")
        return
    broken = []
    for package in packages:
        status = package.get("status", "")
        if status and status != "install ok installed":
            broken.append("%s: %s" % (package.get("package", "nieznany"), status))
    details = "Zainstalowane wpisy: %d\nNieprawidłowe stany: %d" % (len(packages), len(broken))
    if broken:
        details += "\n\n" + "\n".join(broken[:40])
        add_result(results, STATUS_ERROR, "Spójność pakietów OPKG", "Wykryto pakiety w niepełnym stanie: %d" % len(broken), details, "opkg_broken", {"packages": ", ".join(broken[:10])})
    else:
        add_result(results, STATUS_OK, "Spójność pakietów OPKG", "Baza pakietów nie zawiera niepełnych instalacji", details)


def extract_traceback_context(content):
    frames = []
    pattern = re.compile(r'^\s*File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+([^\n]+)', re.MULTILINE)
    for match in pattern.finditer(content):
        frames.append({"file": match.group(1), "line": match.group(2), "function": match.group(3).strip()})
    exception = ""
    error_message = ""
    exception_pattern = re.compile(r'^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):\s*(.*)$', re.MULTILINE)
    matches = list(exception_pattern.finditer(content))
    if matches:
        exception = matches[-1].group(1)
        error_message = matches[-1].group(2).strip()
    culprit = None
    for frame in reversed(frames):
        if "/Plugins/Extensions/" in frame.get("file", "") or "/Plugins/SystemPlugins/" in frame.get("file", ""):
            culprit = frame
            break
    if culprit is None and frames:
        culprit = frames[-1]
    plugin = "nie ustalono"
    plugin_path = ""
    if culprit:
        match = re.search(r"/(Plugins/(?:Extensions|SystemPlugins)/([^/]+))", culprit.get("file", ""))
        if match:
            plugin = match.group(2)
            prefix = culprit.get("file", "").split("/Plugins/", 1)[0]
            plugin_path = os.path.join(prefix, match.group(1))
    return {
        "frames": frames,
        "culprit": culprit or {},
        "exception": exception,
        "error": error_message,
        "plugin": plugin,
        "plugin_path": plugin_path,
    }


def analyze_crashlog(content):
    context = extract_traceback_context(content)
    rules = [
        (r"ModuleNotFoundError:\s*No module named ['\"]?([^'\"\s]+)", "Brak modułu Python: {0}", "crash_python_module", "module"),
        (r"No module named ['\"]?([^'\"\s]+)", "Brak modułu Python: {0}", "crash_python_module", "module"),
        (r"ImportError:\s*(.+)", "Błąd importu: {0}", "crash_import", "error"),
        (r"SkinError:\s*(.+)", "Błąd skina: {0}", "crash_skin", "error"),
        (r"No space left on device", "Brak wolnego miejsca na urządzeniu", "crash_no_space", None),
        (r"SyntaxError:\s*(.+)", "Błąd składni Python: {0}", "crash_python_error", "error"),
        (r"IndentationError:\s*(.+)", "Błąd wcięć Python: {0}", "crash_python_error", "error"),
        (r"TypeError:\s*(.+)", "Błąd typu danych: {0}", "crash_python_error", "error"),
        (r"RuntimeError:\s*(.+)", "Błąd wykonania: {0}", "crash_python_error", "error"),
        (r"KeyError:\s*(.+)", "Brak klucza w danych wtyczki: {0}", "crash_python_error", "error"),
        (r"IndexError:\s*(.+)", "Błąd indeksu lub listy we wtyczce: {0}", "crash_python_error", "error"),
        (r"AttributeError:\s*(.+)", "Błąd zgodności wtyczki lub API: {0}", "crash_python_error", "error"),
        (r"Permission denied", "Brak uprawnień do pliku lub katalogu", "crash_permission", None),
        (r"Read-only file system", "System plików jest zamontowany tylko do odczytu", "crash_readonly", None),
        (r"certificate verify failed", "Błąd weryfikacji certyfikatu HTTPS", "crash_ssl", None),
        (r"Network is unreachable", "Sieć jest niedostępna", "crash_network", None),
        (r"Segmentation fault", "Błąd segmentacji składnika systemowego", "crash_segfault", None),
    ]
    findings = []
    seen = set()
    for pattern, message, solution_id, context_key in rules:
        match = re.search(pattern, content, re.IGNORECASE)
        if not match:
            continue
        value = ""
        if match.lastindex:
            try:
                value = match.group(1).strip()[:240]
            except Exception:
                value = ""
        text = message.format(value) if "{0}" in message else message
        if text in seen:
            continue
        item_context = {
            "plugin": context.get("plugin", "nie ustalono"),
            "plugin_path": context.get("plugin_path", ""),
            "file": context.get("culprit", {}).get("file", "nie ustalono"),
            "line": context.get("culprit", {}).get("line", "nie ustalono"),
            "function": context.get("culprit", {}).get("function", "nie ustalono"),
            "exception": context.get("exception", ""),
            "error": value or context.get("error") or text,
        }
        if context_key:
            item_context[context_key] = value or "nie ustalono"
        findings.append({"code": solution_id, "message": text, "solution_id": solution_id, "context": item_context})
        seen.add(text)
    if not findings and context.get("exception"):
        text = "%s: %s" % (context.get("exception"), context.get("error") or "brak opisu")
        findings.append({
            "code": "crash_generic",
            "message": text[:260],
            "solution_id": "crash_generic",
            "context": {
                "plugin": context.get("plugin", "nie ustalono"),
                "plugin_path": context.get("plugin_path", ""),
                "file": context.get("culprit", {}).get("file", "nie ustalono"),
                "line": context.get("culprit", {}).get("line", "nie ustalono"),
                "function": context.get("culprit", {}).get("function", "nie ustalono"),
                "exception": context.get("exception", ""),
                "error": context.get("error") or text,
            },
        })
    return findings


def crash_fingerprint(finding):
    context = finding.get("context") or {}
    raw = "%s|%s|%s|%s" % (
        finding.get("solution_id", ""), context.get("plugin", ""), context.get("file", ""), context.get("error", "")
    )
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


def check_crashlogs(results):
    logs = find_crashlogs()
    if not logs:
        add_result(results, STATUS_OK, "Crashlogi Enigma2", "Nie znaleziono crashlogów", "Sprawdzono standardowe katalogi logów.")
        return
    analyzed = []
    for path in logs[:8]:
        content = read_text(path, limit=900000)
        findings = analyze_crashlog(content)
        if findings:
            analyzed.append((path, findings[0], content))
    newest = logs[0]
    content = read_text(newest, limit=900000)
    findings = analyze_crashlog(content)
    modified = os.path.getmtime(newest)
    stamp = datetime.datetime.fromtimestamp(modified).strftime("%Y-%m-%d %H:%M:%S")
    age_hours = max(0.0, (time.time() - modified) / 3600.0)
    has_traceback = "Traceback (most recent call last)" in content or "Segmentation fault" in content or "FATAL" in content
    if findings:
        first = findings[0]
        fingerprint = crash_fingerprint(first)
        repeat_count = len([1 for _, finding, _ in analyzed if crash_fingerprint(finding) == fingerprint])
        context = dict(first.get("context") or {})
        context.update({"log_path": newest, "log_count": len(logs), "age_hours": "%.1f" % age_hours, "repeat_count": repeat_count})
        culprit_lines = []
        if context.get("plugin") and context.get("plugin") != "nie ustalono":
            culprit_lines.append("Podejrzana wtyczka: %s" % context.get("plugin"))
        if context.get("file") and context.get("file") != "nie ustalono":
            culprit_lines.append("Plik: %s" % context.get("file"))
        if context.get("line") and context.get("line") != "nie ustalono":
            culprit_lines.append("Linia: %s | funkcja: %s" % (context.get("line"), context.get("function", "nie ustalono")))
        details = "Najnowszy log: %s\nOstatnia modyfikacja: %s\nWykryte logi: %d\nPowtórzenia tego błędu: %d\nWiek logu: %.1f godz.\n%s\n\nRozpoznanie:\n%s" % (
            newest, stamp, len(logs), repeat_count, age_hours, "\n".join(culprit_lines), first.get("message")
        )
        safe_action = None
        plugin_path = context.get("plugin_path", "")
        if plugin_path and os.path.isdir(plugin_path) and os.path.basename(plugin_path) != "E2Doctor" and "/Plugins/Extensions/" in plugin_path:
            safe_action = "disable_suspect_plugin"
        status = STATUS_ERROR if has_traceback and age_hours <= 72 else STATUS_WARN
        add_result(results, status, "Crashlogi Enigma2", first.get("message"), details, first.get("solution_id"), context, safe_action)
    else:
        details = "Najnowszy log: %s\nOstatnia modyfikacja: %s\nLiczba logów: %d\nNie rozpoznano jednoznacznego wzorca." % (newest, stamp, len(logs))
        status = STATUS_WARN if has_traceback and age_hours <= 72 else STATUS_INFO
        add_result(results, status, "Crashlogi Enigma2", "Crashlogi: %d, brak jednoznacznego rozpoznania" % len(logs), details, "crash_generic", {"log_path": newest})


def get_solution(item):
    solution_id = item.get("solution_id")
    raw = SOLUTIONS.get(solution_id, {}) if solution_id else {}
    context = dict(item.get("context") or {})
    context.setdefault("title", item.get("title", ""))
    context.setdefault("summary", item.get("summary", ""))
    context.setdefault("plugin", "nie ustalono")
    context.setdefault("module", "nie ustalono")
    context.setdefault("error", item.get("summary", "nie ustalono"))
    context.setdefault("file", "nie ustalono")
    context.setdefault("line", "nie ustalono")
    context.setdefault("function", "nie ustalono")
    solution = {}
    for key, value in raw.items():
        if isinstance(value, list):
            solution[key] = [safe_format(entry, context) for entry in value]
        else:
            solution[key] = safe_format(value, context)
    if item.get("safe_action"):
        solution["action"] = item.get("safe_action")
    if solution.get("action") == "disable_suspect_plugin":
        solution["action_label"] = "Tymczasowo wyłącz wtyczkę"
    return solution


def run_all_checks(session=None):
    results = []
    checks = [
        check_system, check_flash, check_memory, check_time, check_system_load,
        check_network, check_opkg, check_opkg_integrity, check_bouquets,
        check_tuner_config, check_tuner_hardware, check_mounts, check_storage_health,
        check_epg, check_picons, check_oscam, check_crashlogs, check_temperature,
    ]
    for check in checks:
        try:
            check(results)
        except Exception as error:
            add_result(results, STATUS_ERROR, check.__name__, "Moduł diagnostyczny zakończył się błędem", "%s\n%s" % (error, traceback.format_exc()), "diagnostic_error", {"error": str(error), "module": check.__name__})
    try:
        check_live_tuner(results, session)
    except Exception as error:
        add_result(results, STATUS_INFO, "Aktywna głowica i sygnał", "Nie udało się wykonać odczytu", str(error))
    return assign_modules(results)


def create_backup(paths, label):
    ensure_state_dirs()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(E2D_BACKUP_DIR, "%s_%s" % (label, timestamp))
    os.makedirs(backup_dir)
    copied = []
    for path in paths:
        if os.path.isfile(path):
            target = os.path.join(backup_dir, os.path.basename(path))
            shutil.copy2(path, target)
            copied.append({"original": path, "backup": target})
    if not copied:
        try:
            os.rmdir(backup_dir)
        except Exception:
            pass
        raise RuntimeError("Nie znaleziono plików do wykonania kopii")
    save_json_file(os.path.join(backup_dir, "manifest.json"), {"label": label, "timestamp": timestamp, "files": copied})
    return backup_dir, copied


def repair_missing_bouquet_refs():
    base = "/etc/enigma2"
    indexes = [path for path in (os.path.join(base, "bouquets.tv"), os.path.join(base, "bouquets.radio")) if os.path.isfile(path)]
    missing_pairs = find_missing_bouquet_refs()
    missing_set = set((index, filename) for index, filename in missing_pairs)
    if not missing_set:
        return 0, "Nie znaleziono brakujących odwołań."
    backup_dir, copied = create_backup(indexes, "bukiety")
    pattern = re.compile(r'FROM BOUQUET\s+"([^"]+)"', re.IGNORECASE)
    removed = 0
    for index_path in indexes:
        content = read_text(index_path)
        output = []
        for line in content.splitlines(True):
            match = pattern.search(line)
            if match and (index_path, match.group(1)) in missing_set:
                removed += 1
                continue
            output.append(line)
        write_text_atomic(index_path, "".join(output))
    if eDVBDB is not None:
        db = eDVBDB.getInstance()
        db.reloadServicelist()
        db.reloadBouquets()
    record_operation(
        "Naprawa odwołań do bukietów",
        "restore_files",
        {"backup_dir": backup_dir, "files": copied, "reload_bouquets": True},
        True,
    )
    return removed, backup_dir


def disable_suspect_plugin(context):
    plugin_path = os.path.realpath((context or {}).get("plugin_path", ""))
    extensions_root = os.path.realpath("/usr/lib/enigma2/python/Plugins/Extensions")
    if not plugin_path or not plugin_path.startswith(extensions_root + os.sep):
        raise RuntimeError("Nie ustalono bezpiecznej ścieżki wtyczki Extensions.")
    if os.path.basename(plugin_path) == "E2Doctor":
        raise RuntimeError("E2 Doctor nie może wyłączyć własnego katalogu.")
    if not os.path.isdir(plugin_path):
        raise RuntimeError("Katalog podejrzanej wtyczki nie istnieje.")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    disabled = "%s.disabled_by_e2doctor_%s" % (plugin_path, timestamp)
    os.rename(plugin_path, disabled)
    record_operation(
        "Tymczasowe wyłączenie wtyczki %s" % os.path.basename(plugin_path),
        "rename_plugin",
        {"original": plugin_path, "disabled": disabled},
        True,
    )
    return plugin_path, disabled


def make_report(results):
    now = datetime.datetime.now()
    path = os.path.join(choose_writable_report_dir(), "E2Doctor_Raport_%s.txt" % now.strftime("%Y%m%d_%H%M%S"))
    distro, version, build = get_image_info()
    score = calculate_health_score(results)
    counts = result_counts(results)
    lines = [
        "RAPORT DIAGNOSTYCZNY E2 DOCTOR 2.3",
        "=" * 78,
        "Utworzono: %s" % now.strftime("%Y-%m-%d %H:%M:%S"),
        "Wersja wtyczki: %s" % PLUGIN_VERSION,
        "Autor: %s" % PLUGIN_AUTHOR,
        "System: %s %s" % (distro, version),
        "Kompilacja: %s" % (build or "nieznana"),
        "Python: %s" % sys.version.replace("\n", " "),
        "Architektura: %s" % (os.uname().machine if hasattr(os, "uname") else "nieznana"),
        "",
        "WYNIK DIAGNOSTYKI: %d/100 — %s" % (score, health_grade(score)),
        "OK: %d | Informacje: %d | Ostrzeżenia: %d | Błędy: %d" % (
            counts.get(STATUS_OK, 0), counts.get(STATUS_INFO, 0), counts.get(STATUS_WARN, 0), counts.get(STATUS_ERROR, 0)
        ),
        "Zmiany: %s" % current_change_summary(results),
        "",
        "Raport nie zawiera haseł, linii serwerów OSCam ani pełnego pliku ustawień.",
        "",
    ]
    for item in results:
        lines.extend([
            "=" * 78,
            "%s %s" % (status_prefix(item.get("status")), item.get("title", "")),
            item.get("summary", ""),
            "-" * 78,
            item.get("details", ""),
        ])
        if item.get("status") in (STATUS_WARN, STATUS_ERROR):
            lines.extend(["", "MOŻLIWE ROZWIĄZANIE", "-" * 78, build_solution_text(item, include_technical=False)])
        lines.append("")
    code, uptime, _ = run_command("uptime", timeout=3)
    if code == 0:
        lines.extend(["=" * 78, "Czas pracy systemu", uptime, ""])
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def python3_compatibility_report():
    roots = [
        "/usr/lib/enigma2/python/Plugins/Extensions",
        "/usr/lib/enigma2/python/Plugins/SystemPlugins",
    ]
    patterns = [
        (re.compile(r"\bimport\s+urllib2\b|\bfrom\s+urllib2\b"), "moduł urllib2 z Python 2"),
        (re.compile(r"\bxrange\s*\("), "funkcja xrange z Python 2"),
        (re.compile(r"\.iteritems\s*\("), "metoda iteritems z Python 2"),
        (re.compile(r"\bimport\s+ConfigParser\b|\bfrom\s+ConfigParser\b"), "moduł ConfigParser z Python 2"),
        (re.compile(r"\bbasestring\b"), "typ basestring z Python 2"),
        (re.compile(r"\bexcept\s+[^:\n,]+,\s*[A-Za-z_]\w*\s*:"), "stara składnia except"),
        (re.compile(r"^\s*print\s+[^\(\n]", re.MULTILINE), "stara składnia print"),
    ]
    syntax_errors = []
    heuristics = []
    pyo_files = []
    scanned = 0
    for root in roots:
        if not os.path.isdir(root):
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if not name.startswith(".") and name != "E2Doctor"]
            for name in files:
                path = os.path.join(current, name)
                if name.endswith(".pyo"):
                    pyo_files.append(path)
                    continue
                if not name.endswith(".py"):
                    continue
                scanned += 1
                if scanned > 3500:
                    break
                try:
                    if os.path.getsize(path) > 1024 * 1024:
                        continue
                    content = read_text(path)
                    try:
                        ast.parse(content, filename=path)
                    except SyntaxError as error:
                        syntax_errors.append("%s:%s — %s" % (path, error.lineno or "?", error.msg))
                    for pattern, description in patterns:
                        match = pattern.search(content)
                        if match:
                            line = content.count("\n", 0, match.start()) + 1
                            heuristics.append("%s:%d — %s" % (path, line, description))
                except Exception:
                    pass
            if scanned > 3500:
                break
        if scanned > 3500:
            break
    lines = [
        "KONTROLA ZGODNOŚCI WTYCZEK Z PYTHON 3",
        "",
        "Przeskanowane pliki Python: %d" % scanned,
        "Błędy składni wykryte przez Python 3: %d" % len(syntax_errors),
        "Podejrzane konstrukcje Python 2: %d" % len(heuristics),
        "Pliki .pyo: %d" % len(pyo_files),
        "",
    ]
    if syntax_errors:
        lines.extend(["BŁĘDY SKŁADNI", "-"])
        lines.extend(syntax_errors[:80])
        lines.append("")
    if heuristics:
        lines.extend(["PODEJRZANE KONSTRUKCJE", "-"])
        lines.extend(heuristics[:120])
        lines.append("")
    if pyo_files:
        lines.extend(["POZOSTAŁOŚCI PYTHON 2 (.pyo)", "-"])
        lines.extend(pyo_files[:60])
        lines.append("")
    if not syntax_errors and not heuristics and not pyo_files:
        lines.append("Nie wykryto typowych problemów zgodności z Pythonem 3.")
    lines.extend([
        "",
        "Uwaga: wykrycie konstrukcji jest analizą heurystyczną. Niektóre wtyczki zawierają warstwy zgodności i mogą działać poprawnie.",
        "E2 Doctor nie usuwa ani nie modyfikuje zeskanowanych plików.",
    ])
    return "\n".join(lines)


def find_ipk_files():
    roots = ["/tmp"]
    for _, mountpoint, _, _ in get_mounts():
        if mountpoint.startswith("/media/") and mountpoint not in roots:
            roots.append(mountpoint)
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip("/").count("/")
        for current, dirs, files in os.walk(root):
            depth = current.rstrip("/").count("/") - base_depth
            if depth >= 3:
                dirs[:] = []
            for name in files:
                if name.lower().endswith(".ipk"):
                    path = os.path.join(current, name)
                    try:
                        found.append((os.path.getmtime(path), path))
                    except Exception:
                        found.append((0, path))
            if len(found) >= 150:
                break
        if len(found) >= 150:
            break
    return [path for _, path in sorted(found, reverse=True)]


def read_ar_members(path):
    members = {}
    with open(path, "rb") as handle:
        if handle.read(8) != b"!<arch>\n":
            raise RuntimeError("Plik nie ma prawidłowego nagłówka archiwum IPK/ar.")
        while True:
            header = handle.read(60)
            if not header:
                break
            if len(header) != 60 or header[58:60] != b"`\n":
                raise RuntimeError("Uszkodzony nagłówek archiwum IPK.")
            name = header[0:16].decode("utf-8", "replace").strip().rstrip("/")
            size_text = header[48:58].decode("ascii", "replace").strip()
            try:
                size = int(size_text)
            except Exception:
                raise RuntimeError("Nieprawidłowy rozmiar elementu IPK.")
            data = handle.read(size)
            if size % 2:
                handle.read(1)
            members[name] = data
    return members


def parse_control_fields(text):
    fields = {}
    current = None
    for line in text.splitlines():
        if line.startswith(" ") and current:
            fields[current] = fields.get(current, "") + " " + line.strip()
        elif ":" in line:
            key, value = line.split(":", 1)
            current = key.strip().lower()
            fields[current] = value.strip()
    return fields


def accepted_opkg_architectures():
    values = {"all", "noarch"}
    for path in glob.glob("/etc/opkg/*.conf") + ["/etc/opkg/arch.conf"]:
        for line in read_text(path).splitlines():
            match = re.match(r"\s*arch\s+(\S+)\s+", line)
            if match:
                values.add(match.group(1))
    try:
        values.add(os.uname().machine)
    except Exception:
        pass
    return values


def installed_package_names():
    return {item.get("package") for item in parse_opkg_status() if item.get("package")}


def normalize_dependency_name(raw):
    value = re.sub(r"\([^\)]*\)", "", raw).strip()
    value = value.split("|")[0].strip()
    return value


def analyze_ipk(path):
    members = read_ar_members(path)
    control_name = next((name for name in members if name.startswith("control.tar")), None)
    data_name = next((name for name in members if name.startswith("data.tar")), None)
    if not control_name or not data_name:
        raise RuntimeError("Paczka nie zawiera control.tar ani data.tar.")
    try:
        control_tar = tarfile.open(fileobj=io.BytesIO(members[control_name]), mode="r:*")
    except Exception as error:
        raise RuntimeError("Nie można odczytać %s: %s" % (control_name, error))
    control_text = ""
    scripts = []
    for member in control_tar.getmembers():
        name = member.name.lstrip("./")
        if name == "control" and member.isfile():
            extracted = control_tar.extractfile(member)
            if extracted:
                control_text = extracted.read().decode("utf-8", "replace")
        if name in ("preinst", "postinst", "prerm", "postrm") and member.isfile():
            scripts.append(name)
    fields = parse_control_fields(control_text)
    try:
        data_tar = tarfile.open(fileobj=io.BytesIO(members[data_name]), mode="r:*")
    except Exception as error:
        raise RuntimeError("Nie można odczytać %s: %s" % (data_name, error))
    files = [member for member in data_tar.getmembers() if member.isfile() or member.issym() or member.islnk()]
    paths = ["/" + member.name.lstrip("./") for member in files]
    risky_paths = []
    risk_prefixes = (
        "/etc/enigma2/settings", "/etc/network/", "/etc/fstab", "/boot/", "/lib/modules/",
        "/etc/init.d/", "/usr/bin/", "/usr/sbin/", "/etc/rc", "/etc/passwd", "/etc/shadow",
    )
    for item in paths:
        if item == "/etc/enigma2/settings" or item.startswith(risk_prefixes):
            risky_paths.append(item)
    py2_findings = []
    py_files = 0
    for member in files:
        if not member.isfile() or not member.name.endswith(".py") or member.size > 1024 * 1024:
            continue
        py_files += 1
        try:
            extracted = data_tar.extractfile(member)
            content = extracted.read().decode("utf-8", "replace") if extracted else ""
            try:
                ast.parse(content, filename=member.name)
            except SyntaxError as error:
                py2_findings.append("%s:%s — błąd składni: %s" % (member.name, error.lineno or "?", error.msg))
            for pattern, description in [
                (r"\bimport\s+urllib2\b", "urllib2"),
                (r"\bxrange\s*\(", "xrange"),
                (r"\.iteritems\s*\(", "iteritems"),
                (r"\bexcept\s+[^:\n,]+,\s*[A-Za-z_]\w*\s*:", "stara składnia except"),
            ]:
                if re.search(pattern, content):
                    py2_findings.append("%s — %s" % (member.name, description))
        except Exception:
            pass
    package_arch = fields.get("architecture", "nieznana")
    accepted = accepted_opkg_architectures()
    architecture_ok = package_arch in accepted or package_arch in ("all", "noarch", "nieznana")
    depends = [normalize_dependency_name(x) for x in fields.get("depends", "").split(",") if normalize_dependency_name(x)]
    installed = installed_package_names()
    missing_dependencies = [dep for dep in depends if dep not in installed]
    installed_size = 0
    for member in files:
        try:
            installed_size += int(member.size or 0)
        except Exception:
            pass
    root_free = 0
    try:
        stats = os.statvfs("/")
        root_free = stats.f_bavail * stats.f_frsize
    except Exception:
        pass
    flags = []
    risk_points = 0
    if scripts:
        flags.append("Paczka zawiera skrypty instalacyjne: %s" % ", ".join(scripts))
        risk_points += 20
    if risky_paths:
        flags.append("Paczka ingeruje w wrażliwe ścieżki systemowe.")
        risk_points += min(45, 12 + len(risky_paths) * 4)
    if not architecture_ok:
        flags.append("Architektura paczki nie występuje w konfiguracji OPKG tunera.")
        risk_points += 40
    if py2_findings:
        flags.append("Wykryto możliwą niezgodność z Pythonem 3.")
        risk_points += 30
    if root_free and installed_size > root_free * 0.8:
        flags.append("Paczka może zająć większość dostępnego miejsca we flashu.")
        risk_points += 35
    risk_points = min(100, risk_points)
    risk_label = "NISKIE" if risk_points < 25 else "ŚREDNIE" if risk_points < 55 else "WYSOKIE"
    lines = [
        "E2 SAFE INSTALLER — ANALIZA PACZKI IPK",
        "",
        "Plik: %s" % path,
        "Rozmiar paczki: %s" % format_bytes(os.path.getsize(path)),
        "",
        "Pakiet: %s" % fields.get("package", "nieznany"),
        "Wersja: %s" % fields.get("version", "nieznana"),
        "Architektura: %s (%s)" % (package_arch, "zgodna" if architecture_ok else "NIEZGODNA"),
        "Opis: %s" % fields.get("description", "brak"),
        "Zależności: %s" % (", ".join(depends) if depends else "brak zadeklarowanych"),
        "Brakujące zależności według bazy OPKG: %s" % (", ".join(missing_dependencies) if missing_dependencies else "nie wykryto"),
        "Pliki w paczce: %d" % len(files),
        "Pliki Python: %d" % py_files,
        "Szacowany rozmiar po rozpakowaniu: %s" % format_bytes(installed_size),
        "Wolne miejsce we flashu: %s" % format_bytes(root_free),
        "",
        "OCENA RYZYKA: %s (%d/100)" % (risk_label, risk_points),
        "",
    ]
    if flags:
        lines.extend(["OSTRZEŻENIA", "-"])
        lines.extend("- %s" % flag for flag in flags)
        lines.append("")
    if risky_paths:
        lines.extend(["WRAŻLIWE ŚCIEŻKI", "-"])
        lines.extend(risky_paths[:100])
        lines.append("")
    if scripts:
        lines.extend(["SKRYPTY INSTALACYJNE", "-", ", ".join(scripts), ""])
    if py2_findings:
        lines.extend(["ZGODNOŚĆ Z PYTHONEM 3", "-"])
        lines.extend(py2_findings[:100])
        lines.append("")
    lines.extend(["PIERWSZE PLIKI PACZKI", "-"])
    lines.extend(paths[:120])
    lines.extend([
        "",
        "E2 Doctor tylko analizuje paczkę. Nie instaluje jej i nie modyfikuje systemu.",
        "Paczki z wysokim ryzykiem instaluj wyłącznie po wykonaniu pełnej kopii systemu.",
    ])
    return "\n".join(lines)


def emergency_report():
    if not os.path.exists(E2D_CLI):
        raise RuntimeError("Nie znaleziono narzędzia %s" % E2D_CLI)
    code, output, error = run_command(E2D_CLI, timeout=30)
    if code != 0:
        raise RuntimeError(error or output or "Kod błędu %s" % code)
    path = output.strip().splitlines()[-1] if output.strip() else ""
    if not path or not os.path.isfile(path):
        raise RuntimeError("Narzędzie nie zwróciło ścieżki raportu.")
    return path


def get_desktop_size():
    try:
        size = getDesktop(0).size()
        return size.width(), size.height()
    except Exception:
        return 1280, 720


DESKTOP_WIDTH, DESKTOP_HEIGHT = get_desktop_size()
E2D_FHD = DESKTOP_WIDTH >= 1800 and DESKTOP_HEIGHT >= 1000
E2D_UI_W = 1580 if E2D_FHD else 1180
E2D_UI_H = 900 if E2D_FHD else 680
E2D_MARGIN = 48 if E2D_FHD else 34
E2D_LIST_W = E2D_UI_W - (E2D_MARGIN * 2)
E2D_ITEM_H = 82 if E2D_FHD else 62
E2D_FONT_TITLE = 34 if E2D_FHD else 27
E2D_FONT_BODY = 28 if E2D_FHD else 22
E2D_FONT_SMALL = 23 if E2D_FHD else 18
E2D_LOGO_SIZE = 132 if E2D_FHD else 96
E2D_LOGO_PATH = os.path.join(PLUGIN_PATH, "logo.png")


def dashboard_skin():
    w = E2D_UI_W
    h = E2D_UI_H
    m = E2D_MARGIN
    header_h = 178 if E2D_FHD else 164
    summary_y = header_h + 16
    summary_h = 100 if E2D_FHD else 76
    list_y = summary_y + summary_h + 14
    footer_h = 72 if E2D_FHD else 54
    footer_y = h - footer_h - 18
    list_h = footer_y - list_y - 10
    logo = E2D_LOGO_SIZE
    score_x = w - m - (310 if E2D_FHD else 230)
    score_w = 310 if E2D_FHD else 230
    title_x = m + logo + 26
    title_w = score_x - title_x - 24
    card_gap = 12
    card_w = int((w - 2 * m - 3 * card_gap) / 4)
    return """
    <screen name="E2DoctorDashboard" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor" backgroundColor="#0D151C" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,%(header_h)d" backgroundColor="#13232F" transparent="0" />
        <widget name="accent" position="0,0" size="10,%(header_h)d" backgroundColor="#29B8C7" transparent="0" />
        <widget name="logo" position="%(m)d,%(logo_y)d" size="%(logo)d,%(logo)d" pixmap="%(logo_path)s" alphatest="blend" />
        <widget name="title" position="%(title_x)d,%(title_y)d" size="%(title_w)d,58" font="Regular;%(main_title)d" foregroundColor="#FFFFFF" />
        <widget name="subtitle" position="%(title_x)d,%(subtitle_y)d" size="%(title_w)d,42" font="Regular;%(body)d" foregroundColor="#AFC3D0" />
        <widget name="change" position="%(title_x)d,%(change_y)d" size="%(title_w)d,38" font="Regular;%(small)d" foregroundColor="#72D1DA" />
        <widget name="score_bg" position="%(score_x)d,18" size="%(score_w)d,%(score_h)d" backgroundColor="#0B1821" transparent="0" />
        <widget name="score_title" position="%(score_x2)d,28" size="%(score_w2)d,32" font="Regular;%(small)d" halign="center" foregroundColor="#9CB3C1" />
        <widget name="score_value" position="%(score_x2)d,58" size="%(score_w2)d,62" font="Regular;%(score_font)d" halign="center" foregroundColor="#FFFFFF" />
        <widget name="score_grade" position="%(score_x2)d,%(score_grade_y)d" size="%(score_w2)d,32" font="Regular;%(small)d" halign="center" foregroundColor="#46D369" />
        <widget name="score_bar" position="%(score_x3)d,%(score_bar_y)d" size="%(score_w3)d,12" borderWidth="1" />
        <widget name="ok_bg" position="%(m)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#173B2A" transparent="0" />
        <widget name="ok_count" position="%(m)d,%(count_y)d" size="%(card_w)d,42" font="Regular;%(count_font)d" halign="center" foregroundColor="#55E782" />
        <widget name="ok_label" position="%(m)d,%(label_y)d" size="%(card_w)d,30" font="Regular;%(small)d" halign="center" foregroundColor="#B7DCC4" />
        <widget name="info_bg" position="%(card2_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#173246" transparent="0" />
        <widget name="info_count" position="%(card2_x)d,%(count_y)d" size="%(card_w)d,42" font="Regular;%(count_font)d" halign="center" foregroundColor="#58C7F2" />
        <widget name="info_label" position="%(card2_x)d,%(label_y)d" size="%(card_w)d,30" font="Regular;%(small)d" halign="center" foregroundColor="#B7D1DF" />
        <widget name="warn_bg" position="%(card3_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#443B18" transparent="0" />
        <widget name="warn_count" position="%(card3_x)d,%(count_y)d" size="%(card_w)d,42" font="Regular;%(count_font)d" halign="center" foregroundColor="#F0D34F" />
        <widget name="warn_label" position="%(card3_x)d,%(label_y)d" size="%(card_w)d,30" font="Regular;%(small)d" halign="center" foregroundColor="#E1D7AE" />
        <widget name="error_bg" position="%(card4_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#482127" transparent="0" />
        <widget name="error_count" position="%(card4_x)d,%(count_y)d" size="%(card_w)d,42" font="Regular;%(count_font)d" halign="center" foregroundColor="#FF6C74" />
        <widget name="error_label" position="%(card4_x)d,%(label_y)d" size="%(card_w)d,30" font="Regular;%(small)d" halign="center" foregroundColor="#E4BDC0" />
        <widget name="dashboard" position="%(m)d,%(list_y)d" size="%(list_w)d,%(list_h)d" scrollbarMode="showOnDemand" />
        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#101E27" transparent="0" />
        <widget source="key_red" render="Label" position="%(red_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#FF6269" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#5DE684" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#F4D653" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#5DAEF2" />
        <widget name="footer" position="%(m)d,%(version_y)d" size="%(list_w)d,26" font="Regular;%(small)d" halign="center" foregroundColor="#758B98" />
    </screen>
    """ % {
        "w": w, "h": h, "m": m, "header_h": header_h,
        "logo_y": 24 if E2D_FHD else 18, "logo": logo, "logo_path": E2D_LOGO_PATH,
        "title_x": title_x, "title_y": 30 if E2D_FHD else 22, "title_w": title_w,
        "main_title": 48 if E2D_FHD else 38, "subtitle_y": 88 if E2D_FHD else 66,
        "body": E2D_FONT_BODY, "change_y": 132 if E2D_FHD else 98, "small": E2D_FONT_SMALL,
        "score_x": score_x, "score_w": score_w, "score_h": 154 if E2D_FHD else 142,
        "score_x2": score_x + 10, "score_w2": score_w - 20, "score_font": 48 if E2D_FHD else 36,
        "score_grade_y": 120 if E2D_FHD else 108, "score_bar_y": 156 if E2D_FHD else 144,
        "score_x3": score_x + 22, "score_w3": score_w - 44,
        "summary_y": summary_y, "summary_h": summary_h, "card_w": card_w,
        "card2_x": m + card_w + card_gap, "card3_x": m + 2 * (card_w + card_gap),
        "card4_x": m + 3 * (card_w + card_gap),
        "count_y": summary_y + (13 if E2D_FHD else 7), "label_y": summary_y + (58 if E2D_FHD else 43),
        "count_font": 34 if E2D_FHD else 27,
        "list_y": list_y, "list_w": E2D_LIST_W, "list_h": list_h,
        "footer_bg_y": footer_y - 10, "footer_bg_h": h - footer_y + 10,
        "footer_y": footer_y, "key_h": 42 if E2D_FHD else 34,
        "key_w": int((w - 2 * m) / 4), "red_x": m,
        "green_x": m + int((w - 2 * m) / 4), "yellow_x": m + 2 * int((w - 2 * m) / 4),
        "blue_x": m + 3 * int((w - 2 * m) / 4), "version_y": h - 28,
    }


def standard_text_skin(screen_name, title_height=None):
    w = E2D_UI_W
    h = E2D_UI_H
    m = E2D_MARGIN
    footer_y = h - (76 if E2D_FHD else 58)
    return """
    <screen name="%(name)s" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor" backgroundColor="#0D151C" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,%(header_h)d" backgroundColor="#13232F" transparent="0" />
        <widget name="accent" position="0,0" size="10,%(header_h)d" backgroundColor="#29B8C7" transparent="0" />
        <widget name="title" position="%(m)d,18" size="%(content_w)d,52" font="Regular;%(title_font)d" halign="center" foregroundColor="#FFFFFF" />
        <widget name="status" position="%(m)d,72" size="%(content_w)d,36" font="Regular;%(small)d" halign="center" foregroundColor="#AFC3D0" />
        <widget name="body" position="%(m)d,122" size="%(content_w)d,%(body_h)d" font="Regular;%(body_font)d" scrollbarMode="showOnDemand" />
        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#101E27" transparent="0" />
        <widget source="key_red" render="Label" position="%(m)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#FF6269" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#5DE684" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#F4D653" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#5DAEF2" />
    </screen>
    """ % {
        "name": screen_name, "w": w, "h": h, "m": m, "header_h": 112 if E2D_FHD else 108,
        "content_w": w - 2 * m, "title_font": 38 if E2D_FHD else 32, "small": E2D_FONT_SMALL,
        "body_h": footer_y - 138, "body_font": E2D_FONT_BODY,
        "footer_bg_y": footer_y - 10, "footer_bg_h": h - footer_y + 10, "footer_y": footer_y,
        "key_w": int((w - 2 * m) / 4), "green_x": m + int((w - 2 * m) / 4),
        "yellow_x": m + 2 * int((w - 2 * m) / 4), "blue_x": m + 3 * int((w - 2 * m) / 4),
    }


def results_skin():
    w = E2D_UI_W
    h = E2D_UI_H
    m = E2D_MARGIN
    footer_y = h - (76 if E2D_FHD else 58)
    return """
    <screen name="E2DoctorResultsScreen" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor" backgroundColor="#0D151C" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,112" backgroundColor="#13232F" transparent="0" />
        <widget name="accent" position="0,0" size="10,112" backgroundColor="#29B8C7" transparent="0" />
        <widget name="title" position="%(m)d,18" size="%(content_w)d,48" font="Regular;%(title_font)d" halign="center" foregroundColor="#FFFFFF" />
        <widget name="status" position="%(m)d,68" size="%(content_w)d,34" font="Regular;%(small)d" halign="center" foregroundColor="#AFC3D0" />
        <widget name="list" position="%(m)d,126" size="%(content_w)d,%(list_h)d" scrollbarMode="showOnDemand" />
        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#101E27" transparent="0" />
        <widget source="key_red" render="Label" position="%(m)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#FF6269" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#5DE684" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#F4D653" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#5DAEF2" />
    </screen>
    """ % {
        "w": w, "h": h, "m": m, "content_w": w - 2 * m,
        "title_font": 38 if E2D_FHD else 32, "small": E2D_FONT_SMALL,
        "list_h": footer_y - 142, "footer_bg_y": footer_y - 10, "footer_bg_h": h - footer_y + 10,
        "footer_y": footer_y, "body_font": E2D_FONT_BODY,
        "key_w": int((w - 2 * m) / 4), "green_x": m + int((w - 2 * m) / 4),
        "yellow_x": m + 2 * int((w - 2 * m) / 4), "blue_x": m + 3 * int((w - 2 * m) / 4),
    }


class E2DoctorDashboardList(MenuList):
    def __init__(self, entries=None):
        MenuList.__init__(self, entries or [], enableWrapAround=True, content=eListboxPythonMultiContent)
        self.l.setFont(0, gFont("Regular", E2D_FONT_TITLE))
        self.l.setFont(1, gFont("Regular", E2D_FONT_SMALL))
        self.l.setFont(2, gFont("Regular", E2D_FONT_BODY))
        self.l.setItemHeight(E2D_ITEM_H)
        self.l.setBuildFunc(self.build_entry)

    def build_entry(self, key, title, subtitle, status, badge):
        status_color = STATUS_COLORS.get(status, 0x008A9AA5)
        height = E2D_ITEM_H - 8
        title_y = 10 if E2D_FHD else 7
        subtitle_y = 46 if E2D_FHD else 35
        badge_w = 210 if E2D_FHD else 160
        content_w = E2D_LIST_W
        return [
            None,
            MultiContentEntryText(pos=(0, 4), size=(content_w, height), font=1, text="", backcolor=0x0015222B, backcolor_sel=0x00233B49),
            MultiContentEntryText(pos=(0, 4), size=(9, height), font=1, text="", backcolor=status_color, backcolor_sel=status_color),
            MultiContentEntryText(pos=(28, title_y), size=(content_w - badge_w - 50, 38), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=title, color=0x00FFFFFF, color_sel=0x00FFFFFF, backcolor_sel=0x00233B49),
            MultiContentEntryText(pos=(30, subtitle_y), size=(content_w - badge_w - 55, 28), font=1, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=subtitle, color=0x009CB1BE, color_sel=0x00D7E5EC, backcolor_sel=0x00233B49),
            MultiContentEntryText(pos=(content_w - badge_w - 20, 12), size=(badge_w, height - 16), font=2, flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=badge, color=status_color, color_sel=status_color, backcolor_sel=0x00233B49),
        ]


class E2DoctorV2ResultList(MenuList):
    def __init__(self, entries=None):
        MenuList.__init__(self, entries or [], enableWrapAround=False, content=eListboxPythonMultiContent)
        self.l.setFont(0, gFont("Regular", E2D_FONT_BODY))
        self.l.setFont(1, gFont("Regular", E2D_FONT_SMALL))
        self.l.setItemHeight(68 if E2D_FHD else 52)
        self.l.setBuildFunc(self.build_entry)

    def build_entry(self, status, title, summary):
        color = STATUS_COLORS.get(status, 0x00FFFFFF)
        item_h = 68 if E2D_FHD else 52
        return [
            None,
            MultiContentEntryText(pos=(0, 2), size=(E2D_LIST_W, item_h - 4), font=1, text="", backcolor=0x0015222B, backcolor_sel=0x00233B49),
            MultiContentEntryText(pos=(0, 2), size=(8, item_h - 4), font=1, text="", backcolor=color, backcolor_sel=color),
            MultiContentEntryText(pos=(24, 3), size=(E2D_LIST_W - 48, 30), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text="%s  %s" % (status_prefix(status), title), color=color, color_sel=color, backcolor_sel=0x00233B49),
            MultiContentEntryText(pos=(28, 32 if E2D_FHD else 26), size=(E2D_LIST_W - 56, 28), font=1, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=summary, color=0x00B4C5CF, color_sel=0x00FFFFFF, backcolor_sel=0x00233B49),
        ]


class E2DoctorTextScreen(Screen):
    skin = standard_text_skin("E2DoctorTextScreen")

    def __init__(self, session, title, text, status="E2 Doctor 2.0"):
        Screen.__init__(self, session)
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label(title)
        self["status"] = Label(status)
        self["body"] = ScrollLabel(text)
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("")
        self["key_yellow"] = StaticText("")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "cancel": self.close, "red": self.close, "blue": self.close, "ok": self.close,
                "up": self["body"].pageUp, "down": self["body"].pageDown,
                "left": self["body"].pageUp, "right": self["body"].pageDown,
            },
            -1,
        )


class E2DoctorSolutionScreen(Screen):
    skin = standard_text_skin("E2DoctorSolutionScreen")

    def __init__(self, session, item):
        Screen.__init__(self, session)
        self.item = item
        self.solution = get_solution(item)
        self.action_name = self.solution.get("action")
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label("Możliwe rozwiązanie")
        self["status"] = Label("%s — %s" % (status_name(item.get("status")), item.get("title", "")))
        self["body"] = ScrollLabel(build_solution_text(item, include_technical=False))
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText(self.solution.get("action_label", "") if self.action_name else "")
        self["key_yellow"] = StaticText("Dane techniczne")
        self["key_blue"] = StaticText("Zapisz instrukcję")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "cancel": self.close, "red": self.close, "green": self.perform_action,
                "yellow": self.show_technical, "blue": self.save_instruction,
                "up": self["body"].pageUp, "down": self["body"].pageDown,
                "left": self["body"].pageUp, "right": self["body"].pageDown,
            },
            -1,
        )

    def show_technical(self):
        self.session.open(E2DoctorTextScreen, "Dane techniczne — %s" % self.item.get("title", ""), self.item.get("details", "Brak danych technicznych."))

    def save_instruction(self):
        try:
            path = save_solution_instruction(self.item)
            self.session.open(MessageBox, "Instrukcję zapisano w:\n%s" % path, MessageBox.TYPE_INFO, timeout=8)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się zapisać instrukcji:\n%s" % error, MessageBox.TYPE_ERROR)

    def perform_action(self):
        if not self.action_name:
            self.session.open(MessageBox, tr("no_safe_action"), MessageBox.TYPE_INFO, timeout=7)
            return
        confirmations = {
            "repair_bouquet_refs": tr("confirm_repair_bouquets"),
            "remove_opkg_lock": tr("confirm_remove_lock"),
            "restart_oscam": tr("confirm_restart_oscam"),
            "sync_time": tr("confirm_sync_time"),
            "disable_suspect_plugin": "Tymczasowo wyłączyć podejrzaną wtyczkę %s?\n\nJej katalog zostanie jedynie przemianowany. Zmianę będzie można cofnąć w Narzędziach E2 Doctor. Po operacji wymagany jest restart GUI." % self.item.get("context", {}).get("plugin", ""),
        }
        if self.action_name in confirmations:
            self.session.openWithCallback(self._confirmed_action, MessageBox, confirmations[self.action_name], MessageBox.TYPE_YESNO)
        else:
            self._execute_action()

    def _confirmed_action(self, answer):
        if answer:
            self._execute_action()

    def _success(self, message, changed=True):
        self.session.openWithCallback(lambda *args: self.close(changed), MessageBox, message, MessageBox.TYPE_INFO, timeout=10)

    def _execute_action(self):
        try:
            if self.action_name == "repair_bouquet_refs":
                removed, backup_dir = repair_missing_bouquet_refs()
                self._success("Usunięto błędne odwołania: %d\nKopia bezpieczeństwa:\n%s" % (removed, backup_dir))
            elif self.action_name == "remove_opkg_lock":
                removed = remove_inactive_opkg_locks()
                if removed:
                    self._success("Usunięto blokady OPKG:\n%s" % "\n".join(removed))
                else:
                    self.session.open(MessageBox, tr("lock_missing"), MessageBox.TYPE_INFO, timeout=6)
            elif self.action_name == "restart_oscam":
                command, _ = restart_oscam_service()
                self._success("OSCam został uruchomiony ponownie.\nUżyte polecenie: %s" % command)
            elif self.action_name == "sync_time":
                command, _ = sync_system_time()
                self._success("Uruchomiono synchronizację czasu.\nUżyte polecenie: %s" % command)
            elif self.action_name == "network_test":
                self.session.open(E2DoctorTextScreen, "Rozszerzony test sieci", network_diagnostic_text())
            elif self.action_name == "show_processes":
                self.session.open(E2DoctorTextScreen, "Procesy i pamięć RAM", top_memory_processes_text())
            elif self.action_name == "find_large_files":
                self.session.open(E2DoctorTextScreen, "Największe pliki", largest_files_text())
            elif self.action_name == "disable_suspect_plugin":
                original, disabled = disable_suspect_plugin(self.item.get("context") or {})
                self._success("Wtyczka została tymczasowo wyłączona.\n\nOryginał: %s\nWyłączony katalog: %s\n\nWykonaj restart GUI. Zmianę można cofnąć w Narzędziach." % (original, disabled))
            else:
                self.session.open(MessageBox, "Nieznane działanie: %s" % self.action_name, MessageBox.TYPE_ERROR)
        except Exception as error:
            self.session.open(MessageBox, "Operacja nie powiodła się:\n%s" % error, MessageBox.TYPE_ERROR)


class E2DoctorResultsScreen(Screen):
    skin = results_skin()

    def __init__(self, session, title, results, status_text=""):
        Screen.__init__(self, session)
        self.results = list(results or [])
        self.changed = False
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label(title)
        counts = result_counts(self.results)
        self["status"] = Label(status_text or "OK %d | Informacje %d | Ostrzeżenia %d | Błędy %d" % (
            counts.get(STATUS_OK, 0), counts.get(STATUS_INFO, 0), counts.get(STATUS_WARN, 0), counts.get(STATUS_ERROR, 0)
        ))
        self["list"] = E2DoctorV2ResultList([])
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Odczyt / pomoc")
        self["key_yellow"] = StaticText("Raport")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "cancel": self.finish, "red": self.finish, "blue": self.finish,
                "ok": self.open_selected, "green": self.open_selected, "yellow": self.save_report,
            },
            -1,
        )
        self.refresh_list()

    def refresh_list(self):
        self["list"].setList([(item.get("status"), item.get("title", ""), item.get("summary", "")) for item in self.results])

    def open_selected(self):
        index = self["list"].getSelectedIndex()
        if 0 <= index < len(self.results):
            self.session.openWithCallback(self.solution_closed, E2DoctorSolutionScreen, self.results[index])

    def solution_closed(self, changed=False):
        if changed:
            self.changed = True

    def save_report(self):
        try:
            path = make_report(self.results)
            self.session.open(MessageBox, "Raport zapisano w:\n%s" % path, MessageBox.TYPE_INFO, timeout=9)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się utworzyć raportu:\n%s" % error, MessageBox.TYPE_ERROR)

    def finish(self):
        self.close(self.changed)


class E2DoctorHistoryScreen(Screen):
    skin = results_skin().replace('name="E2DoctorResultsScreen"', 'name="E2DoctorHistoryScreen"')

    def __init__(self, session):
        Screen.__init__(self, session)
        self.history = load_history()
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label("Historia stanu dekodera")
        self["status"] = Label("Porównuj wyniki i sprawdzaj, co zmieniło się w systemie")
        self.entries = []
        for index, snapshot in enumerate(self.history):
            counts = snapshot.get("counts") or {}
            title = "%s — %d/100 (%s)" % (snapshot.get("timestamp", "brak daty"), snapshot.get("score", 0), snapshot.get("grade", ""))
            summary = "Błędy %d | Ostrzeżenia %d | %s" % (
                counts.get(STATUS_ERROR, 0), counts.get(STATUS_WARN, 0), snapshot.get("system", "Enigma2")
            )
            status = STATUS_ERROR if counts.get(STATUS_ERROR, 0) else STATUS_WARN if counts.get(STATUS_WARN, 0) else STATUS_OK
            self.entries.append((status, title, summary))
        if not self.entries:
            self.entries.append((STATUS_INFO, "Brak zapisanej historii", "Uruchom pełny skan E2 Doctor."))
        self["list"] = E2DoctorV2ResultList(self.entries)
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Szczegóły")
        self["key_yellow"] = StaticText("Wyczyść historię")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "cancel": self.close, "red": self.close, "blue": self.close,
                "ok": self.show_selected, "green": self.show_selected, "yellow": self.confirm_clear,
            },
            -1,
        )

    def show_selected(self):
        index = self["list"].getSelectedIndex()
        if not self.history or index < 0 or index >= len(self.history):
            return
        snapshot = self.history[index]
        previous = self.history[index + 1] if index + 1 < len(self.history) else None
        counts = snapshot.get("counts") or {}
        lines = [
            "SKAN: %s" % snapshot.get("timestamp", ""),
            "Wynik: %d/100 — %s" % (snapshot.get("score", 0), snapshot.get("grade", "")),
            "System: %s | Python %s" % (snapshot.get("system", ""), snapshot.get("python", "")),
            "OK: %d | Informacje: %d | Ostrzeżenia: %d | Błędy: %d" % (
                counts.get(STATUS_OK, 0), counts.get(STATUS_INFO, 0), counts.get(STATUS_WARN, 0), counts.get(STATUS_ERROR, 0)
            ),
            "",
            "PORÓWNANIE Z POPRZEDNIM SKANEM",
            compare_snapshots(snapshot, previous),
            "",
            "WYKRYTE PROBLEMY",
        ]
        issues = snapshot.get("issues") or []
        if issues:
            for issue in issues:
                lines.append("%s %s — %s" % (status_prefix(issue.get("status")), issue.get("title", ""), issue.get("summary", "")))
        else:
            lines.append("Brak ostrzeżeń i błędów.")
        self.session.open(E2DoctorTextScreen, "Historia — %s" % snapshot.get("timestamp", ""), "\n".join(lines))

    def confirm_clear(self):
        if not self.history:
            return
        self.session.openWithCallback(self.clear_history, MessageBox, "Usunąć zapisaną historię skanów E2 Doctor?", MessageBox.TYPE_YESNO)

    def clear_history(self, answer):
        if answer:
            try:
                save_json_file(E2D_HISTORY_FILE, [])
                self.session.openWithCallback(lambda *args: self.close(), MessageBox, "Historia została usunięta.", MessageBox.TYPE_INFO, timeout=6)
            except Exception as error:
                self.session.open(MessageBox, "Nie udało się usunąć historii:\n%s" % error, MessageBox.TYPE_ERROR)


class E2DoctorIPKBrowser(Screen):
    skin = results_skin().replace('name="E2DoctorResultsScreen"', 'name="E2DoctorIPKBrowser"')

    def __init__(self, session):
        Screen.__init__(self, session)
        self.paths = []
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label("E2 Safe Installer — analiza IPK")
        self["status"] = Label("Analiza bez instalowania i bez modyfikowania systemu")
        self["list"] = E2DoctorV2ResultList([])
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Analizuj")
        self["key_yellow"] = StaticText("Odśwież")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "cancel": self.close, "red": self.close, "blue": self.close,
                "ok": self.analyze_selected, "green": self.analyze_selected, "yellow": self.refresh,
            },
            -1,
        )
        self.refresh()

    def refresh(self):
        self.paths = find_ipk_files()
        rows = []
        for path in self.paths:
            try:
                summary = "%s | %s" % (format_bytes(os.path.getsize(path)), os.path.dirname(path))
            except Exception:
                summary = os.path.dirname(path)
            rows.append((STATUS_INFO, os.path.basename(path), summary))
        if not rows:
            rows.append((STATUS_INFO, "Nie znaleziono paczek IPK", "Skopiuj plik IPK do /tmp lub na nośnik w /media."))
        self["list"].setList(rows)
        self["status"].setText("Znalezione paczki: %d | E2 Doctor nie instaluje wskazanego pliku" % len(self.paths))

    def analyze_selected(self):
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.paths):
            return
        path = self.paths[index]
        try:
            text = analyze_ipk(path)
            self.session.open(E2DoctorTextScreen, "Analiza — %s" % os.path.basename(path), text, "E2 Safe Installer")
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się przeanalizować paczki:\n%s" % error, MessageBox.TYPE_ERROR)


class E2DoctorSettingsScreen(Screen):
    skin = results_skin().replace('name="E2DoctorResultsScreen"', 'name="E2DoctorSettingsScreen"')

    def __init__(self, session):
        Screen.__init__(self, session)
        self.settings = load_e2doctor_settings()
        self.options = ["auto_scan", "monitor_enabled", "monitor_interval_hours", "history_limit"]
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label("Ustawienia E2 Doctor")
        self["status"] = Label("Lewo / prawo zmienia wartość. Zielony zapisuje ustawienia.")
        self["list"] = E2DoctorV2ResultList([])
        self["key_red"] = StaticText("Anuluj")
        self["key_green"] = StaticText("Zapisz")
        self["key_yellow"] = StaticText("Domyślne")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "cancel": self.close, "red": self.close, "blue": self.close,
                "green": self.save, "yellow": self.defaults,
                "left": self.change_left, "right": self.change_right, "ok": self.change_right,
            },
            -1,
        )
        self.refresh()

    def option_text(self, key):
        if key == "auto_scan":
            return "Automatyczny skan po otwarciu", "włączony" if self.settings.get(key) else "wyłączony"
        if key == "monitor_enabled":
            return "Monitor krytycznych problemów w tle", "włączony" if self.settings.get(key) else "wyłączony"
        if key == "monitor_interval_hours":
            return "Odstęp kontroli monitora", "%d godz." % self.settings.get(key, 6)
        if key == "history_limit":
            return "Liczba zapisanych skanów", "%d" % self.settings.get(key, 20)
        return key, str(self.settings.get(key))

    def refresh(self):
        rows = []
        for key in self.options:
            title, value = self.option_text(key)
            rows.append((STATUS_INFO, title, "Wartość: %s" % value))
        self["list"].setList(rows)

    def modify(self, direction):
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.options):
            return
        key = self.options[index]
        if key in ("auto_scan", "monitor_enabled"):
            self.settings[key] = not bool(self.settings.get(key))
        elif key == "monitor_interval_hours":
            values = [1, 3, 6, 12, 24]
            current = self.settings.get(key, 6)
            try:
                pos = values.index(current)
            except Exception:
                pos = 2
            self.settings[key] = values[(pos + direction) % len(values)]
        elif key == "history_limit":
            values = [5, 10, 20, 30, 50]
            current = self.settings.get(key, 20)
            try:
                pos = values.index(current)
            except Exception:
                pos = 2
            self.settings[key] = values[(pos + direction) % len(values)]
        self.refresh()
        try:
            self["list"].moveToIndex(index)
        except Exception:
            pass

    def change_left(self):
        self.modify(-1)

    def change_right(self):
        self.modify(1)

    def defaults(self):
        self.settings = dict(DEFAULT_SETTINGS)
        self.refresh()

    def save(self):
        try:
            save_e2doctor_settings(self.settings)
            self.session.openWithCallback(lambda *args: self.close(True), MessageBox, "Ustawienia zostały zapisane.", MessageBox.TYPE_INFO, timeout=6)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się zapisać ustawień:\n%s" % error, MessageBox.TYPE_ERROR)


class E2DoctorTools(Screen):
    skin = results_skin().replace('name="E2DoctorResultsScreen"', 'name="E2DoctorTools"')

    def __init__(self, session):
        Screen.__init__(self, session)
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label("Bezpieczne narzędzia E2 Doctor")
        last_op = last_reversible_operation()
        self["status"] = Label("Ostatnia operacja do cofnięcia: %s" % (last_op.get("label") if last_op else "brak"))
        self.tool_entries = [
            ("Przeładuj listę kanałów", "reload", "Bez usuwania list i ustawień tunera"),
            ("Usuń nieaktywną blokadę OPKG", "lock", "Tylko gdy OPKG nie jest uruchomiony"),
            ("Usuń stare crashlogi", "logs", "Pozostawia 3 najnowsze pliki"),
            ("Uruchom ponownie OSCam", "oscam", "Wyszukuje dostępny skrypt startowy"),
            ("Pokaż procesy zużywające RAM", "processes", "Diagnostyka bez kończenia procesów"),
            ("Znajdź największe pliki", "files", "Analiza bez automatycznego usuwania"),
            ("Utwórz raport awaryjny", "emergency", "Działa również z polecenia e2doctor-report"),
            ("Cofnij ostatnią bezpieczną zmianę", "rollback", "Przywraca backup lub wyłączoną wtyczkę"),
            ("Ustawienia E2 Doctor", "settings", "Monitoring, historia i automatyczny skan"),
            ("Uruchom ponownie GUI", "gui", "Wymaga potwierdzenia"),
        ]
        rows = [(STATUS_INFO, title, subtitle) for title, _, subtitle in self.tool_entries]
        self["list"] = E2DoctorV2ResultList(rows)
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Wykonaj")
        self["key_yellow"] = StaticText("")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {"cancel": self.close, "red": self.close, "blue": self.close, "ok": self.execute, "green": self.execute},
            -1,
        )

    def execute(self):
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.tool_entries):
            return
        action = self.tool_entries[index][1]
        if action == "reload":
            self.reload_bouquets()
        elif action == "lock":
            self.remove_lock()
        elif action == "logs":
            self.session.openWithCallback(self.logs_confirmed, MessageBox, "Usunąć stare crashlogi i pozostawić 3 najnowsze?", MessageBox.TYPE_YESNO)
        elif action == "oscam":
            self.session.openWithCallback(self.oscam_confirmed, MessageBox, "Uruchomić ponownie OSCam?", MessageBox.TYPE_YESNO)
        elif action == "processes":
            self.session.open(E2DoctorTextScreen, "Procesy i pamięć RAM", top_memory_processes_text())
        elif action == "files":
            self.session.open(E2DoctorTextScreen, "Największe pliki", largest_files_text())
        elif action == "emergency":
            self.make_emergency()
        elif action == "rollback":
            operation = last_reversible_operation()
            if not operation:
                self.session.open(MessageBox, "Brak operacji możliwej do cofnięcia.", MessageBox.TYPE_INFO, timeout=6)
            else:
                text = "Cofnąć operację?\n\n%s\nData: %s" % (operation.get("label", ""), operation.get("timestamp", ""))
                self.session.openWithCallback(self.rollback_confirmed, MessageBox, text, MessageBox.TYPE_YESNO)
        elif action == "settings":
            self.session.open(E2DoctorSettingsScreen)
        elif action == "gui":
            self.session.openWithCallback(self.gui_confirmed, MessageBox, "Uruchomić ponownie GUI Enigma2?", MessageBox.TYPE_YESNO)

    def reload_bouquets(self):
        try:
            if eDVBDB is None:
                raise RuntimeError("Interfejs eDVBDB jest niedostępny")
            db = eDVBDB.getInstance()
            db.reloadServicelist()
            db.reloadBouquets()
            self.session.open(MessageBox, "Lista kanałów została przeładowana.", MessageBox.TYPE_INFO, timeout=6)
        except Exception as error:
            self.session.open(MessageBox, "Operacja nie powiodła się:\n%s" % error, MessageBox.TYPE_ERROR)

    def remove_lock(self):
        try:
            removed = remove_inactive_opkg_locks()
            text = "Usunięto:\n%s" % "\n".join(removed) if removed else "Nie znaleziono nieaktywnej blokady OPKG."
            self.session.open(MessageBox, text, MessageBox.TYPE_INFO, timeout=7)
        except Exception as error:
            self.session.open(MessageBox, "Operacja nie powiodła się:\n%s" % error, MessageBox.TYPE_ERROR)

    def logs_confirmed(self, answer):
        if answer:
            try:
                removed = cleanup_old_crashlogs(3)
                self.session.open(MessageBox, "Usunięto starych crashlogów: %d" % len(removed), MessageBox.TYPE_INFO, timeout=7)
            except Exception as error:
                self.session.open(MessageBox, "Operacja nie powiodła się:\n%s" % error, MessageBox.TYPE_ERROR)

    def oscam_confirmed(self, answer):
        if answer:
            try:
                command, _ = restart_oscam_service()
                self.session.open(MessageBox, "OSCam został uruchomiony ponownie.\n%s" % command, MessageBox.TYPE_INFO, timeout=7)
            except Exception as error:
                self.session.open(MessageBox, "Operacja nie powiodła się:\n%s" % error, MessageBox.TYPE_ERROR)

    def make_emergency(self):
        try:
            path = emergency_report()
            self.session.open(MessageBox, "Raport awaryjny zapisano w:\n%s" % path, MessageBox.TYPE_INFO, timeout=9)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się utworzyć raportu:\n%s" % error, MessageBox.TYPE_ERROR)

    def rollback_confirmed(self, answer):
        if answer:
            try:
                message = rollback_last_operation()
                self.session.openWithCallback(lambda *args: self.close(True), MessageBox, message, MessageBox.TYPE_INFO, timeout=9)
            except Exception as error:
                self.session.open(MessageBox, "Nie udało się cofnąć zmiany:\n%s" % error, MessageBox.TYPE_ERROR)

    def gui_confirmed(self, answer):
        if answer:
            try:
                from Screens.Standby import TryQuitMainloop
                self.session.open(TryQuitMainloop, 3)
            except Exception as error:
                self.session.open(MessageBox, "Restart GUI nie powiódł się:\n%s" % error, MessageBox.TYPE_ERROR)


DASHBOARD_MODULES = [
    ("problems", "Najważniejsze problemy", "Ostrzeżenia i błędy wymagające uwagi"),
    ("system", "System i wydajność", "Python, flash, RAM, czas, temperatura i obciążenie"),
    ("crashlogs", "Analizator crashlogów", "Wskazuje błąd, plik, linię i podejrzaną wtyczkę"),
    ("network", "Sieć i internet", "Adresacja, DNS oraz połączenie HTTPS"),
    ("channels", "Listy kanałów", "Indeksy bukietów, lamedb i martwe odwołania"),
    ("tuners", "Głowice i sygnał", "Wykryte tunery, konfiguracja i bieżący LOCK"),
    ("storage", "Nośniki i systemy plików", "Punkty montowania, miejsce i błędy zapisu"),
    ("packages", "Pakiety OPKG", "Stan menedżera i niepełne instalacje"),
    ("oscam", "OSCam", "Proces, pliki konfiguracji i bezpieczny restart"),
    ("media", "EPG i picony", "Lokalizacja, rozmiar i podstawowa poprawność danych"),
    ("history", "Historia stanu dekodera", "Porównanie skanów i wykrywanie nowych problemów"),
    ("py3", "Zgodność wtyczek z Python 3", "Skan błędów składni i pozostałości Python 2"),
    ("ipk", "E2 Safe Installer", "Analiza paczek IPK przed instalacją"),
    ("tools", "Bezpieczne narzędzia", "Naprawy, raport awaryjny, cofanie zmian i ustawienia"),
]


def module_results(results, key):
    if key == "problems":
        return [item for item in results if item.get("status") in (STATUS_WARN, STATUS_ERROR)]
    return [item for item in results if item.get("module") == key]


def module_badge(results, key):
    selected = module_results(results, key)
    if key in ("history", "py3", "ipk", "tools"):
        return STATUS_INFO, "OTWÓRZ"
    if key == "problems" and not selected and results:
        return STATUS_OK, "BRAK PROBLEMÓW"
    if not selected:
        return STATUS_INFO, "BRAK DANYCH"
    worst = max((item.get("status", STATUS_INFO) for item in selected), key=lambda value: STATUS_RANK.get(value, 0))
    errors = len([item for item in selected if item.get("status") == STATUS_ERROR])
    warnings = len([item for item in selected if item.get("status") == STATUS_WARN])
    if errors:
        badge = "%d BŁĄD" % errors if errors == 1 else "%d BŁĘDY" % errors if 2 <= errors <= 4 else "%d BŁĘDÓW" % errors
    elif warnings:
        badge = "%d OSTRZEŻENIE" % warnings if warnings == 1 else "%d OSTRZEŻENIA" % warnings if 2 <= warnings <= 4 else "%d OSTRZEŻEŃ" % warnings
    else:
        badge = "DZIAŁA POPRAWNIE"
    return worst, badge


def module_subtitle(results, key, default):
    selected = module_results(results, key)
    problematic = [item for item in selected if item.get("status") in (STATUS_ERROR, STATUS_WARN)]
    if problematic:
        problematic.sort(key=lambda item: STATUS_RANK.get(item.get("status"), 0), reverse=True)
        return problematic[0].get("summary", default)
    return default


class E2DoctorDashboard(Screen):
    skin = dashboard_skin()

    def __init__(self, session):
        Screen.__init__(self, session)
        self.results = []
        self.settings = load_e2doctor_settings()
        self._scan_started = False
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["score_bg"] = Label("")
        self["ok_bg"] = Label("")
        self["info_bg"] = Label("")
        self["warn_bg"] = Label("")
        self["error_bg"] = Label("")
        self["footer_bg"] = Label("")
        self["logo"] = Pixmap()
        self["title"] = Label("E2 Doctor")
        self["subtitle"] = Label("Centrum diagnostyki i bezpiecznej naprawy Enigma2")
        self["change"] = Label("Gotowy do diagnostyki")
        self["score_title"] = Label("WYNIK DIAGNOSTYKI")
        self["score_value"] = Label("--/100")
        self["score_grade"] = Label("BRAK SKANU")
        self["score_bar"] = ProgressBar()
        self["score_bar"].setValue(0)
        self["ok_count"] = Label("0")
        self["ok_label"] = Label("POPRAWNE")
        self["info_count"] = Label("0")
        self["info_label"] = Label("INFORMACJE")
        self["warn_count"] = Label("0")
        self["warn_label"] = Label("OSTRZEŻENIA")
        self["error_count"] = Label("0")
        self["error_label"] = Label("BŁĘDY")
        self["dashboard"] = E2DoctorDashboardList([])
        self["key_red"] = StaticText("Skanuj")
        self["key_green"] = StaticText("Otwórz")
        self["key_yellow"] = StaticText("Raport")
        self["key_blue"] = StaticText("Wyjście")
        self["footer"] = Label("E2 Doctor %s | Python 3 | by %s | MENU: ustawienia" % (PLUGIN_VERSION, PLUGIN_AUTHOR))
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "MenuActions", "InfoActions"],
            {
                "cancel": self.close, "blue": self.close,
                "red": self.scan, "green": self.open_selected, "ok": self.open_selected,
                "yellow": self.save_report, "menu": self.open_settings, "info": self.open_tools,
            },
            -1,
        )
        self.refresh_dashboard()
        self.onShown.append(self.first_show)

    def first_show(self):
        if self._scan_started:
            return
        self._scan_started = True
        self.settings = load_e2doctor_settings()
        if self.settings.get("auto_scan", True):
            self.scan()
        else:
            self["change"].setText("Automatyczny skan jest wyłączony. Naciśnij czerwony przycisk.")

    def scan(self):
        self["change"].setText("Trwa pełna diagnostyka systemu...")
        try:
            previous_history = load_history()
            self.results = run_all_checks(self.session)
            current = compact_snapshot(self.results)
            previous = previous_history[0] if previous_history else None
            change_text = compare_snapshots(current, previous)
            save_history_snapshot(self.results)
            self.update_summary(change_text)
            self.refresh_dashboard()
        except Exception as error:
            self["change"].setText("Błąd diagnostyki: %s" % error)
            self.session.open(MessageBox, "Diagnostyka nie powiodła się:\n%s\n\n%s" % (error, traceback.format_exc()), MessageBox.TYPE_ERROR)

    def update_summary(self, change_text=None):
        counts = result_counts(self.results)
        score = calculate_health_score(self.results)
        grade = health_grade(score)
        self["score_value"].setText("%d/100" % score)
        self["score_grade"].setText(grade)
        self["score_bar"].setValue(score)
        self["ok_count"].setText(str(counts.get(STATUS_OK, 0)))
        self["info_count"].setText(str(counts.get(STATUS_INFO, 0)))
        self["warn_count"].setText(str(counts.get(STATUS_WARN, 0)))
        self["error_count"].setText(str(counts.get(STATUS_ERROR, 0)))
        self["change"].setText(change_text or current_change_summary(self.results))

    def refresh_dashboard(self):
        rows = []
        for key, title, default_subtitle in DASHBOARD_MODULES:
            status, badge = module_badge(self.results, key)
            subtitle = module_subtitle(self.results, key, default_subtitle)
            rows.append((key, title, subtitle, status, badge))
        self["dashboard"].setList(rows)

    def selected_key(self):
        index = self["dashboard"].getSelectedIndex()
        if 0 <= index < len(DASHBOARD_MODULES):
            return DASHBOARD_MODULES[index][0]
        return None

    def open_selected(self):
        key = self.selected_key()
        if not key:
            return
        if key == "history":
            self.session.open(E2DoctorHistoryScreen)
        elif key == "py3":
            self["change"].setText("Trwa skanowanie zgodności wtyczek z Pythonem 3...")
            try:
                report = python3_compatibility_report()
                self.session.open(E2DoctorTextScreen, "Zgodność z Pythonem 3", report, "Analiza bez modyfikowania plików")
            except Exception as error:
                self.session.open(MessageBox, "Skan zgodności nie powiódł się:\n%s" % error, MessageBox.TYPE_ERROR)
            finally:
                self["change"].setText(current_change_summary(self.results) if self.results else "Gotowy")
        elif key == "ipk":
            self.session.open(E2DoctorIPKBrowser)
        elif key == "tools":
            self.open_tools()
        else:
            if not self.results:
                self.scan()
            selected = module_results(self.results, key)
            if not selected:
                self.session.open(MessageBox, "Brak wyników dla wybranego modułu.", MessageBox.TYPE_INFO, timeout=5)
                return
            title = next((item[1] for item in DASHBOARD_MODULES if item[0] == key), "Wyniki diagnostyki")
            self.session.openWithCallback(self.results_closed, E2DoctorResultsScreen, title, selected)

    def results_closed(self, changed=False):
        if changed:
            self.scan()

    def save_report(self):
        if not self.results:
            self.scan()
        if not self.results:
            return
        try:
            path = make_report(self.results)
            self.session.open(MessageBox, "Raport zapisano w:\n%s" % path, MessageBox.TYPE_INFO, timeout=9)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się utworzyć raportu:\n%s" % error, MessageBox.TYPE_ERROR)

    def open_tools(self):
        self.session.openWithCallback(self.tools_closed, E2DoctorTools)

    def tools_closed(self, changed=False):
        if changed:
            self.scan()

    def open_settings(self):
        self.session.openWithCallback(self.settings_closed, E2DoctorSettingsScreen)

    def settings_closed(self, changed=False):
        if changed:
            self.settings = load_e2doctor_settings()


class E2DoctorMonitor(object):
    def __init__(self, session):
        self.session = session
        self.timer = eTimer() if eTimer is not None else None
        if self.timer is not None:
            try:
                self.timer.callback.append(self.check)
            except Exception:
                try:
                    self.timer_conn = self.timer.timeout.connect(self.check)
                except Exception:
                    self.timer = None
        if self.timer is not None:
            try:
                self.timer.startLongTimer(90)
            except Exception:
                self.timer.start(90000, True)

    def schedule_next(self):
        if self.timer is None:
            return
        hours = load_e2doctor_settings().get("monitor_interval_hours", 6)
        seconds = int(hours * 3600)
        try:
            self.timer.startLongTimer(seconds)
        except Exception:
            self.timer.start(seconds * 1000, True)

    def critical_issues(self):
        issues = []
        try:
            stats = os.statvfs("/")
            free = stats.f_bavail * stats.f_frsize
            percent = free * 100.0 / (stats.f_blocks * stats.f_frsize) if stats.f_blocks else 0
            if free < 25 * 1024 * 1024 or percent < 3:
                issues.append("Krytycznie mało miejsca we flashu: %s" % format_bytes(free))
        except Exception:
            pass
        try:
            root_entry = next((item for item in get_mounts() if item[1] == "/"), None)
            if root_entry and "ro" in root_entry[3].split(","):
                issues.append("Główny system plików jest tylko do odczytu")
        except Exception:
            pass
        if datetime.datetime.now().year < 2024:
            issues.append("Nieprawidłowa data i czas systemowy")
        logs = find_crashlogs()
        if logs:
            try:
                age = time.time() - os.path.getmtime(logs[0])
                if age < 10 * 60:
                    findings = analyze_crashlog(read_text(logs[0], limit=500000))
                    message = findings[0].get("message") if findings else "Pojawił się nowy crashlog Enigma2"
                    issues.append(message)
            except Exception:
                pass
        return issues

    def check(self):
        try:
            settings = load_e2doctor_settings()
            if not settings.get("monitor_enabled", True):
                self.schedule_next()
                return
            issues = self.critical_issues()
            if issues:
                now = int(time.time())
                last_notice = 0
                try:
                    last_notice = int(read_text(E2D_LAST_NOTICE_FILE).strip() or 0)
                except Exception:
                    pass
                interval = settings.get("monitor_interval_hours", 6) * 3600
                if now - last_notice >= interval:
                    ensure_state_dirs()
                    try:
                        with open(E2D_LAST_NOTICE_FILE, "w", encoding="utf-8") as handle:
                            handle.write(str(now))
                    except Exception:
                        pass
                    text = "E2 Doctor wykrył problem wymagający uwagi:\n\n%s\n\nOtwórz E2 Doctor, aby zobaczyć rozwiązanie." % "\n".join("- %s" % item for item in issues[:5])
                    try:
                        from Tools.Notifications import AddPopup
                        AddPopup(text, MessageBox.TYPE_WARNING, 14, "E2DoctorMonitor")
                    except Exception:
                        pass
        finally:
            self.schedule_next()


E2D_MONITORS = []


def session_start(reason, session=None, **kwargs):
    if reason == 0 and session is not None and eTimer is not None:
        try:
            E2D_MONITORS.append(E2DoctorMonitor(session))
        except Exception:
            pass


def main(session, **kwargs):
    session.open(E2DoctorDashboard)


def Plugins(**kwargs):
    descriptors = [
        PluginDescriptor(name="E2 Doctor", description="Centrum diagnostyki i bezpiecznej naprawy Enigma2", where=PluginDescriptor.WHERE_PLUGINMENU, icon="plugin.png", fnc=main),
        PluginDescriptor(name="E2 Doctor", description="Centrum diagnostyki i bezpiecznej naprawy Enigma2", where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
    ]
    try:
        descriptors.append(PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=session_start))
    except Exception:
        pass
    return descriptors

# -----------------------------------------------------------------------------
# E2 Doctor 2.1 - interfejs premium i centrum naprawy kontekstowej
# -----------------------------------------------------------------------------

PLUGIN_EMAIL = "aio-iptv@wp.pl"
E2D_FONT_TINY = 19 if E2D_FHD else 15
E2D_LOGO_SIZE = 148 if E2D_FHD else 116
E2D_LOGO_PATH = os.path.join(PLUGIN_PATH, "logo_fhd.png" if E2D_FHD else "logo_hd.png")

try:
    from enigma import RT_HALIGN_CENTER
except Exception:
    RT_HALIGN_CENTER = 0


def _root_device_id():
    try:
        return os.stat("/").st_dev
    except Exception:
        return None


def _is_on_root_filesystem(path):
    try:
        root_dev = _root_device_id()
        return root_dev is not None and os.stat(path).st_dev == root_dev
    except Exception:
        return False


def _file_size(path):
    try:
        return int(os.path.getsize(path))
    except Exception:
        return 0


def _memory_available_bytes():
    values = {}
    for line in read_text("/proc/meminfo").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        try:
            values[key] = int(value.strip().split()[0]) * 1024
        except Exception:
            pass
    return values.get("MemAvailable", values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0))


def safe_ram_refresh():
    """Zwalnia wyłącznie cache jądra. Nie kończy procesów i nie usuwa plików."""
    before = _memory_available_bytes()
    code, output, error = run_command("sync", timeout=12)
    if code not in (0, None):
        raise RuntimeError(error or output or "Nie udało się wykonać synchronizacji danych.")
    try:
        with open("/proc/sys/vm/drop_caches", "w") as handle:
            handle.write("3\n")
    except Exception as exc:
        raise RuntimeError("System nie pozwolił odświeżyć pamięci podręcznej: %s" % exc)
    time.sleep(0.4)
    after = _memory_available_bytes()
    record_operation(
        "Bezpieczne odświeżenie pamięci RAM",
        "information",
        {"before": before, "after": after, "method": "sync + drop_caches=3"},
        False,
    )
    return before, after


def safe_flash_cleanup_candidates():
    """Zwraca tylko ściśle określone, bezpieczne pliki z głównego flasha."""
    candidates = {}

    # Stare crashlogi - trzy najnowsze pozostają nietknięte.
    logs = find_crashlogs()
    for path in logs[3:]:
        if os.path.isfile(path) and _is_on_root_filesystem(path):
            candidates[os.path.realpath(path)] = "stary crashlog"

    # Pobrane archiwa OPKG. Nie usuwamy baz pakietów ani list repozytoriów.
    for pattern in (
        "/var/cache/opkg/*.ipk",
        "/var/cache/opkg/archives/*.ipk",
        "/home/root/*.ipk.part",
        "/home/root/*.ipk.tmp",
    ):
        for path in glob.glob(pattern):
            if os.path.isfile(path) and _is_on_root_filesystem(path):
                candidates[os.path.realpath(path)] = "pobrany plik tymczasowy OPKG"

    # Zrzuty pamięci po awarii. Ograniczamy się do katalogu domowego i /tmp.
    for pattern in (
        "/home/root/core",
        "/home/root/core.*",
        "/home/root/*.core",
        "/home/root/enigma2.core*",
        "/tmp/core",
        "/tmp/core.*",
        "/tmp/*.core",
    ):
        for path in glob.glob(pattern):
            if os.path.isfile(path) and _is_on_root_filesystem(path):
                candidates[os.path.realpath(path)] = "zrzut pamięci po awarii"

    entries = []
    for path, category in candidates.items():
        try:
            entries.append({"path": path, "category": category, "size": _file_size(path)})
        except Exception:
            pass
    entries.sort(key=lambda item: item.get("size", 0), reverse=True)
    return entries


def safe_flash_cleanup_preview():
    entries = safe_flash_cleanup_candidates()
    total = sum(item.get("size", 0) for item in entries)
    lines = [
        "BEZPIECZNE CZYSZCZENIE PAMIĘCI FLASH",
        "",
        "E2 Doctor nie usuwa ustawień Enigma2, list kanałów, EPG, piconów, wtyczek ani konfiguracji OSCam.",
        "Usuwane mogą być wyłącznie stare crashlogi, pobrane archiwa OPKG i zrzuty pamięci po awarii.",
        "",
        "Znaleziono: %d plików | możliwe do odzyskania: %s" % (len(entries), format_bytes(total)),
        "",
    ]
    if entries:
        for item in entries[:80]:
            lines.append("- %s | %s | %s" % (format_bytes(item.get("size", 0)), item.get("category", ""), item.get("path", "")))
        if len(entries) > 80:
            lines.append("... oraz %d kolejnych plików" % (len(entries) - 80))
    else:
        lines.append("Nie znaleziono plików kwalifikujących się do bezpiecznego usunięcia.")
    return "\n".join(lines), entries, total


def perform_safe_flash_cleanup(entries=None):
    entries = list(entries if entries is not None else safe_flash_cleanup_candidates())
    removed = []
    failed = []
    recovered = 0
    for item in entries:
        path = item.get("path", "")
        if not path or not os.path.isfile(path) or not _is_on_root_filesystem(path):
            continue
        try:
            size = _file_size(path)
            os.unlink(path)
            removed.append(path)
            recovered += size
        except Exception as exc:
            failed.append("%s: %s" % (path, exc))
    record_operation(
        "Bezpieczne czyszczenie pamięci flash",
        "information",
        {"removed": removed, "failed": failed, "recovered": recovered},
        False,
    )
    return removed, failed, recovered


def reload_bouquets_safe():
    if eDVBDB is None:
        raise RuntimeError("Interfejs eDVBDB jest niedostępny w tym systemie.")
    db = eDVBDB.getInstance()
    db.reloadServicelist()
    db.reloadBouquets()
    return True


def storage_diagnostic_text():
    parts = ["DIAGNOSTYKA NOŚNIKÓW I SYSTEMÓW PLIKÓW", ""]
    for title, command in (
        ("Wykorzystanie miejsca", "df -hT 2>/dev/null || df -h"),
        ("Punkty montowania", "mount"),
        ("Ostatnie komunikaty kernela", "dmesg 2>/dev/null | tail -n 100"),
    ):
        code, output, error = run_command(command, timeout=12)
        parts.extend([title.upper(), "-" * 58, output or error or "Brak danych", ""])
    parts.append("E2 Doctor nie wykonuje formatowania ani naprawy systemu plików podczas pracy Enigma2.")
    return "\n".join(parts)


ACTION_REGISTRY = {
    "safe_flash_cleanup": {
        "title": "Bezpiecznie oczyść pamięć flash",
        "description": "Usuń wyłącznie stare crashlogi, archiwa OPKG i zrzuty pamięci. Ustawienia oraz dane Enigma2 pozostają bez zmian.",
        "status": STATUS_WARN,
        "mutating": True,
    },
    "find_large_files": {
        "title": "Pokaż największe pliki",
        "description": "Znajdź pliki zajmujące najwięcej miejsca bez ich usuwania.",
        "status": STATUS_INFO,
        "mutating": False,
    },
    "safe_ram_refresh": {
        "title": "Bezpiecznie odśwież pamięć RAM",
        "description": "Zapisz dane na dysk i zwolnij wyłącznie cache jądra. Procesy i konfiguracja nie są zatrzymywane.",
        "status": STATUS_WARN,
        "mutating": True,
    },
    "show_processes": {
        "title": "Pokaż procesy zużywające RAM",
        "description": "Sprawdź, które procesy zajmują najwięcej pamięci. Nic nie zostanie zakończone.",
        "status": STATUS_INFO,
        "mutating": False,
    },
    "repair_bouquet_refs": {
        "title": "Napraw odwołania do bukietów",
        "description": "Wykonaj kopię plików indeksu i usuń wyłącznie wpisy kierujące do nieistniejących bukietów.",
        "status": STATUS_WARN,
        "mutating": True,
    },
    "reload_bouquets": {
        "title": "Przeładuj listę kanałów",
        "description": "Odśwież listy w Enigma2 bez kasowania bukietów, głowic i ustawień.",
        "status": STATUS_INFO,
        "mutating": True,
    },
    "remove_opkg_lock": {
        "title": "Usuń nieaktywną blokadę OPKG",
        "description": "Usuń blokadę tylko wtedy, gdy menedżer pakietów nie jest uruchomiony.",
        "status": STATUS_WARN,
        "mutating": True,
    },
    "restart_oscam": {
        "title": "Uruchom ponownie OSCam",
        "description": "Wyszukaj właściwy skrypt systemowy i wykonaj bezpieczny restart usługi.",
        "status": STATUS_WARN,
        "mutating": True,
    },
    "sync_time": {
        "title": "Synchronizuj datę i czas",
        "description": "Uruchom dostępny w systemie mechanizm synchronizacji czasu.",
        "status": STATUS_WARN,
        "mutating": True,
    },
    "network_test": {
        "title": "Wykonaj rozszerzony test sieci",
        "description": "Sprawdź interfejs, adres IP, bramę, DNS i HTTPS bez zmieniania konfiguracji.",
        "status": STATUS_INFO,
        "mutating": False,
    },
    "disable_suspect_plugin": {
        "title": "Tymczasowo wyłącz podejrzaną wtyczkę",
        "description": "Zmień nazwę katalogu wtyczki bez jej kasowania. Operację można cofnąć.",
        "status": STATUS_ERROR,
        "mutating": True,
    },
    "cleanup_crashlogs": {
        "title": "Usuń stare crashlogi",
        "description": "Pozostaw trzy najnowsze logi potrzebne do dalszej diagnostyki.",
        "status": STATUS_WARN,
        "mutating": True,
    },
    "emergency_report": {
        "title": "Utwórz raport awaryjny",
        "description": "Zapisz raport możliwy do przekazania osobie udzielającej pomocy.",
        "status": STATUS_INFO,
        "mutating": False,
    },
    "storage_diagnostic": {
        "title": "Pokaż diagnostykę nośników",
        "description": "Wyświetl montowania, wolne miejsce i ostatnie komunikaty kernela bez naprawy systemu plików.",
        "status": STATUS_INFO,
        "mutating": False,
    },
    "restart_gui": {
        "title": "Uruchom ponownie GUI Enigma2",
        "description": "Zamknij i ponownie uruchom interfejs Enigma2. Nagrania i działające procesy mogą zostać przerwane.",
        "status": STATUS_WARN,
        "mutating": True,
    },
}


def _append_action(actions, name):
    if name in ACTION_REGISTRY and name not in actions:
        actions.append(name)


def available_problem_actions(item):
    item = item or {}
    actions = []
    solution = get_solution(item)
    primary = solution.get("action")
    if primary:
        _append_action(actions, primary)

    solution_id = item.get("solution_id", "")
    module = item.get("module", "")
    title = item.get("title", "")
    context = item.get("context") or {}

    if solution_id in ("flash_low", "flash_critical", "crash_no_space") or title == "Pamięć flash":
        _append_action(actions, "safe_flash_cleanup")
        _append_action(actions, "find_large_files")
    if solution_id in ("ram_low", "ram_critical") or title == "Pamięć RAM":
        _append_action(actions, "safe_ram_refresh")
        _append_action(actions, "show_processes")
        _append_action(actions, "restart_gui")
    if solution_id in ("system_load_high",):
        _append_action(actions, "show_processes")
    if module == "channels":
        if solution_id == "bouquet_missing_refs":
            _append_action(actions, "repair_bouquet_refs")
        _append_action(actions, "reload_bouquets")
    if module == "network" or solution_id in ("dns_error", "https_error", "crash_ssl", "crash_network"):
        _append_action(actions, "network_test")
    if solution_id == "time_invalid":
        _append_action(actions, "sync_time")
    if module == "packages" and solution_id == "opkg_lock":
        _append_action(actions, "remove_opkg_lock")
    if module == "oscam" or solution_id == "oscam_stopped":
        _append_action(actions, "restart_oscam")
    if module == "storage" or solution_id in ("storage_warning", "mount_readonly"):
        _append_action(actions, "storage_diagnostic")
        _append_action(actions, "find_large_files")
    if module == "crashlogs" or str(solution_id).startswith("crash_"):
        if item.get("safe_action") == "disable_suspect_plugin" or context.get("plugin_path"):
            _append_action(actions, "disable_suspect_plugin")
        _append_action(actions, "cleanup_crashlogs")
        _append_action(actions, "emergency_report")
        _append_action(actions, "restart_gui")
    return actions


def quick_repair_entries(results):
    entries = []
    seen = set()
    problems = [item for item in (results or []) if item.get("status") in (STATUS_WARN, STATUS_ERROR)]
    problems.sort(key=lambda item: STATUS_RANK.get(item.get("status"), 0), reverse=True)
    for item in problems:
        for action in available_problem_actions(item):
            context = item.get("context") or {}
            unique = action
            if action == "disable_suspect_plugin":
                unique = "%s|%s" % (action, context.get("plugin_path", context.get("plugin", "")))
            if unique in seen:
                continue
            seen.add(unique)
            entries.append({"action": action, "item": item})
    return entries


def action_title(action_name):
    return ACTION_REGISTRY.get(action_name, {}).get("title", action_name)


def action_description(action_name):
    return ACTION_REGISTRY.get(action_name, {}).get("description", "")


def action_button_label(action_name):
    labels = {
        "safe_flash_cleanup": "Oczyść flash",
        "find_large_files": "Duże pliki",
        "safe_ram_refresh": "Odśwież RAM",
        "show_processes": "Procesy RAM",
        "repair_bouquet_refs": "Napraw bukiety",
        "reload_bouquets": "Przeładuj listę",
        "remove_opkg_lock": "Usuń blokadę",
        "restart_oscam": "Restart OSCam",
        "sync_time": "Synchronizuj czas",
        "network_test": "Test sieci",
        "disable_suspect_plugin": "Wyłącz wtyczkę",
        "cleanup_crashlogs": "Usuń stare logi",
        "emergency_report": "Raport awaryjny",
        "storage_diagnostic": "Diagnostyka",
        "restart_gui": "Restart GUI",
    }
    return labels.get(action_name, action_title(action_name))


class E2DoctorActionMixin(object):
    def request_action(self, action_name, item=None, on_done=None):
        self._e2d_pending_action = action_name
        self._e2d_pending_item = item or {}
        self._e2d_pending_done = on_done

        if action_name == "safe_flash_cleanup":
            preview, entries, total = safe_flash_cleanup_preview()
            self._e2d_flash_entries = entries
            if not entries:
                self.session.open(E2DoctorTextScreen, "Bezpieczne czyszczenie flash", preview, "Brak plików do usunięcia")
                return
            text = (
                "E2 Doctor znalazł %d bezpiecznych plików o łącznym rozmiarze %s.\n\n"
                "Usunięte zostaną wyłącznie stare crashlogi, archiwa OPKG i zrzuty pamięci. "
                "Ustawienia, listy kanałów, wtyczki, EPG i picony pozostaną bez zmian.\n\nKontynuować?"
            ) % (len(entries), format_bytes(total))
            self.session.openWithCallback(self._confirmed_action, MessageBox, text, MessageBox.TYPE_YESNO)
            return

        confirmations = {
            "safe_ram_refresh": "Bezpiecznie odświeżyć pamięć podręczną RAM?\n\nProcesy nie zostaną zakończone, a ustawienia nie zostaną zmienione.",
            "repair_bouquet_refs": tr("confirm_repair_bouquets"),
            "remove_opkg_lock": tr("confirm_remove_lock"),
            "restart_oscam": tr("confirm_restart_oscam"),
            "sync_time": tr("confirm_sync_time"),
            "disable_suspect_plugin": "Tymczasowo wyłączyć podejrzaną wtyczkę %s?\n\nKatalog zostanie jedynie przemianowany. Operację można cofnąć w Narzędziach E2 Doctor." % (item or {}).get("context", {}).get("plugin", ""),
            "cleanup_crashlogs": "Usunąć stare crashlogi i pozostawić trzy najnowsze?",
            "reload_bouquets": "Przeładować listę kanałów bez usuwania ustawień i bukietów?",
            "restart_gui": "Uruchomić ponownie GUI Enigma2?\n\nPrzed wykonaniem zakończ trwające nagrania i ważne operacje.",
        }
        if action_name in confirmations:
            self.session.openWithCallback(self._confirmed_action, MessageBox, confirmations[action_name], MessageBox.TYPE_YESNO)
        else:
            self._execute_pending_action()

    def _confirmed_action(self, answer):
        if answer:
            self._execute_pending_action()

    def _finish_action(self, changed=False):
        callback = getattr(self, "_e2d_pending_done", None)
        if callback:
            try:
                callback(changed)
            except Exception:
                pass

    def _show_action_message(self, message, changed=False, error=False):
        box_type = MessageBox.TYPE_ERROR if error else MessageBox.TYPE_INFO
        self.session.openWithCallback(lambda *args: self._finish_action(changed), MessageBox, message, box_type, timeout=10 if not error else 0)

    def _open_action_text(self, title, text, status="E2 Doctor 2.3"):
        self.session.openWithCallback(lambda *args: self._finish_action(False), E2DoctorTextScreen, title, text, status)

    def _execute_pending_action(self):
        action = getattr(self, "_e2d_pending_action", "")
        item = getattr(self, "_e2d_pending_item", {}) or {}
        try:
            if action == "safe_flash_cleanup":
                removed, failed, recovered = perform_safe_flash_cleanup(getattr(self, "_e2d_flash_entries", None))
                text = "Bezpieczne czyszczenie zakończone.\n\nUsunięto plików: %d\nOdzyskano: %s" % (len(removed), format_bytes(recovered))
                if failed:
                    text += "\nNie udało się usunąć: %d" % len(failed)
                self._show_action_message(text, True)
            elif action == "find_large_files":
                self._open_action_text("Największe pliki", largest_files_text(), "Analiza bez usuwania danych")
            elif action == "safe_ram_refresh":
                before, after = safe_ram_refresh()
                difference = max(0, after - before)
                self._show_action_message(
                    "Pamięć podręczna została bezpiecznie odświeżona.\n\nDostępne przed: %s\nDostępne po: %s\nRóżnica: %s\n\nProcesy nie zostały zakończone." % (
                        format_bytes(before), format_bytes(after), format_bytes(difference)
                    ),
                    True,
                )
            elif action == "show_processes":
                self._open_action_text("Procesy i pamięć RAM", top_memory_processes_text(), "Diagnostyka bez kończenia procesów")
            elif action == "repair_bouquet_refs":
                removed, backup_dir = repair_missing_bouquet_refs()
                self._show_action_message("Usunięto błędne odwołania: %d\nKopia bezpieczeństwa:\n%s" % (removed, backup_dir), True)
            elif action == "reload_bouquets":
                reload_bouquets_safe()
                self._show_action_message("Lista kanałów została przeładowana.\nNie usunięto bukietów ani ustawień tunera.", True)
            elif action == "remove_opkg_lock":
                removed = remove_inactive_opkg_locks()
                if removed:
                    self._show_action_message("Usunięto nieaktywne blokady OPKG:\n%s" % "\n".join(removed), True)
                else:
                    self._show_action_message("Nie znaleziono nieaktywnej blokady OPKG.", False)
            elif action == "restart_oscam":
                command, _ = restart_oscam_service()
                self._show_action_message("OSCam został uruchomiony ponownie.\nUżyte polecenie: %s" % command, True)
            elif action == "sync_time":
                command, _ = sync_system_time()
                self._show_action_message("Uruchomiono synchronizację czasu.\nUżyte polecenie: %s" % command, True)
            elif action == "network_test":
                self._open_action_text("Rozszerzony test sieci", network_diagnostic_text(), "Test bez zmiany konfiguracji")
            elif action == "disable_suspect_plugin":
                original, disabled = disable_suspect_plugin(item.get("context") or {})
                self._show_action_message(
                    "Wtyczka została tymczasowo wyłączona.\n\nOryginał: %s\nWyłączony katalog: %s\n\nWykonaj restart GUI. Zmianę można cofnąć w Narzędziach." % (original, disabled),
                    True,
                )
            elif action == "cleanup_crashlogs":
                removed = cleanup_old_crashlogs(3)
                self._show_action_message("Usunięto starych crashlogów: %d\nPozostawiono trzy najnowsze." % len(removed), True)
            elif action == "emergency_report":
                path = emergency_report()
                self._show_action_message("Raport awaryjny zapisano w:\n%s" % path, False)
            elif action == "storage_diagnostic":
                self._open_action_text("Nośniki i systemy plików", storage_diagnostic_text(), "Diagnostyka bez formatowania")
            elif action == "restart_gui":
                from Screens.Standby import TryQuitMainloop
                self.session.open(TryQuitMainloop, 3)
            else:
                self._show_action_message("Nieznane działanie: %s" % action, False, True)
        except Exception as error:
            self._show_action_message("Operacja nie powiodła się:\n%s" % error, False, True)


def premium_text_skin(screen_name):
    w, h, m = E2D_UI_W, E2D_UI_H, E2D_MARGIN
    footer_y = h - (76 if E2D_FHD else 58)
    return """
    <screen name="%(name)s" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor" backgroundColor="#0A141B" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,112" backgroundColor="#122A38" transparent="0" />
        <widget name="accent" position="0,0" size="12,112" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="title" position="%(m)d,14" size="%(content_w)d,50" font="Regular;%(title_font)d" halign="center" foregroundColor="#FFFFFF" />
        <widget name="status" position="%(m)d,65" size="%(content_w)d,34" font="Regular;%(small)d" halign="center" foregroundColor="#78DCE4" />
        <widget name="body" position="%(m)d,126" size="%(content_w)d,%(body_h)d" font="Regular;%(body_font)d" scrollbarMode="showOnDemand" />
        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#10212B" transparent="0" />
        <widget source="key_red" render="Label" position="%(m)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#FF6970" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#5BEA87" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#F4D85B" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#60B7F5" />
    </screen>
    """ % {
        "name": screen_name, "w": w, "h": h, "m": m, "content_w": w - 2 * m,
        "title_font": 40 if E2D_FHD else 32, "small": E2D_FONT_SMALL,
        "body_h": footer_y - 138, "body_font": E2D_FONT_BODY,
        "footer_bg_y": footer_y - 10, "footer_bg_h": h - footer_y + 10, "footer_y": footer_y,
        "key_w": int((w - 2 * m) / 4), "green_x": m + int((w - 2 * m) / 4),
        "yellow_x": m + 2 * int((w - 2 * m) / 4), "blue_x": m + 3 * int((w - 2 * m) / 4),
    }


def premium_results_skin(screen_name):
    w, h, m = E2D_UI_W, E2D_UI_H, E2D_MARGIN
    footer_y = h - (76 if E2D_FHD else 58)
    return """
    <screen name="%(name)s" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor" backgroundColor="#0A141B" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,112" backgroundColor="#122A38" transparent="0" />
        <widget name="accent" position="0,0" size="12,112" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="title" position="%(m)d,14" size="%(content_w)d,50" font="Regular;%(title_font)d" halign="center" foregroundColor="#FFFFFF" />
        <widget name="status" position="%(m)d,65" size="%(content_w)d,34" font="Regular;%(small)d" halign="center" foregroundColor="#9EC1CF" />
        <widget name="list" position="%(m)d,126" size="%(content_w)d,%(list_h)d" scrollbarMode="showOnDemand" />
        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#10212B" transparent="0" />
        <widget source="key_red" render="Label" position="%(m)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#FF6970" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#5BEA87" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#F4D85B" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body_font)d" halign="center" foregroundColor="#60B7F5" />
    </screen>
    """ % {
        "name": screen_name, "w": w, "h": h, "m": m, "content_w": w - 2 * m,
        "title_font": 40 if E2D_FHD else 32, "small": E2D_FONT_SMALL,
        "list_h": footer_y - 138, "footer_bg_y": footer_y - 10, "footer_bg_h": h - footer_y + 10,
        "footer_y": footer_y, "body_font": E2D_FONT_BODY,
        "key_w": int((w - 2 * m) / 4), "green_x": m + int((w - 2 * m) / 4),
        "yellow_x": m + 2 * int((w - 2 * m) / 4), "blue_x": m + 3 * int((w - 2 * m) / 4),
    }


def dashboard_skin_21():
    w, h, m = E2D_UI_W, E2D_UI_H, E2D_MARGIN
    header_h = 220 if E2D_FHD else 176
    summary_y = header_h + 12
    summary_h = 92 if E2D_FHD else 70
    banner_y = summary_y + summary_h + 10
    banner_h = 52 if E2D_FHD else 42
    list_y = banner_y + banner_h + 10
    footer_h = 72 if E2D_FHD else 54
    footer_y = h - footer_h - 18
    list_h = footer_y - list_y - 8
    logo_panel = 168 if E2D_FHD else 132
    logo = E2D_LOGO_SIZE
    logo_x = m + int((logo_panel - logo) / 2)
    logo_y = int((header_h - logo) / 2)
    score_w = 320 if E2D_FHD else 242
    score_x = w - m - score_w
    title_x = m + logo_panel + 26
    title_w = score_x - title_x - 22
    gap = 12
    card_w = int((w - 2 * m - 3 * gap) / 4)
    key_w = int((w - 2 * m) / 4)
    return """
    <screen name="E2DoctorDashboard" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor" backgroundColor="#08131A" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,%(header_h)d" backgroundColor="#112734" transparent="0" />
        <widget name="top_glow" position="0,0" size="%(w)d,6" backgroundColor="#29D4DE" transparent="0" />
        <widget name="accent" position="0,0" size="12,%(header_h)d" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="logo_panel" position="%(m)d,%(logo_panel_y)d" size="%(logo_panel)d,%(logo_panel)d" backgroundColor="#0B1D27" transparent="0" />
        <widget name="logo_line" position="%(m)d,%(logo_line_y)d" size="%(logo_panel)d,4" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="logo" position="%(logo_x)d,%(logo_y)d" size="%(logo)d,%(logo)d" pixmap="%(logo_path)s" alphatest="blend" />
        <widget name="brand_badge" position="%(title_x)d,%(badge_y)d" size="%(title_w)d,30" font="Regular;%(tiny)d" foregroundColor="#5EE6EE" />
        <widget name="title" position="%(title_x)d,%(title_y)d" size="%(title_w)d,58" font="Regular;%(main_title)d" foregroundColor="#FFFFFF" />
        <widget name="subtitle" position="%(title_x)d,%(subtitle_y)d" size="%(title_w)d,38" font="Regular;%(body)d" foregroundColor="#B4C9D4" />
        <widget name="change" position="%(title_x)d,%(change_y)d" size="%(title_w)d,34" font="Regular;%(small)d" foregroundColor="#78DCE4" />
        <widget name="score_bg" position="%(score_x)d,%(score_y)d" size="%(score_w)d,%(score_h)d" backgroundColor="#081820" transparent="0" />
        <widget name="score_top" position="%(score_x)d,%(score_y)d" size="%(score_w)d,5" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="score_title" position="%(score_x2)d,%(score_title_y)d" size="%(score_w2)d,32" font="Regular;%(small)d" halign="center" foregroundColor="#A4BBC8" />
        <widget name="score_value" position="%(score_x2)d,%(score_value_y)d" size="%(score_w2)d,60" font="Regular;%(score_font)d" halign="center" foregroundColor="#FFFFFF" />
        <widget name="score_grade" position="%(score_x2)d,%(score_grade_y)d" size="%(score_w2)d,32" font="Regular;%(small)d" halign="center" foregroundColor="#62E28B" />
        <widget name="score_bar" position="%(score_bar_x)d,%(score_bar_y)d" size="%(score_bar_w)d,12" borderWidth="1" />
        <widget name="ok_bg" position="%(m)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#123827" transparent="0" />
        <widget name="ok_line" position="%(m)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#51E181" transparent="0" />
        <widget name="ok_count" position="%(m)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#5FE68A" />
        <widget name="ok_label" position="%(m)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#BEDDCA" />
        <widget name="info_bg" position="%(card2_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#123249" transparent="0" />
        <widget name="info_line" position="%(card2_x)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#52BEF0" transparent="0" />
        <widget name="info_count" position="%(card2_x)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#61C8F4" />
        <widget name="info_label" position="%(card2_x)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#BBD3DF" />
        <widget name="warn_bg" position="%(card3_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#423815" transparent="0" />
        <widget name="warn_line" position="%(card3_x)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#F2D14D" transparent="0" />
        <widget name="warn_count" position="%(card3_x)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#F5D85A" />
        <widget name="warn_label" position="%(card3_x)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#E4DAB2" />
        <widget name="error_bg" position="%(card4_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#482027" transparent="0" />
        <widget name="error_line" position="%(card4_x)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#FF626B" transparent="0" />
        <widget name="error_count" position="%(card4_x)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#FF737A" />
        <widget name="error_label" position="%(card4_x)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#E9C0C4" />
        <widget name="recommend_bg" position="%(m)d,%(banner_y)d" size="%(content_w)d,%(banner_h)d" backgroundColor="#173443" transparent="0" />
        <widget name="recommend_line" position="%(m)d,%(banner_y)d" size="8,%(banner_h)d" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="recommendation" position="%(recommend_x)d,%(recommend_text_y)d" size="%(recommend_w)d,30" font="Regular;%(small)d" foregroundColor="#E5F6F8" />
        <widget name="dashboard" position="%(m)d,%(list_y)d" size="%(content_w)d,%(list_h)d" scrollbarMode="showOnDemand" />
        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#0F222C" transparent="0" />
        <widget source="key_red" render="Label" position="%(m)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#FF6970" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#5BEA87" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#F4D85B" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#60B7F5" />
        <widget name="footer" position="%(m)d,%(version_y)d" size="%(content_w)d,24" font="Regular;%(tiny)d" halign="center" foregroundColor="#7C95A3" />
    </screen>
    """ % {
        "w": w, "h": h, "m": m, "header_h": header_h, "content_w": w - 2 * m,
        "logo_panel": logo_panel, "logo_panel_y": int((header_h - logo_panel) / 2),
        "logo_line_y": int((header_h - logo_panel) / 2), "logo_x": logo_x, "logo_y": logo_y,
        "logo": logo, "logo_path": E2D_LOGO_PATH, "title_x": title_x, "title_w": title_w,
        "badge_y": 24 if E2D_FHD else 17, "tiny": E2D_FONT_TINY,
        "title_y": 53 if E2D_FHD else 39, "main_title": 52 if E2D_FHD else 41,
        "subtitle_y": 112 if E2D_FHD else 84, "body": E2D_FONT_BODY,
        "change_y": 158 if E2D_FHD else 122, "small": E2D_FONT_SMALL,
        "score_x": score_x, "score_y": 24 if E2D_FHD else 18, "score_w": score_w,
        "score_h": 176 if E2D_FHD else 140, "score_x2": score_x + 10, "score_w2": score_w - 20,
        "score_title_y": 38 if E2D_FHD else 28, "score_value_y": 72 if E2D_FHD else 54,
        "score_font": 54 if E2D_FHD else 40, "score_grade_y": 132 if E2D_FHD else 103,
        "score_bar_x": score_x + 24, "score_bar_y": 178 if E2D_FHD else 139, "score_bar_w": score_w - 48,
        "summary_y": summary_y, "summary_h": summary_h, "card_w": card_w,
        "card2_x": m + card_w + gap, "card3_x": m + 2 * (card_w + gap), "card4_x": m + 3 * (card_w + gap),
        "count_y": summary_y + (12 if E2D_FHD else 7), "label_y": summary_y + (54 if E2D_FHD else 40),
        "count_font": 36 if E2D_FHD else 28, "banner_y": banner_y, "banner_h": banner_h,
        "recommend_x": m + 22, "recommend_text_y": banner_y + (11 if E2D_FHD else 7), "recommend_w": w - 2 * m - 34,
        "list_y": list_y, "list_h": list_h, "footer_bg_y": footer_y - 10, "footer_bg_h": h - footer_y + 10,
        "footer_y": footer_y, "key_h": 42 if E2D_FHD else 34, "key_w": key_w,
        "green_x": m + key_w, "yellow_x": m + 2 * key_w, "blue_x": m + 3 * key_w,
        "version_y": h - 26,
    }


class E2DoctorDashboardList(MenuList):
    def __init__(self, entries=None):
        MenuList.__init__(self, entries or [], enableWrapAround=True, content=eListboxPythonMultiContent)
        self.l.setFont(0, gFont("Regular", E2D_FONT_TITLE))
        self.l.setFont(1, gFont("Regular", E2D_FONT_SMALL))
        self.l.setFont(2, gFont("Regular", E2D_FONT_BODY))
        self.l.setFont(3, gFont("Regular", E2D_FONT_TINY))
        self.l.setItemHeight(74 if E2D_FHD else 57)
        self.l.setBuildFunc(self.build_entry)

    def build_entry(self, key, code, title, subtitle, status, badge):
        status_color = STATUS_COLORS.get(status, 0x008A9AA5)
        item_h = 74 if E2D_FHD else 57
        content_w = E2D_LIST_W
        badge_w = 226 if E2D_FHD else 172
        code_w = 72 if E2D_FHD else 56
        title_y = 8 if E2D_FHD else 4
        subtitle_y = 42 if E2D_FHD else 29
        return [
            None,
            MultiContentEntryText(pos=(0, 2), size=(content_w, item_h - 4), font=1, text="", backcolor=0x0013212A, backcolor_sel=0x00243E4B),
            MultiContentEntryText(pos=(0, 2), size=(7, item_h - 4), font=1, text="", backcolor=status_color, backcolor_sel=status_color),
            MultiContentEntryText(pos=(18, 10 if E2D_FHD else 8), size=(code_w, item_h - (20 if E2D_FHD else 16)), font=3, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=code, color=0x00FFFFFF, color_sel=0x00FFFFFF, backcolor=status_color, backcolor_sel=status_color),
            MultiContentEntryText(pos=(code_w + 34, title_y), size=(content_w - code_w - badge_w - 66, 36), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=title, color=0x00FFFFFF, color_sel=0x00FFFFFF, backcolor_sel=0x00243E4B),
            MultiContentEntryText(pos=(code_w + 36, subtitle_y), size=(content_w - code_w - badge_w - 70, 26), font=1, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=subtitle, color=0x009CB3BF, color_sel=0x00E1F1F5, backcolor_sel=0x00243E4B),
            MultiContentEntryText(pos=(content_w - badge_w - 18, 8), size=(badge_w, item_h - 16), font=2, flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=badge, color=status_color, color_sel=status_color, backcolor_sel=0x00243E4B),
        ]


class E2DoctorTextScreen(Screen):
    skin = premium_text_skin("E2DoctorTextScreen")

    def __init__(self, session, title, text, status="E2 Doctor 2.3"):
        Screen.__init__(self, session)
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label(title)
        self["status"] = Label(status)
        self["body"] = ScrollLabel(text)
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("")
        self["key_yellow"] = StaticText("")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "cancel": self.close, "red": self.close, "blue": self.close, "ok": self.close,
                "up": self["body"].pageUp, "down": self["body"].pageDown,
                "left": self["body"].pageUp, "right": self["body"].pageDown,
            },
            -1,
        )


class E2DoctorProblemActionsScreen(E2DoctorActionMixin, Screen):
    skin = premium_results_skin("E2DoctorProblemActionsScreen")

    def __init__(self, session, item, title="Działania dla problemu"):
        Screen.__init__(self, session)
        self.item = item or {}
        self.changed = False
        self.actions_list = available_problem_actions(self.item)
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label(title)
        self["status"] = Label("Wybierz działanie. Każda zmiana wymaga potwierdzenia użytkownika.")
        rows = []
        for action in self.actions_list:
            meta = ACTION_REGISTRY.get(action, {})
            rows.append((meta.get("status", STATUS_INFO), meta.get("title", action), meta.get("description", "")))
        if not rows:
            rows.append((STATUS_INFO, "Brak bezpiecznej automatycznej naprawy", "Skorzystaj z instrukcji ręcznej pokazanej przez E2 Doctor."))
        self["list"] = E2DoctorV2ResultList(rows)
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Wykonaj")
        self["key_yellow"] = StaticText("Opis")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "cancel": self.finish, "red": self.finish, "blue": self.finish,
                "ok": self.execute_selected, "green": self.execute_selected, "yellow": self.show_selected,
            },
            -1,
        )

    def selected_action(self):
        index = self["list"].getSelectedIndex()
        if 0 <= index < len(self.actions_list):
            return self.actions_list[index]
        return None

    def show_selected(self):
        action = self.selected_action()
        if not action:
            return
        meta = ACTION_REGISTRY.get(action, {})
        text = "%s\n\n%s\n\nWYKRYTY PROBLEM\n%s\n%s" % (
            meta.get("title", action), meta.get("description", ""),
            self.item.get("title", ""), self.item.get("summary", ""),
        )
        self.session.open(E2DoctorTextScreen, "Opis działania", text, "E2 Doctor — bezpieczna naprawa")

    def execute_selected(self):
        action = self.selected_action()
        if action:
            self.request_action(action, self.item, self.action_finished)

    def action_finished(self, changed=False):
        self.changed = self.changed or bool(changed)

    def finish(self):
        self.close(self.changed)


class E2DoctorSolutionScreen(E2DoctorActionMixin, Screen):
    skin = premium_text_skin("E2DoctorSolutionScreen")

    def __init__(self, session, item):
        Screen.__init__(self, session)
        self.item = item
        self.solution = get_solution(item)
        self.actions_list = available_problem_actions(item)
        self.primary_action = self.actions_list[0] if self.actions_list else None
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label("Diagnoza i możliwe rozwiązanie")
        self["status"] = Label("%s — %s" % (status_name(item.get("status")), item.get("title", "")))
        self["body"] = ScrollLabel(build_solution_text(item, include_technical=False))
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText(action_button_label(self.primary_action) if self.primary_action else "Brak auto-naprawy")
        self["key_yellow"] = StaticText("Dane techniczne")
        self["key_blue"] = StaticText("Działania" if self.actions_list else "Zapisz instrukcję")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions", "InfoActions", "MenuActions"],
            {
                "cancel": self.close, "red": self.close, "green": self.perform_primary,
                "yellow": self.show_technical, "blue": self.open_actions_or_save,
                "info": self.save_instruction, "menu": self.save_instruction,
                "up": self["body"].pageUp, "down": self["body"].pageDown,
                "left": self["body"].pageUp, "right": self["body"].pageDown,
            },
            -1,
        )

    def perform_primary(self):
        if not self.primary_action:
            self.session.open(MessageBox, tr("no_safe_action"), MessageBox.TYPE_INFO, timeout=7)
            return
        self.request_action(self.primary_action, self.item, self.primary_finished)

    def primary_finished(self, changed=False):
        if changed:
            self.close(True)

    def open_actions_or_save(self):
        if self.actions_list:
            self.session.openWithCallback(self.actions_closed, E2DoctorProblemActionsScreen, self.item)
        else:
            self.save_instruction()

    def actions_closed(self, changed=False):
        if changed:
            self.close(True)

    def show_technical(self):
        self.session.open(E2DoctorTextScreen, "Dane techniczne — %s" % self.item.get("title", ""), self.item.get("details", "Brak danych technicznych."), "Surowe dane diagnostyczne")

    def save_instruction(self):
        try:
            path = save_solution_instruction(self.item)
            self.session.open(MessageBox, "Instrukcję zapisano w:\n%s" % path, MessageBox.TYPE_INFO, timeout=8)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się zapisać instrukcji:\n%s" % error, MessageBox.TYPE_ERROR)


class E2DoctorResultsScreen(Screen):
    skin = premium_results_skin("E2DoctorResultsScreen")

    def __init__(self, session, title, results, status_text=""):
        Screen.__init__(self, session)
        self.results = list(results or [])
        self.changed = False
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label(title)
        counts = result_counts(self.results)
        self["status"] = Label(status_text or "OK %d | Informacje %d | Ostrzeżenia %d | Błędy %d" % (
            counts.get(STATUS_OK, 0), counts.get(STATUS_INFO, 0), counts.get(STATUS_WARN, 0), counts.get(STATUS_ERROR, 0)
        ))
        self["list"] = E2DoctorV2ResultList([])
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Odczyt / naprawa")
        self["key_yellow"] = StaticText("Raport")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "cancel": self.finish, "red": self.finish, "blue": self.finish,
                "ok": self.open_selected, "green": self.open_selected, "yellow": self.save_report,
            },
            -1,
        )
        self.refresh_list()

    def refresh_list(self):
        self["list"].setList([(item.get("status"), item.get("title", ""), item.get("summary", "")) for item in self.results])

    def open_selected(self):
        index = self["list"].getSelectedIndex()
        if 0 <= index < len(self.results):
            self.session.openWithCallback(self.solution_closed, E2DoctorSolutionScreen, self.results[index])

    def solution_closed(self, changed=False):
        if changed:
            self.changed = True

    def save_report(self):
        try:
            path = make_report(self.results)
            self.session.open(MessageBox, "Raport zapisano w:\n%s" % path, MessageBox.TYPE_INFO, timeout=9)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się utworzyć raportu:\n%s" % error, MessageBox.TYPE_ERROR)

    def finish(self):
        self.close(self.changed)


class E2DoctorQuickRepairScreen(E2DoctorActionMixin, Screen):
    skin = premium_results_skin("E2DoctorQuickRepairScreen")

    def __init__(self, session, results):
        Screen.__init__(self, session)
        self.results = list(results or [])
        self.entries = quick_repair_entries(self.results)
        self.changed = False
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label("Centrum szybkiej naprawy")
        self["status"] = Label("Dostępne działania: %d | Nic nie zostanie wykonane bez potwierdzenia" % len(self.entries))
        rows = []
        for entry in self.entries:
            action = entry.get("action")
            item = entry.get("item") or {}
            meta = ACTION_REGISTRY.get(action, {})
            rows.append((meta.get("status", STATUS_INFO), meta.get("title", action), "Problem: %s — %s" % (item.get("title", ""), item.get("summary", ""))))
        if not rows:
            rows.append((STATUS_OK, "Brak problemów wymagających bezpiecznej naprawy", "System nie zgłasza działań, które E2 Doctor może wykonać automatycznie."))
        self["list"] = E2DoctorV2ResultList(rows)
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Wykonaj")
        self["key_yellow"] = StaticText("Opis")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions"],
            {
                "cancel": self.finish, "red": self.finish, "blue": self.finish,
                "ok": self.execute_selected, "green": self.execute_selected, "yellow": self.show_selected,
            },
            -1,
        )

    def selected_entry(self):
        index = self["list"].getSelectedIndex()
        if 0 <= index < len(self.entries):
            return self.entries[index]
        return None

    def show_selected(self):
        entry = self.selected_entry()
        if not entry:
            return
        action = entry.get("action")
        item = entry.get("item") or {}
        text = "%s\n\n%s\n\nWYKRYTY PROBLEM\n%s\n%s\n\nDane techniczne:\n%s" % (
            action_title(action), action_description(action), item.get("title", ""), item.get("summary", ""), item.get("details", "")
        )
        self.session.open(E2DoctorTextScreen, "Podgląd działania", text, "E2 Doctor nie wykonał jeszcze żadnej zmiany")

    def execute_selected(self):
        entry = self.selected_entry()
        if entry:
            self.request_action(entry.get("action"), entry.get("item"), self.action_finished)

    def action_finished(self, changed=False):
        self.changed = self.changed or bool(changed)

    def finish(self):
        self.close(self.changed)


# Zachowujemy funkcjonalność ekranów 2.0, ale nadajemy im spójny wygląd 2.1.
_E2DoctorHistoryScreen20 = E2DoctorHistoryScreen
class E2DoctorHistoryScreen(_E2DoctorHistoryScreen20):
    skin = premium_results_skin("E2DoctorHistoryScreen")


_E2DoctorIPKBrowser20 = E2DoctorIPKBrowser
class E2DoctorIPKBrowser(_E2DoctorIPKBrowser20):
    skin = premium_results_skin("E2DoctorIPKBrowser")


_E2DoctorSettingsScreen20 = E2DoctorSettingsScreen
class E2DoctorSettingsScreen(_E2DoctorSettingsScreen20):
    skin = premium_results_skin("E2DoctorSettingsScreen")


_E2DoctorTools20 = E2DoctorTools
class E2DoctorTools(E2DoctorActionMixin, _E2DoctorTools20):
    skin = premium_results_skin("E2DoctorTools")

    def __init__(self, session):
        _E2DoctorTools20.__init__(self, session)
        additions = [
            ("Bezpiecznie oczyść pamięć flash", "safe_flash", "Tylko stare crashlogi, archiwa OPKG i zrzuty pamięci"),
            ("Bezpiecznie odśwież pamięć RAM", "safe_ram", "Zwalnia cache bez kończenia procesów"),
            ("Pokaż diagnostykę nośników", "storage_diag", "Bez formatowania i bez naprawy aktywnego systemu plików"),
        ]
        self.tool_entries = additions + self.tool_entries
        self["list"].setList([(STATUS_INFO, title, subtitle) for title, _, subtitle in self.tool_entries])
        self["status"].setText("Bezpieczne narzędzia ręczne | każda zmiana wymaga potwierdzenia")

    def execute(self):
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.tool_entries):
            return
        action = self.tool_entries[index][1]
        if action == "safe_flash":
            self.request_action("safe_flash_cleanup", {}, self._new_action_finished)
        elif action == "safe_ram":
            self.request_action("safe_ram_refresh", {}, self._new_action_finished)
        elif action == "storage_diag":
            self.request_action("storage_diagnostic", {}, self._new_action_finished)
        else:
            _E2DoctorTools20.execute(self)

    def _new_action_finished(self, changed=False):
        if changed:
            self.close(True)


DASHBOARD_MODULES = [
    ("repair", "FIX", "Centrum szybkiej naprawy", "Działania dopasowane do wykrytych problemów"),
    ("problems", "ALR", "Najważniejsze problemy", "Ostrzeżenia i błędy wymagające uwagi"),
    ("system", "SYS", "System i wydajność", "Python, flash, RAM, czas, temperatura i obciążenie"),
    ("crashlogs", "LOG", "Analizator crashlogów", "Wskazuje błąd, plik, linię i podejrzaną wtyczkę"),
    ("network", "NET", "Sieć i internet", "Adresacja, DNS oraz połączenie HTTPS"),
    ("channels", "CH", "Listy kanałów", "Indeksy bukietów, lamedb i martwe odwołania"),
    ("tuners", "DVB", "Głowice i sygnał", "Wykryte tunery, konfiguracja i bieżący LOCK"),
    ("storage", "HDD", "Nośniki i systemy plików", "Punkty montowania, miejsce i błędy zapisu"),
    ("packages", "PKG", "Pakiety OPKG", "Stan menedżera i niepełne instalacje"),
    ("oscam", "CAM", "OSCam", "Proces, pliki konfiguracji i bezpieczny restart"),
    ("media", "EPG", "EPG i picony", "Lokalizacja, rozmiar i podstawowa poprawność danych"),
    ("history", "HIS", "Historia stanu dekodera", "Porównanie skanów i wykrywanie nowych problemów"),
    ("py3", "PY3", "Zgodność wtyczek z Python 3", "Skan błędów składni i pozostałości Python 2"),
    ("ipk", "IPK", "E2 Safe Installer", "Analiza paczek IPK przed instalacją"),
    ("tools", "TOOL", "Bezpieczne narzędzia", "Naprawy, raport awaryjny, cofanie zmian i ustawienia"),
]


def module_results(results, key):
    if key == "problems":
        return [item for item in results if item.get("status") in (STATUS_WARN, STATUS_ERROR)]
    if key == "repair":
        return [item for item in results if item.get("status") in (STATUS_WARN, STATUS_ERROR)]
    return [item for item in results if item.get("module") == key]


def module_badge(results, key):
    if key == "repair":
        count = len(quick_repair_entries(results))
        if not results:
            return STATUS_INFO, "URUCHOM SKAN"
        if count:
            return STATUS_WARN, "%d DZIAŁAŃ" % count
        return STATUS_OK, "BRAK NAPRAW"
    selected = module_results(results, key)
    if key in ("history", "py3", "ipk", "tools"):
        return STATUS_INFO, "OTWÓRZ"
    if key == "problems" and not selected and results:
        return STATUS_OK, "BRAK PROBLEMÓW"
    if not selected:
        return STATUS_INFO, "BRAK DANYCH"
    worst = max((item.get("status", STATUS_INFO) for item in selected), key=lambda value: STATUS_RANK.get(value, 0))
    errors = len([item for item in selected if item.get("status") == STATUS_ERROR])
    warnings = len([item for item in selected if item.get("status") == STATUS_WARN])
    if errors:
        badge = "%d BŁĄD" % errors if errors == 1 else "%d BŁĘDY" % errors if 2 <= errors <= 4 else "%d BŁĘDÓW" % errors
    elif warnings:
        badge = "%d OSTRZEŻENIE" % warnings if warnings == 1 else "%d OSTRZEŻENIA" % warnings if 2 <= warnings <= 4 else "%d OSTRZEŻEŃ" % warnings
    else:
        badge = "DZIAŁA POPRAWNIE"
    return worst, badge


def module_subtitle(results, key, default):
    if key == "repair":
        count = len(quick_repair_entries(results))
        if count:
            return "Dostępne bezpieczne działania: %d — nic nie uruchomi się bez potwierdzenia" % count
        return "Brak bezpiecznych działań wymaganych przez aktualny skan"
    selected = module_results(results, key)
    problematic = [item for item in selected if item.get("status") in (STATUS_ERROR, STATUS_WARN)]
    if problematic:
        problematic.sort(key=lambda item: STATUS_RANK.get(item.get("status"), 0), reverse=True)
        return problematic[0].get("summary", default)
    return default


def dashboard_recommendation(results):
    if not results:
        return "GOTOWY: uruchom pełny skan, aby E2 Doctor przygotował zalecenia i bezpieczne działania."
    problems = [item for item in results if item.get("status") in (STATUS_ERROR, STATUS_WARN)]
    problems.sort(key=lambda item: STATUS_RANK.get(item.get("status"), 0), reverse=True)
    if problems:
        item = problems[0]
        count = len(quick_repair_entries(results))
        return "PRIORYTET: %s — %s | Centrum naprawy: %d działań" % (item.get("title", "Problem"), item.get("summary", ""), count)
    return "SYSTEM W DOBREJ KONDYCJI: nie wykryto błędów ani ostrzeżeń wymagających działania."


class E2DoctorDashboard(Screen):
    skin = dashboard_skin_21()

    def __init__(self, session):
        Screen.__init__(self, session)
        self.results = []
        self.settings = load_e2doctor_settings()
        self._scan_started = False
        for name in (
            "header_bg", "top_glow", "accent", "logo_panel", "logo_line", "score_bg", "score_top",
            "ok_bg", "ok_line", "info_bg", "info_line", "warn_bg", "warn_line", "error_bg", "error_line",
            "recommend_bg", "recommend_line", "footer_bg"
        ):
            self[name] = Label("")
        self["logo"] = Pixmap()
        self["brand_badge"] = Label("SMART DIAGNOSTICS  •  SAFE REPAIR  •  LIVE CARE")
        self["title"] = Label("E2 Doctor")
        self["subtitle"] = Label("Centrum diagnostyki i bezpiecznej naprawy Enigma2")
        self["change"] = Label("Gotowy do pełnej kontroli tunera")
        self["score_title"] = Label("KONDYCJA TUNERA")
        self["score_value"] = Label("--/100")
        self["score_grade"] = Label("BRAK SKANU")
        self["score_bar"] = ProgressBar()
        self["score_bar"].setValue(0)
        self["ok_count"] = Label("0")
        self["ok_label"] = Label("POPRAWNE")
        self["info_count"] = Label("0")
        self["info_label"] = Label("INFORMACJE")
        self["warn_count"] = Label("0")
        self["warn_label"] = Label("OSTRZEŻENIA")
        self["error_count"] = Label("0")
        self["error_label"] = Label("BŁĘDY")
        self["recommendation"] = Label(dashboard_recommendation([]))
        self["dashboard"] = E2DoctorDashboardList([])
        self["key_red"] = StaticText("Skanuj")
        self["key_green"] = StaticText("Otwórz / napraw")
        self["key_yellow"] = StaticText("Raport")
        self["key_blue"] = StaticText("Wyjście")
        self["footer"] = Label("E2 Doctor %s  •  by %s  •  %s  •  MENU: ustawienia" % (PLUGIN_VERSION, PLUGIN_AUTHOR, PLUGIN_EMAIL))
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "MenuActions", "InfoActions"],
            {
                "cancel": self.close, "blue": self.close,
                "red": self.scan, "green": self.open_selected, "ok": self.open_selected,
                "yellow": self.save_report, "menu": self.open_settings, "info": self.open_tools,
            },
            -1,
        )
        self.refresh_dashboard()
        self.onShown.append(self.first_show)

    def first_show(self):
        if self._scan_started:
            return
        self._scan_started = True
        self.settings = load_e2doctor_settings()
        if self.settings.get("auto_scan", True):
            self.scan()
        else:
            self["change"].setText("Automatyczny skan jest wyłączony. Naciśnij czerwony przycisk.")

    def scan(self):
        self["change"].setText("Trwa pełna diagnostyka systemu...")
        self["recommendation"].setText("ANALIZA: sprawdzanie systemu, sieci, list, głowic, nośników, OPKG i crashlogów...")
        try:
            previous_history = load_history()
            self.results = run_all_checks(self.session)
            current = compact_snapshot(self.results)
            previous = previous_history[0] if previous_history else None
            change_text = compare_snapshots(current, previous)
            save_history_snapshot(self.results)
            self.update_summary(change_text)
            self.refresh_dashboard()
        except Exception as error:
            self["change"].setText("Błąd diagnostyki: %s" % error)
            self["recommendation"].setText("Diagnostyka nie została ukończona. Otwórz raport błędu.")
            self.session.open(MessageBox, "Diagnostyka nie powiodła się:\n%s\n\n%s" % (error, traceback.format_exc()), MessageBox.TYPE_ERROR)

    def update_summary(self, change_text=None):
        counts = result_counts(self.results)
        score = calculate_health_score(self.results)
        self["score_value"].setText("%d/100" % score)
        self["score_grade"].setText(health_grade(score))
        self["score_bar"].setValue(score)
        self["ok_count"].setText(str(counts.get(STATUS_OK, 0)))
        self["info_count"].setText(str(counts.get(STATUS_INFO, 0)))
        self["warn_count"].setText(str(counts.get(STATUS_WARN, 0)))
        self["error_count"].setText(str(counts.get(STATUS_ERROR, 0)))
        self["change"].setText(change_text or current_change_summary(self.results))
        self["recommendation"].setText(dashboard_recommendation(self.results))

    def refresh_dashboard(self):
        rows = []
        for key, code, title, default_subtitle in DASHBOARD_MODULES:
            status, badge = module_badge(self.results, key)
            subtitle = module_subtitle(self.results, key, default_subtitle)
            rows.append((key, code, title, subtitle, status, badge))
        self["dashboard"].setList(rows)

    def selected_key(self):
        index = self["dashboard"].getSelectedIndex()
        if 0 <= index < len(DASHBOARD_MODULES):
            return DASHBOARD_MODULES[index][0]
        return None

    def open_selected(self):
        key = self.selected_key()
        if not key:
            return
        if key == "repair":
            if not self.results:
                self.scan()
            self.session.openWithCallback(self.repair_closed, E2DoctorQuickRepairScreen, self.results)
        elif key == "history":
            self.session.open(E2DoctorHistoryScreen)
        elif key == "py3":
            self["change"].setText("Trwa skanowanie zgodności wtyczek z Pythonem 3...")
            try:
                report = python3_compatibility_report()
                self.session.open(E2DoctorTextScreen, "Zgodność z Pythonem 3", report, "Analiza bez modyfikowania plików")
            except Exception as error:
                self.session.open(MessageBox, "Skan zgodności nie powiódł się:\n%s" % error, MessageBox.TYPE_ERROR)
            finally:
                self["change"].setText(current_change_summary(self.results) if self.results else "Gotowy")
        elif key == "ipk":
            self.session.open(E2DoctorIPKBrowser)
        elif key == "tools":
            self.open_tools()
        else:
            if not self.results:
                self.scan()
            selected = module_results(self.results, key)
            if not selected:
                self.session.open(MessageBox, "Brak wyników dla wybranego modułu.", MessageBox.TYPE_INFO, timeout=5)
                return
            title = next((item[2] for item in DASHBOARD_MODULES if item[0] == key), "Wyniki diagnostyki")
            self.session.openWithCallback(self.results_closed, E2DoctorResultsScreen, title, selected)

    def repair_closed(self, changed=False):
        if changed:
            self.scan()

    def results_closed(self, changed=False):
        if changed:
            self.scan()

    def save_report(self):
        if not self.results:
            self.scan()
        if not self.results:
            return
        try:
            path = make_report(self.results)
            self.session.open(MessageBox, "Raport zapisano w:\n%s" % path, MessageBox.TYPE_INFO, timeout=9)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się utworzyć raportu:\n%s" % error, MessageBox.TYPE_ERROR)

    def open_tools(self):
        self.session.openWithCallback(self.tools_closed, E2DoctorTools)

    def tools_closed(self, changed=False):
        if changed:
            self.scan()

    def open_settings(self):
        self.session.openWithCallback(self.settings_closed, E2DoctorSettingsScreen)

    def settings_closed(self, changed=False):
        if changed:
            self.settings = load_e2doctor_settings()


# -----------------------------------------------------------------------------
# E2 Doctor 2.1 - bezpieczna aktualizacja z GitHub
# Repozytorium: https://github.com/OliOli2013/E2-Doctor-Plugin
# -----------------------------------------------------------------------------

import ssl
import shlex

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlparse
except Exception:
    Request = None
    urlopen = None
    urlparse = None

try:
    from enigma import eConsoleAppContainer
except Exception:
    eConsoleAppContainer = None

UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/OliOli2013/E2-Doctor-Plugin/main/update.json"
UPDATE_ALLOWED_HOSTS = ("raw.githubusercontent.com", "github.com", "objects.githubusercontent.com")
UPDATE_TEMP_IPK = "/tmp/e2doctor-github-update.ipk"

try:
    PLUGIN_BUILD
except NameError:
    PLUGIN_BUILD = "20260711-4"


def _version_parts(value):
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts) if parts else (0,)


def _remote_is_newer(remote_version, remote_build):
    local_version = _version_parts(PLUGIN_VERSION)
    online_version = _version_parts(remote_version)
    if online_version != local_version:
        return online_version > local_version
    return _version_parts(remote_build) > _version_parts(PLUGIN_BUILD)


def _validate_update_url(value):
    if not value or urlparse is None:
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme == "https" and parsed.hostname in UPDATE_ALLOWED_HOSTS
    except Exception:
        return False


def fetch_update_manifest(timeout=10):
    if Request is None or urlopen is None:
        raise RuntimeError("Ten system nie udostępnia modułu urllib.request.")
    request = Request(
        UPDATE_MANIFEST_URL,
        headers={"User-Agent": "E2Doctor/%s Python3" % PLUGIN_VERSION, "Cache-Control": "no-cache"},
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        raw = response.read(131072)
    if not raw:
        raise RuntimeError("Serwer GitHub zwrócił pusty plik aktualizacji.")
    manifest = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Nieprawidłowy format pliku update.json.")
    required = ("version", "build", "download_url", "sha256")
    missing = [key for key in required if not str(manifest.get(key, "")).strip()]
    if missing:
        raise RuntimeError("W update.json brakuje pól: %s" % ", ".join(missing))
    if not _validate_update_url(manifest.get("download_url")):
        raise RuntimeError("Adres paczki aktualizacji nie prowadzi do dozwolonej domeny GitHub.")
    checksum = str(manifest.get("sha256", "")).strip().lower()
    if not re.match(r"^[0-9a-f]{64}$", checksum):
        raise RuntimeError("Nieprawidłowa suma SHA-256 w update.json.")
    minimum_python = int(manifest.get("min_python", 3) or 3)
    if sys.version_info[0] < minimum_python:
        raise RuntimeError("Aktualizacja wymaga Python %d lub nowszego." % minimum_python)
    return manifest


def update_screen_skin_21():
    if E2D_FHD:
        w, h = 1180, 690
        m, title, body, small = 42, 42, 27, 21
        header_h, footer_y = 145, 625
    else:
        w, h = 930, 570
        m, title, body, small = 30, 34, 22, 17
        header_h, footer_y = 120, 515
    content_y = header_h + 18
    content_h = footer_y - content_y - 18
    left_w = int(w * 0.36)
    right_x = m + left_w + 20
    right_w = w - right_x - m
    key_w = int((w - 2 * m) / 4)
    return '''
    <screen name="E2DoctorUpdateScreen" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor — aktualizacja z GitHub" backgroundColor="#0B1721" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,%(header_h)d" backgroundColor="#102737" />
        <widget name="accent" position="0,0" size="8,%(header_h)d" backgroundColor="#28D7E5" />
        <widget name="title" position="%(m)d,22" size="700,55" font="Regular;%(title)d" foregroundColor="#F5FAFF" transparent="1" />
        <widget name="subtitle" position="%(m)d,78" size="850,38" font="Regular;%(small)d" foregroundColor="#8FD7E2" transparent="1" />
        <widget name="source" position="%(m)d,113" size="900,28" font="Regular;%(small)d" foregroundColor="#8A9EAE" transparent="1" />

        <widget name="left_bg" position="%(m)d,%(content_y)d" size="%(left_w)d,%(content_h)d" backgroundColor="#11232E" />
        <widget name="local_title" position="%(left_text_x)d,%(local_y)d" size="%(left_text_w)d,30" font="Regular;%(small)d" foregroundColor="#8A9EAE" transparent="1" />
        <widget name="local_version" position="%(left_text_x)d,%(local_ver_y)d" size="%(left_text_w)d,48" font="Regular;%(title)d" foregroundColor="#58E387" transparent="1" />
        <widget name="remote_title" position="%(left_text_x)d,%(remote_y)d" size="%(left_text_w)d,30" font="Regular;%(small)d" foregroundColor="#8A9EAE" transparent="1" />
        <widget name="remote_version" position="%(left_text_x)d,%(remote_ver_y)d" size="%(left_text_w)d,48" font="Regular;%(title)d" foregroundColor="#5DB7F5" transparent="1" />
        <widget name="status_title" position="%(left_text_x)d,%(status_y)d" size="%(left_text_w)d,30" font="Regular;%(small)d" foregroundColor="#8A9EAE" transparent="1" />
        <widget name="status" position="%(left_text_x)d,%(status_text_y)d" size="%(left_text_w)d,110" font="Regular;%(body)d" foregroundColor="#F4D85B" transparent="1" />

        <widget name="right_bg" position="%(right_x)d,%(content_y)d" size="%(right_w)d,%(content_h)d" backgroundColor="#0E1D27" />
        <widget name="notes_title" position="%(notes_x)d,%(notes_y)d" size="%(notes_w)d,36" font="Regular;%(body)d" foregroundColor="#F5FAFF" transparent="1" />
        <widget name="notes" position="%(notes_x)d,%(notes_text_y)d" size="%(notes_w)d,%(notes_h)d" font="Regular;%(small)d" foregroundColor="#C2CFD8" transparent="1" />

        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#0D1C26" />
        <widget source="key_red" render="Label" position="%(m)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body)d" halign="center" foregroundColor="#FF6970" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body)d" halign="center" foregroundColor="#5BEA87" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body)d" halign="center" foregroundColor="#F4D85B" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,42" font="Regular;%(body)d" halign="center" foregroundColor="#60B7F5" />
    </screen>
    ''' % {
        "w": w, "h": h, "m": m, "title": title, "body": body, "small": small,
        "header_h": header_h, "content_y": content_y, "content_h": content_h,
        "left_w": left_w, "right_x": right_x, "right_w": right_w,
        "left_text_x": m + 22, "left_text_w": left_w - 44,
        "local_y": content_y + 24, "local_ver_y": content_y + 56,
        "remote_y": content_y + 130, "remote_ver_y": content_y + 162,
        "status_y": content_y + 238, "status_text_y": content_y + 272,
        "notes_x": right_x + 24, "notes_y": content_y + 20, "notes_w": right_w - 48,
        "notes_text_y": content_y + 62, "notes_h": content_h - 82,
        "footer_bg_y": footer_y - 12, "footer_bg_h": h - footer_y + 12,
        "footer_y": footer_y, "key_w": key_w, "green_x": m + key_w,
        "yellow_x": m + 2 * key_w, "blue_x": m + 3 * key_w,
    }


class E2DoctorUpdateScreen(Screen):
    skin = update_screen_skin_21()

    def __init__(self, session):
        Screen.__init__(self, session)
        self.manifest = None
        self.update_available = False
        self.busy = False
        self.checked_once = False
        self.console = None
        self.console_output = []
        for name in ("header_bg", "accent", "left_bg", "right_bg", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label("Aktualizacja E2 Doctor z GitHub")
        self["subtitle"] = Label("Bezpieczne sprawdzanie wersji, weryfikacja SHA-256 i instalacja IPK")
        self["source"] = Label("Źródło: github.com/OliOli2013/E2-Doctor-Plugin")
        self["local_title"] = Label("ZAINSTALOWANA WERSJA")
        self["local_version"] = Label("%s  •  build %s" % (PLUGIN_VERSION, PLUGIN_BUILD))
        self["remote_title"] = Label("WERSJA NA GITHUB")
        self["remote_version"] = Label("sprawdzanie...")
        self["status_title"] = Label("STATUS AKTUALIZACJI")
        self["status"] = Label("Łączenie z GitHub...")
        self["notes_title"] = Label("Informacje o wydaniu")
        self["notes"] = ScrollLabel("Trwa pobieranie pliku update.json...")
        self["key_red"] = StaticText("Wróć")
        self["key_green"] = StaticText("Sprawdź")
        self["key_yellow"] = StaticText("Sprawdź ponownie")
        self["key_blue"] = StaticText("Wyjście")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "cancel": self.safe_close, "red": self.safe_close, "blue": self.safe_close,
                "green": self.green_action, "ok": self.green_action,
                "yellow": self.check_update,
                "up": self["notes"].pageUp, "down": self["notes"].pageDown,
                "left": self["notes"].pageUp, "right": self["notes"].pageDown,
            },
            -1,
        )
        self.onShown.append(self.first_show)

    def first_show(self):
        if self.checked_once:
            return
        self.checked_once = True
        self.check_update()

    def safe_close(self):
        if self.busy:
            self.session.open(MessageBox, "Trwa pobieranie lub instalacja. Poczekaj na zakończenie operacji.", MessageBox.TYPE_INFO, timeout=6)
            return
        self.close()

    def _set_status(self, text, notes=None):
        self["status"].setText(text)
        if notes is not None:
            self["notes"].setText(notes)

    def check_update(self):
        if self.busy:
            return
        self.manifest = None
        self.update_available = False
        self["key_green"].setText("Sprawdź")
        self["remote_version"].setText("sprawdzanie...")
        self._set_status("Łączenie z GitHub...", "Pobieranie i sprawdzanie pliku update.json.")
        try:
            manifest = fetch_update_manifest()
            self.manifest = manifest
            version = str(manifest.get("version"))
            build = str(manifest.get("build"))
            self["remote_version"].setText("%s  •  build %s" % (version, build))
            notes = manifest.get("notes") or []
            if isinstance(notes, str):
                notes = [notes]
            note_lines = ["E2 Doctor %s" % version]
            release_date = str(manifest.get("release_date", "")).strip()
            if release_date:
                note_lines.append("Data wydania: %s" % release_date)
            note_lines.append("")
            for entry in notes:
                note_lines.append("• %s" % str(entry))
            note_lines.extend([
                "", "Bezpieczeństwo aktualizacji:",
                "• paczka jest pobierana wyłącznie przez HTTPS z GitHub,",
                "• przed instalacją sprawdzana jest suma SHA-256,",
                "• instalacja wymaga potwierdzenia użytkownika,",
                "• po instalacji proponowany jest restart GUI.",
            ])
            self["notes"].setText("\n".join(note_lines))
            self.update_available = _remote_is_newer(version, build)
            if self.update_available:
                self._set_status("DOSTĘPNA NOWA WERSJA")
                self["key_green"].setText("Pobierz i zainstaluj")
            else:
                self._set_status("MASZ NAJNOWSZĄ WERSJĘ")
                self["key_green"].setText("Sprawdź ponownie")
        except Exception as error:
            self["remote_version"].setText("brak danych")
            self._set_status("BŁĄD POŁĄCZENIA", "Nie udało się sprawdzić aktualizacji.\n\n%s\n\nSprawdź internet, DNS, prawidłową datę systemową oraz dostęp do GitHub." % error)
            self["key_green"].setText("Spróbuj ponownie")

    def green_action(self):
        if self.busy:
            return
        if not self.manifest or not self.update_available:
            self.check_update()
            return
        version = self.manifest.get("version")
        build = self.manifest.get("build")
        text = (
            "Pobrać i zainstalować E2 Doctor %s (build %s) z GitHub?\n\n"
            "Paczka zostanie zweryfikowana sumą SHA-256 przed instalacją. "
            "Ustawienia i historia E2 Doctor pozostaną zachowane."
        ) % (version, build)
        self.session.openWithCallback(self._download_confirmed, MessageBox, text, MessageBox.TYPE_YESNO)

    def _download_confirmed(self, answer):
        if not answer:
            return
        self.start_download()

    def _new_console(self, closed_callback):
        if eConsoleAppContainer is None:
            raise RuntimeError("Ten obraz Enigma2 nie udostępnia eConsoleAppContainer.")
        self.console_output = []
        self.console = eConsoleAppContainer()
        self.console.dataAvail.append(self._console_data)
        self.console.appClosed.append(closed_callback)
        return self.console

    def _console_data(self, data):
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            self.console_output.append(str(data))
            if len(self.console_output) > 200:
                self.console_output = self.console_output[-200:]
        except Exception:
            pass

    def start_download(self):
        try:
            if os.path.exists(UPDATE_TEMP_IPK):
                os.unlink(UPDATE_TEMP_IPK)
        except Exception:
            pass
        self.busy = True
        self["key_green"].setText("Pobieranie...")
        self._set_status("POBIERANIE PACZKI", "Trwa pobieranie aktualizacji z GitHub. Nie wyłączaj dekodera.")
        try:
            console = self._new_console(self._download_finished)
            command = "wget -q -O %s %s" % (shlex.quote(UPDATE_TEMP_IPK), shlex.quote(str(self.manifest.get("download_url"))))
            if console.execute(command):
                raise RuntimeError("Nie udało się uruchomić polecenia wget.")
        except Exception as error:
            self.busy = False
            self._set_status("BŁĄD POBIERANIA", str(error))
            self["key_green"].setText("Spróbuj ponownie")

    def _download_finished(self, return_code):
        self.busy = False
        if int(return_code) != 0 or not os.path.isfile(UPDATE_TEMP_IPK):
            output = "".join(self.console_output).strip()
            self._set_status("BŁĄD POBIERANIA", "Nie udało się pobrać paczki.\nKod: %s\n%s" % (return_code, output[-1500:]))
            self["key_green"].setText("Spróbuj ponownie")
            return
        try:
            with open(UPDATE_TEMP_IPK, "rb") as handle:
                header = handle.read(8)
                handle.seek(0)
                digest = hashlib.sha256()
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            if header != b"!<arch>\n":
                raise RuntimeError("Pobrany plik nie jest prawidłową paczką IPK.")
            expected = str(self.manifest.get("sha256", "")).lower()
            actual = digest.hexdigest().lower()
            if actual != expected:
                raise RuntimeError("Suma SHA-256 jest niezgodna.\nOczekiwana: %s\nPobrana: %s" % (expected, actual))
        except Exception as error:
            try:
                os.unlink(UPDATE_TEMP_IPK)
            except Exception:
                pass
            self._set_status("AKTUALIZACJA ODRZUCONA", str(error))
            self["key_green"].setText("Sprawdź ponownie")
            return
        self._set_status("PACZKA ZWERYFIKOWANA", "Paczka została pobrana i poprawnie zweryfikowana sumą SHA-256.")
        self.session.openWithCallback(
            self._install_confirmed,
            MessageBox,
            "Paczka jest poprawna. Zainstalować aktualizację teraz?\n\nPo instalacji należy uruchomić ponownie GUI Enigma2.",
            MessageBox.TYPE_YESNO,
        )

    def _install_confirmed(self, answer):
        if not answer:
            self["key_green"].setText("Pobierz i zainstaluj")
            return
        self.start_install()

    def start_install(self):
        self.busy = True
        self["key_green"].setText("Instalowanie...")
        self._set_status("INSTALOWANIE AKTUALIZACJI", "OPKG instaluje zweryfikowaną paczkę. Nie wyłączaj dekodera.")
        try:
            console = self._new_console(self._install_finished)
            command = "opkg install --force-reinstall %s" % shlex.quote(UPDATE_TEMP_IPK)
            if console.execute(command):
                raise RuntimeError("Nie udało się uruchomić OPKG.")
        except Exception as error:
            self.busy = False
            self._set_status("BŁĄD INSTALACJI", str(error))
            self["key_green"].setText("Spróbuj ponownie")

    def _install_finished(self, return_code):
        self.busy = False
        output = "".join(self.console_output).strip()
        try:
            os.unlink(UPDATE_TEMP_IPK)
        except Exception:
            pass
        if int(return_code) != 0:
            self._set_status("BŁĄD INSTALACJI", "OPKG zakończył pracę kodem %s.\n\n%s" % (return_code, output[-2500:]))
            self["key_green"].setText("Sprawdź ponownie")
            return
        self._set_status("AKTUALIZACJA ZAINSTALOWANA", "Nowa wersja E2 Doctor została zainstalowana poprawnie. Wykonaj restart GUI, aby wczytać nowe pliki.")
        self["key_green"].setText("Gotowe")
        self.session.openWithCallback(
            self._restart_gui_answer,
            MessageBox,
            "Aktualizacja została zainstalowana poprawnie.\n\nUruchomić teraz ponownie GUI Enigma2?",
            MessageBox.TYPE_YESNO,
        )

    def _restart_gui_answer(self, answer):
        if not answer:
            return
        try:
            from Screens.Standby import TryQuitMainloop
            self.session.open(TryQuitMainloop, 3)
        except Exception as error:
            self.session.open(MessageBox, "Nie udało się uruchomić restartu GUI:\n%s" % error, MessageBox.TYPE_ERROR)


# Wstawienie aktualizacji jako widocznego modułu panelu oraz skrótu klawiszem 0.
if not any(entry[0] == "update" for entry in DASHBOARD_MODULES):
    insert_at = max(0, len(DASHBOARD_MODULES) - 1)
    DASHBOARD_MODULES.insert(insert_at, ("update", "UPD", "Aktualizacja z GitHub", "Sprawdź, pobierz i bezpiecznie zainstaluj najnowszą wersję"))

_E2D_MODULE_BADGE_BEFORE_UPDATE = module_badge


def module_badge(results, key):
    if key == "update":
        return STATUS_INFO, "SPRAWDŹ"
    return _E2D_MODULE_BADGE_BEFORE_UPDATE(results, key)


_E2D_DASHBOARD_INIT_BEFORE_UPDATE = E2DoctorDashboard.__init__
_E2D_DASHBOARD_OPEN_BEFORE_UPDATE = E2DoctorDashboard.open_selected


def _e2d_dashboard_init_with_update(self, session):
    _E2D_DASHBOARD_INIT_BEFORE_UPDATE(self, session)
    self["update_actions"] = ActionMap(["NumberActions"], {"0": self.open_update}, -1)
    try:
        self["footer"].setText("E2 Doctor %s  •  by %s  •  %s  •  0: aktualizacja  •  MENU: ustawienia" % (PLUGIN_VERSION, PLUGIN_AUTHOR, PLUGIN_EMAIL))
    except Exception:
        pass


def _e2d_dashboard_open_update(self):
    self.session.open(E2DoctorUpdateScreen)


def _e2d_dashboard_open_selected_with_update(self):
    if self.selected_key() == "update":
        self.open_update()
        return
    return _E2D_DASHBOARD_OPEN_BEFORE_UPDATE(self)


E2DoctorDashboard.__init__ = _e2d_dashboard_init_with_update
E2DoctorDashboard.open_update = _e2d_dashboard_open_update
E2DoctorDashboard.open_selected = _e2d_dashboard_open_selected_with_update

# -----------------------------------------------------------------------------
# E2 Doctor 2.3 - dashboard premium cards
# -----------------------------------------------------------------------------
try:
    from Components.MultiContent import MultiContentEntryPixmapAlphaBlend
except Exception:
    MultiContentEntryPixmapAlphaBlend = None
try:
    from Tools.LoadPixmap import LoadPixmap
except Exception:
    LoadPixmap = None

MODULE_HINTS_22 = {
    "repair": "Działania bezpieczne dopasowane do wykrytych problemów",
    "problems": "Najważniejsze alerty wymagające uwagi użytkownika",
    "system": "Flash, RAM, CPU, temperatura i stan pracy tunera",
    "crashlogs": "Analiza crashlogów, wskazanie błędu i źródła problemu",
    "network": "Adresacja, DNS, brama i połączenie HTTPS",
    "channels": "Bukiety, lamedb, indeksy i brakujące odwołania",
    "tuners": "Wykryte głowice, konfiguracja i bieżący LOCK",
    "storage": "Nośniki, miejsce, montowanie i bezpieczeństwo zapisu",
    "packages": "Kontrola OPKG, zależności i niepełne instalacje",
    "oscam": "Stan procesu, konfiguracja i szybki restart OSCam",
    "media": "EPG, picony i podstawowa poprawność danych",
    "history": "Porównanie skanów i wykrywanie zmian w systemie",
    "py3": "Skan zgodności wtyczek z Pythonem 3",
    "ipk": "Analiza paczek IPK przed instalacją",
    "tools": "Narzędzia ręczne, raport i cofanie zmian",
    "update": "Sprawdź nową wersję i wykonaj aktualizację z GitHub",
}

MODULE_ICON_FILES_22 = {key: os.path.join(PLUGIN_PATH, 'icons', '%s.png' % key) for key in MODULE_HINTS_22.keys()}
MODULE_ICONS_22 = {}
if LoadPixmap is not None:
    for _key, _path in MODULE_ICON_FILES_22.items():
        try:
            if os.path.exists(_path):
                MODULE_ICONS_22[_key] = LoadPixmap(cached=True, path=_path)
        except Exception:
            MODULE_ICONS_22[_key] = None


def _badge_label_22(results, key):
    if key == 'update':
        return STATUS_INFO, 'AKTUALIZUJ'
    if key == 'repair':
        count = len(quick_repair_entries(results))
        if not results:
            return STATUS_INFO, 'SKAN'
        if count:
            return STATUS_WARN, '%d AKCJI' % count
        return STATUS_OK, 'GOTOWE'
    selected = module_results(results, key)
    if key in ('history', 'py3', 'ipk', 'tools'):
        return STATUS_INFO, 'OTWÓRZ'
    if key == 'problems' and not selected and results:
        return STATUS_OK, 'BRAK'
    if not selected:
        return STATUS_INFO, 'BRAK'
    worst = max((item.get('status', STATUS_INFO) for item in selected), key=lambda value: STATUS_RANK.get(value, 0))
    errors = len([item for item in selected if item.get('status') == STATUS_ERROR])
    warnings = len([item for item in selected if item.get('status') == STATUS_WARN])
    if errors:
        return STATUS_ERROR, ('%d BŁĄD' % errors) if errors == 1 else ('%d BŁĘDY' % errors if errors <= 4 else '%d BŁĘDÓW' % errors)
    if warnings:
        return STATUS_WARN, ('%d OSTRZ.' % warnings)
    return STATUS_OK, 'OK'


module_badge = _badge_label_22


def dashboard_skin_22():
    w, h, m = E2D_UI_W, E2D_UI_H, E2D_MARGIN
    header_h = 220 if E2D_FHD else 176
    summary_y = header_h + 12
    summary_h = 92 if E2D_FHD else 70
    banner_y = summary_y + summary_h + 10
    banner_h = 54 if E2D_FHD else 44
    list_y = banner_y + banner_h + 12
    footer_h = 74 if E2D_FHD else 56
    footer_y = h - footer_h - 18
    list_h = footer_y - list_y - 8
    logo_panel = 168 if E2D_FHD else 132
    logo = E2D_LOGO_SIZE
    logo_x = m + int((logo_panel - logo) / 2)
    logo_y = int((header_h - logo) / 2)
    score_w = 320 if E2D_FHD else 242
    score_x = w - m - score_w
    title_x = m + logo_panel + 26
    title_w = score_x - title_x - 22
    gap = 12
    card_w = int((w - 2 * m - 3 * gap) / 4)
    key_w = int((w - 2 * m) / 4)
    return """
    <screen name="E2DoctorDashboard" position="center,center" size="%(w)d,%(h)d" title="E2 Doctor" backgroundColor="#08131A" flags="wfNoBorder">
        <widget name="header_bg" position="0,0" size="%(w)d,%(header_h)d" backgroundColor="#112734" transparent="0" />
        <widget name="top_glow" position="0,0" size="%(w)d,6" backgroundColor="#29D4DE" transparent="0" />
        <widget name="accent" position="0,0" size="12,%(header_h)d" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="logo_panel" position="%(m)d,%(logo_panel_y)d" size="%(logo_panel)d,%(logo_panel)d" backgroundColor="#0B1D27" transparent="0" />
        <widget name="logo_line" position="%(m)d,%(logo_line_y)d" size="%(logo_panel)d,4" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="logo" position="%(logo_x)d,%(logo_y)d" size="%(logo)d,%(logo)d" pixmap="%(logo_path)s" alphatest="blend" />
        <widget name="brand_badge" position="%(title_x)d,%(badge_y)d" size="%(title_w)d,30" font="Regular;%(tiny)d" foregroundColor="#5EE6EE" />
        <widget name="title" position="%(title_x)d,%(title_y)d" size="%(title_w)d,58" font="Regular;%(main_title)d" foregroundColor="#FFFFFF" />
        <widget name="subtitle" position="%(title_x)d,%(subtitle_y)d" size="%(title_w)d,38" font="Regular;%(body)d" foregroundColor="#B4C9D4" />
        <widget name="change" position="%(title_x)d,%(change_y)d" size="%(title_w)d,34" font="Regular;%(small)d" foregroundColor="#78DCE4" />
        <widget name="score_bg" position="%(score_x)d,%(score_y)d" size="%(score_w)d,%(score_h)d" backgroundColor="#081820" transparent="0" />
        <widget name="score_top" position="%(score_x)d,%(score_y)d" size="%(score_w)d,5" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="score_title" position="%(score_x2)d,%(score_title_y)d" size="%(score_w2)d,32" font="Regular;%(small)d" halign="center" foregroundColor="#A4BBC8" />
        <widget name="score_value" position="%(score_x2)d,%(score_value_y)d" size="%(score_w2)d,60" font="Regular;%(score_font)d" halign="center" foregroundColor="#FFFFFF" />
        <widget name="score_grade" position="%(score_x2)d,%(score_grade_y)d" size="%(score_w2)d,32" font="Regular;%(small)d" halign="center" foregroundColor="#62E28B" />
        <widget name="score_bar" position="%(score_bar_x)d,%(score_bar_y)d" size="%(score_bar_w)d,12" borderWidth="1" />
        <widget name="ok_bg" position="%(m)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#123827" transparent="0" />
        <widget name="ok_line" position="%(m)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#51E181" transparent="0" />
        <widget name="ok_count" position="%(m)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#5FE68A" />
        <widget name="ok_label" position="%(m)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#BEDDCA" />
        <widget name="info_bg" position="%(card2_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#123249" transparent="0" />
        <widget name="info_line" position="%(card2_x)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#52BEF0" transparent="0" />
        <widget name="info_count" position="%(card2_x)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#61C8F4" />
        <widget name="info_label" position="%(card2_x)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#BBD3DF" />
        <widget name="warn_bg" position="%(card3_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#423815" transparent="0" />
        <widget name="warn_line" position="%(card3_x)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#F2D14D" transparent="0" />
        <widget name="warn_count" position="%(card3_x)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#F5D85A" />
        <widget name="warn_label" position="%(card3_x)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#E4DAB2" />
        <widget name="error_bg" position="%(card4_x)d,%(summary_y)d" size="%(card_w)d,%(summary_h)d" backgroundColor="#482027" transparent="0" />
        <widget name="error_line" position="%(card4_x)d,%(summary_y)d" size="%(card_w)d,5" backgroundColor="#FF626B" transparent="0" />
        <widget name="error_count" position="%(card4_x)d,%(count_y)d" size="%(card_w)d,38" font="Regular;%(count_font)d" halign="center" foregroundColor="#FF737A" />
        <widget name="error_label" position="%(card4_x)d,%(label_y)d" size="%(card_w)d,27" font="Regular;%(small)d" halign="center" foregroundColor="#E9C0C4" />
        <widget name="recommend_bg" position="%(m)d,%(banner_y)d" size="%(content_w)d,%(banner_h)d" backgroundColor="#173443" transparent="0" />
        <widget name="recommend_line" position="%(m)d,%(banner_y)d" size="8,%(banner_h)d" backgroundColor="#2AD0D9" transparent="0" />
        <widget name="recommendation" position="%(recommend_x)d,%(recommend_text_y)d" size="%(recommend_w)d,30" font="Regular;%(small)d" foregroundColor="#E5F6F8" />
        <widget name="dashboard" position="%(m)d,%(list_y)d" size="%(content_w)d,%(list_h)d" scrollbarMode="showOnDemand" />
        <widget name="footer_bg" position="0,%(footer_bg_y)d" size="%(w)d,%(footer_bg_h)d" backgroundColor="#0F222C" transparent="0" />
        <widget source="key_red" render="Label" position="%(m)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#FF6970" />
        <widget source="key_green" render="Label" position="%(green_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#5BEA87" />
        <widget source="key_yellow" render="Label" position="%(yellow_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#F4D85B" />
        <widget source="key_blue" render="Label" position="%(blue_x)d,%(footer_y)d" size="%(key_w)d,%(key_h)d" font="Regular;%(body)d" halign="center" foregroundColor="#60B7F5" />
        <widget name="footer" position="%(m)d,%(version_y)d" size="%(content_w)d,24" font="Regular;%(tiny)d" halign="center" foregroundColor="#7C95A3" />
    </screen>
    """ % {
        "w": w, "h": h, "m": m, "header_h": header_h, "content_w": w - 2 * m,
        "logo_panel": logo_panel, "logo_panel_y": int((header_h - logo_panel) / 2),
        "logo_line_y": int((header_h - logo_panel) / 2), "logo_x": logo_x, "logo_y": logo_y,
        "logo": logo, "logo_path": E2D_LOGO_PATH, "title_x": title_x, "title_w": title_w,
        "badge_y": 24 if E2D_FHD else 17, "tiny": E2D_FONT_TINY,
        "title_y": 53 if E2D_FHD else 39, "main_title": 52 if E2D_FHD else 41,
        "subtitle_y": 112 if E2D_FHD else 84, "body": E2D_FONT_BODY,
        "change_y": 158 if E2D_FHD else 122, "small": E2D_FONT_SMALL,
        "score_x": score_x, "score_y": 24 if E2D_FHD else 18, "score_w": score_w,
        "score_h": 176 if E2D_FHD else 140, "score_x2": score_x + 10, "score_w2": score_w - 20,
        "score_title_y": 38 if E2D_FHD else 28, "score_value_y": 72 if E2D_FHD else 54,
        "score_font": 54 if E2D_FHD else 40, "score_grade_y": 132 if E2D_FHD else 103,
        "score_bar_x": score_x + 24, "score_bar_y": 178 if E2D_FHD else 139, "score_bar_w": score_w - 48,
        "summary_y": summary_y, "summary_h": summary_h, "card_w": card_w,
        "card2_x": m + card_w + gap, "card3_x": m + 2 * (card_w + gap), "card4_x": m + 3 * (card_w + gap),
        "count_y": summary_y + (12 if E2D_FHD else 7), "label_y": summary_y + (54 if E2D_FHD else 40),
        "count_font": 36 if E2D_FHD else 28, "banner_y": banner_y, "banner_h": banner_h,
        "recommend_x": m + 22, "recommend_text_y": banner_y + (12 if E2D_FHD else 8), "recommend_w": w - 2 * m - 34,
        "list_y": list_y, "list_h": list_h, "footer_bg_y": footer_y - 10, "footer_bg_h": h - footer_y + 10,
        "footer_y": footer_y, "key_h": 42 if E2D_FHD else 34, "key_w": key_w,
        "green_x": m + key_w, "yellow_x": m + 2 * key_w, "blue_x": m + 3 * key_w,
        "version_y": h - 26,
    }


class E2DoctorDashboardList(MenuList):
    def __init__(self, entries=None):
        MenuList.__init__(self, entries or [], enableWrapAround=True, content=eListboxPythonMultiContent)
        self.l.setFont(0, gFont('Regular', 18 if E2D_FHD else 14))
        self.l.setFont(1, gFont('Regular', E2D_FONT_TITLE))
        self.l.setFont(2, gFont('Regular', E2D_FONT_SMALL))
        self.l.setFont(3, gFont('Regular', E2D_FONT_TINY))
        self.l.setFont(4, gFont('Regular', 20 if E2D_FHD else 15))
        self.l.setItemHeight(92 if E2D_FHD else 72)
        self.l.setBuildFunc(self.build_entry)

    def build_entry(self, key, code, title, subtitle, status, badge):
        status_color = STATUS_COLORS.get(status, 0x008A9AA5)
        item_h = 92 if E2D_FHD else 72
        content_w = E2D_LIST_W
        icon_size = 54 if E2D_FHD else 42
        icon_box = 84 if E2D_FHD else 66
        badge_w = 180 if E2D_FHD else 142
        title_x = icon_box + 24
        text_w = content_w - title_x - badge_w - 26
        helper = MODULE_HINTS_22.get(key, '')
        icon = MODULE_ICONS_22.get(key)
        entries = [
            None,
            MultiContentEntryText(pos=(0, 4), size=(content_w, item_h - 8), font=2, text='', backcolor=0x00122029, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(0, 4), size=(6, item_h - 8), font=2, text='', backcolor=status_color, backcolor_sel=status_color),
            MultiContentEntryText(pos=(18, 14 if E2D_FHD else 11), size=(icon_box, item_h - (28 if E2D_FHD else 22)), font=4, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text='', backcolor=0x00193342, backcolor_sel=0x0028495A),
            MultiContentEntryText(pos=(title_x, 10 if E2D_FHD else 8), size=(text_w, 22), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=code + '  •  MODUŁ', color=0x0078DCE4, color_sel=0x0096ECF2, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(title_x, 28 if E2D_FHD else 21), size=(text_w, 34), font=1, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=title, color=0x00FFFFFF, color_sel=0x00FFFFFF, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(title_x, 58 if E2D_FHD else 46), size=(text_w, 22), font=3, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=helper, color=0x0089A4B0, color_sel=0x00B9D3DE, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(content_w - badge_w - 18, 18 if E2D_FHD else 12), size=(badge_w, item_h - (36 if E2D_FHD else 24)), font=4, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text='', backcolor=0x00142B35, backcolor_sel=0x00193442),
            MultiContentEntryText(pos=(content_w - badge_w - 18, 26 if E2D_FHD else 18), size=(badge_w, 24), font=2, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=badge, color=status_color, color_sel=status_color, backcolor_sel=0x00193442),
            MultiContentEntryText(pos=(content_w - badge_w - 18, 50 if E2D_FHD else 39), size=(badge_w, 18), font=3, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=subtitle, color=0x00C0CCD4, color_sel=0x00FFFFFF, backcolor_sel=0x00193442),
        ]
        if icon is not None and MultiContentEntryPixmapAlphaBlend is not None:
            entries.append(MultiContentEntryPixmapAlphaBlend(pos=(18 + int((icon_box - icon_size) / 2), 14 if E2D_FHD else 11), size=(icon_size, icon_size), png=icon))
        else:
            entries.append(MultiContentEntryText(pos=(18, 14 if E2D_FHD else 11), size=(icon_box, item_h - (28 if E2D_FHD else 22)), font=4, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=code, color=0x00FFFFFF, color_sel=0x00FFFFFF, backcolor_sel=0x0028495A))
        return entries


# aktywacja stylu 2.2 bez naruszania logiki ekranu
E2DoctorDashboard.skin = dashboard_skin_22()

# -----------------------------------------------------------------------------
# E2 Doctor 2.3 - język systemu (PL/EN) i poprawione skalowanie ikon
# -----------------------------------------------------------------------------
DEFAULT_SETTINGS["language"] = "auto"

try:
    from Components.Language import language as _e2_system_language
except Exception:
    _e2_system_language = None

try:
    from Components.config import config as _e2_config
except Exception:
    _e2_config = None


def _system_language_code():
    value = ""
    try:
        if _e2_system_language is not None:
            value = str(_e2_system_language.getLanguage() or "")
    except Exception:
        value = ""
    if not value:
        try:
            value = str(_e2_config.osd.language.value or "")
        except Exception:
            value = ""
    if not value:
        value = os.environ.get("LANG", "")
    return "pl" if value.lower().startswith("pl") else "en"


def current_language_code(settings=None):
    if settings is None:
        try:
            settings = load_e2doctor_settings()
        except Exception:
            settings = {}
    selected = str((settings or {}).get("language", "auto") or "auto").lower()
    if selected in ("pl", "en"):
        return selected
    return _system_language_code()


def is_english():
    return current_language_code() == "en"


def L(pl_text, en_text):
    return en_text if is_english() else pl_text


_TITLE_EN = {
    "System / Python": "System / Python",
    "Pamięć flash": "Flash memory",
    "Pamięć RAM": "RAM memory",
    "Data i czas systemowy": "System date and time",
    "Temperatura": "Temperature",
    "Obciążenie systemu": "System load",
    "DNS": "DNS",
    "Połączenie z internetem": "Internet connection",
    "Menedżer pakietów OPKG": "OPKG package manager",
    "Spójność pakietów OPKG": "OPKG package integrity",
    "Listy kanałów": "Channel lists",
    "Konfiguracja głowic": "Tuner configuration",
    "Wykryte głowice": "Detected tuners",
    "Aktywna głowica i sygnał": "Active tuner and signal",
    "Nośniki i punkty montowania": "Storage devices and mount points",
    "Stan systemów plików": "Filesystem status",
    "Pamięć EPG": "EPG storage",
    "Picony": "Picons",
    "OSCam": "OSCam",
    "Crashlogi Enigma2": "Enigma2 crashlogs",
}

_EXACT_EN = {
    "nieznana": "unknown",
    "nieznany": "unknown",
    "nie ustalono": "not determined",
    "brak danych": "no data",
    "brak daty": "no date",
    "brak opisu": "no description",
    "Moduł diagnostyczny zakończył się błędem": "The diagnostic module ended with an error",
    "Domena github.com została poprawnie rozwiązana": "github.com was resolved correctly",
    "Połączenie HTTPS działa poprawnie": "HTTPS connection works correctly",
    "DNS działa, ale połączenie HTTPS nie powiodło się": "DNS works, but the HTTPS connection failed",
    "Nie można rozwiązać domeny github.com": "github.com could not be resolved",
    "Nie znaleziono programu OPKG": "The OPKG executable was not found",
    "Nie znaleziono bazy zainstalowanych pakietów": "The installed-package database was not found",
    "Możliwa nieaktywna blokada OPKG": "A possibly inactive OPKG lock was found",
    "OPKG jest dostępny": "OPKG is available",
    "Brakuje głównych plików listy kanałów lub są one puste": "Main channel-list files are missing or empty",
    "Nie znaleziono wpisów konfiguracji głowic": "No tuner configuration entries were found",
    "Ustawienia głowic istnieją, ale brakuje plików XML skanowania": "Tuner settings exist, but scanning XML files are missing",
    "Plik EPG nie został jeszcze utworzony": "The EPG file has not been created yet",
    "Plik EPG jest pusty lub nietypowo mały": "The EPG file is empty or unusually small",
    "Katalog piconów istnieje, ale jest pusty": "The picon directory exists, but it is empty",
    "Nie wykryto piconów": "No picons were detected",
    "Proces OSCam jest uruchomiony": "The OSCam process is running",
    "Konfiguracja istnieje, ale OSCam nie jest uruchomiony": "Configuration exists, but OSCam is not running",
    "OSCam nie jest zainstalowany lub skonfigurowany": "OSCam is not installed or configured",
    "Nie znaleziono crashlogów": "No crashlogs were found",
    "Sprawdzono standardowe katalogi logów.": "Standard log directories were checked.",
    "Czujnik temperatury jest niedostępny": "The temperature sensor is unavailable",
    "Nie znaleziono czytelnego czujnika temperatury.": "No readable temperature sensor was found.",
    "System nie udostępnił listy głowic": "The system did not provide a tuner list",
    "Plik /proc/bus/nim_sockets jest pusty lub niedostępny.": "The /proc/bus/nim_sockets file is empty or unavailable.",
    "Brak sesji Enigma2 do odczytu sygnału": "No Enigma2 session is available for signal reading",
    "Uruchom diagnostykę z panelu E2 Doctor podczas oglądania kanału.": "Run diagnostics from E2 Doctor while watching a channel.",
    "Nie wykryto bieżących błędów nośników": "No current storage errors were detected",
    "Nie można przeanalizować bazy pakietów": "The package database could not be analysed",
    "Brak czytelnych wpisów w /var/lib/opkg/status.": "No readable entries were found in /var/lib/opkg/status.",
    "Baza pakietów nie zawiera niepełnych instalacji": "The package database contains no incomplete installations",
    "Nie można odczytać informacji o systemie plików": "Filesystem information could not be read",
    "Nie jest odtwarzany kanał": "No channel is currently playing",
    "Aktualna usługa nie korzysta z głowicy DVB": "The current service does not use a DVB tuner",
    "Odczyt parametrów sygnału jest niedostępny": "Signal parameters are unavailable",
    "Nie udało się wykonać odczytu": "The reading could not be completed",
    "Nie udało się odczytać obciążenia": "System load could not be read",
    "Brak aktywnej usługi.": "No active service.",
    "Brak ostrzeżeń i błędów.": "No warnings or errors.",
    "Brak wyników dla wybranego modułu.": "No results are available for the selected module.",
    "Wtyczka wymaga środowiska Python 3": "The plug-in requires Python 3",
}

_REGEX_EN = [
    (r"^Krytycznie mało wolnego miejsca: (.+)$", r"Critically low free space: \1"),
    (r"^Mało wolnego miejsca: (.+)$", r"Low free space: \1"),
    (r"^Wolne: (.+)$", r"Free: \1"),
    (r"^Krytycznie mało dostępnej pamięci RAM: (.+)$", r"Critically low available RAM: \1"),
    (r"^Mało dostępnej pamięci RAM: (.+)$", r"Low available RAM: \1"),
    (r"^Dostępne: (.+)$", r"Available: \1"),
    (r"^Brakujące odwołania do bukietów: (\d+)$", r"Missing bouquet references: \1"),
    (r"^Bukiety: (\d+), brak błędnych odwołań$", r"Bouquets: \1, no invalid references"),
    (r"^Wykryto wpisy konfiguracji: (\d+)$", r"Configuration entries detected: \1"),
    (r"^Liczba wykrytych głowic: (\d+)$", r"Detected tuners: \1"),
    (r"^Wykryto zewnętrzne nośniki: (\d+)$", r"External storage devices detected: \1"),
    (r"^Nie wykryto zewnętrznego nośnika$", r"No external storage device was detected"),
    (r"^Nośniki tylko do odczytu: (.+)$", r"Read-only storage devices: \1"),
    (r"^Rozmiar: (.+)$", r"Size: \1"),
    (r"^Wykryto picony: (\d+)$", r"Picons detected: \1"),
    (r"^Crashlogi: (\d+), brak rozpoznanego wzorca$", r"Crashlogs: \1, no recognised pattern"),
    (r"^Crashlogi: (\d+), brak jednoznacznego rozpoznania$", r"Crashlogs: \1, no unambiguous diagnosis"),
    (r"^Wykryto ostrzeżenia dotyczące nośników: (\d+)$", r"Storage warnings detected: \1"),
    (r"^Wykryto pakiety w niepełnym stanie: (\d+)$", r"Packages in an incomplete state: \1"),
    (r"^Temperatura krytyczna: (.+)$", r"Critical temperature: \1"),
    (r"^Wysoka temperatura: (.+)$", r"High temperature: \1"),
    (r"^Bardzo wysokie obciążenie CPU: (.+)$", r"Very high CPU load: \1"),
    (r"^Wysokie obciążenie CPU: (.+)$", r"High CPU load: \1"),
    (r"^Obciążenie 1 min: (.+)$", r"1-minute load: \1"),
    (r"^Brak modułu Python: (.+)$", r"Missing Python module: \1"),
    (r"^Błąd importu: (.+)$", r"Import error: \1"),
    (r"^Błąd skina: (.+)$", r"Skin error: \1"),
    (r"^Błąd składni Python: (.+)$", r"Python syntax error: \1"),
    (r"^Błąd wcięć Python: (.+)$", r"Python indentation error: \1"),
    (r"^Błąd typu danych: (.+)$", r"Data type error: \1"),
    (r"^Błąd wykonania: (.+)$", r"Runtime error: \1"),
    (r"^Brak klucza w danych wtyczki: (.+)$", r"Missing key in plug-in data: \1"),
    (r"^Błąd indeksu lub listy we wtyczce: (.+)$", r"Index or list error in plug-in: \1"),
    (r"^Błąd zgodności wtyczki lub API: (.+)$", r"Plug-in or API compatibility error: \1"),
    (r"^Brak wolnego miejsca na urządzeniu$", r"No space left on device"),
    (r"^Brak uprawnień do pliku lub katalogu$", r"Permission denied for a file or directory"),
    (r"^System plików jest zamontowany tylko do odczytu$", r"The filesystem is mounted read-only"),
    (r"^Błąd weryfikacji certyfikatu HTTPS$", r"HTTPS certificate verification error"),
    (r"^Sieć jest niedostępna$", r"The network is unavailable"),
    (r"^Błąd segmentacji składnika systemowego$", r"System component segmentation fault"),
]

_LINE_REPLACEMENTS_EN = [
    ("System:", "System:"),
    ("Kompilacja:", "Build:"),
    ("Architektura:", "Architecture:"),
    ("Całkowita:", "Total:"),
    ("Dostępne:", "Available:"),
    ("Wolne:", "Free:"),
    ("SWAP wolny:", "Free swap:"),
    ("Lokalny czas systemowy:", "Local system time:"),
    ("Odnalezione adresy:", "Resolved addresses:"),
    ("Połączenie TCP z", "TCP connection to"),
    ("Najnowszy log:", "Newest log:"),
    ("Ostatnia modyfikacja:", "Last modified:"),
    ("Wykryte logi:", "Detected logs:"),
    ("Liczba logów:", "Log count:"),
    ("Powtórzenia tego błędu:", "Occurrences of this error:"),
    ("Wiek logu:", "Log age:"),
    ("Podejrzana wtyczka:", "Suspected plug-in:"),
    ("Plik:", "File:"),
    ("Linia:", "Line:"),
    ("funkcja:", "function:"),
    ("Rozpoznanie:", "Diagnosis:"),
    ("Referencja:", "Reference:"),
    ("Zainstalowane wpisy:", "Installed entries:"),
    ("Nieprawidłowe stany:", "Invalid states:"),
    ("Punkty montowania", "Mount points"),
    ("Wykorzystanie miejsca", "Space usage"),
    ("Ostatnie komunikaty kernela", "Latest kernel messages"),
    ("Brak danych", "No data"),
    ("godz.", "hours"),
]


def translate_text(value):
    if not is_english() or value is None:
        return value
    text = str(value)
    if text in _TITLE_EN:
        return _TITLE_EN[text]
    if text in _EXACT_EN:
        return _EXACT_EN[text]
    lines = []
    for original_line in text.split("\n"):
        line = _TITLE_EN.get(original_line, _EXACT_EN.get(original_line, original_line))
        for pattern, replacement in _REGEX_EN:
            if re.match(pattern, line):
                line = re.sub(pattern, replacement, line)
                break
        for source, target in _LINE_REPLACEMENTS_EN:
            line = line.replace(source, target)
        lines.append(line)
    return "\n".join(lines)


def translated_item(item):
    result = dict(item or {})
    for key in ("title", "summary", "details"):
        result[key] = translate_text(result.get(key, ""))
    return result


# Polish and English solution databases.
_SOLUTIONS_PL_23 = SOLUTIONS
try:
    with open(os.path.join(PLUGIN_PATH, "data", "solutions_en.json"), "r", encoding="utf-8") as _handle:
        _SOLUTIONS_EN_23 = json.load(_handle)
except Exception:
    _SOLUTIONS_EN_23 = {}


def get_solution(item):
    solution_id = (item or {}).get("solution_id")
    database = _SOLUTIONS_EN_23 if is_english() else _SOLUTIONS_PL_23
    raw = database.get(solution_id, {}) if solution_id else {}
    context = dict((item or {}).get("context") or {})
    context.setdefault("title", translate_text((item or {}).get("title", "")))
    context.setdefault("summary", translate_text((item or {}).get("summary", "")))
    context.setdefault("plugin", L("nie ustalono", "not determined"))
    context.setdefault("module", L("nie ustalono", "not determined"))
    context.setdefault("error", translate_text((item or {}).get("summary", L("nie ustalono", "not determined"))))
    context.setdefault("file", L("nie ustalono", "not determined"))
    context.setdefault("line", L("nie ustalono", "not determined"))
    context.setdefault("function", L("nie ustalono", "not determined"))
    solution = {}
    for key, value in raw.items():
        if isinstance(value, list):
            solution[key] = [safe_format(entry, context) for entry in value]
        else:
            solution[key] = safe_format(value, context)
    if (item or {}).get("safe_action"):
        solution["action"] = (item or {}).get("safe_action")
    if solution.get("action") == "disable_suspect_plugin":
        solution.setdefault("action_label", L("Wyłącz podejrzaną wtyczkę", "Disable suspected plug-in"))
    return solution


def status_name(status):
    if is_english():
        return {STATUS_OK: "RESULT OK", STATUS_WARN: "WARNING", STATUS_ERROR: "ERROR DETECTED", STATUS_INFO: "INFORMATION"}.get(status, "RESULT")
    return {STATUS_OK: "WYNIK PRAWIDŁOWY", STATUS_WARN: "OSTRZEŻENIE", STATUS_ERROR: "WYKRYTY BŁĄD", STATUS_INFO: "INFORMACJA"}.get(status, "WYNIK")


def health_grade(score):
    if score >= 92:
        return L("ZNAKOMITY", "EXCELLENT")
    if score >= 78:
        return L("DOBRY", "GOOD")
    if score >= 58:
        return L("WYMAGA UWAGI", "NEEDS ATTENTION")
    return L("KRYTYCZNY", "CRITICAL")


def build_solution_text(item, include_technical=False):
    shown = translated_item(item)
    solution = get_solution(item)
    lines = [status_name((item or {}).get("status")), "", shown.get("title", ""), L("Wykryto: %s", "Detected: %s") % shown.get("summary", "")]
    if solution:
        lines.extend(["", L("MOŻLIWA PRZYCZYNA", "POSSIBLE CAUSE"), "", solution.get("cause", L("Brak dodatkowego opisu przyczyny.", "No additional cause description is available."))])
        consequences = solution.get("consequences")
        if consequences:
            lines.extend(["", L("MOŻLIWE SKUTKI", "POSSIBLE CONSEQUENCES"), "", consequences])
        steps = solution.get("steps") or []
        if steps:
            lines.extend(["", L("CO NALEŻY ZROBIĆ", "WHAT TO DO"), ""])
            for index, step in enumerate(steps, 1):
                lines.append("%d. %s" % (index, step))
        restart = solution.get("restart")
        if restart:
            lines.extend(["", L("RESTART", "RESTART"), "", restart])
        action = solution.get("action")
        if action:
            lines.extend(["", L("BEZPIECZNE DZIAŁANIE", "SAFE ACTION"), "", L("Zielony przycisk: %s", "Green button: %s") % solution.get("action_label", L("Wykonaj działanie", "Run action"))])
        elif (item or {}).get("status") in (STATUS_WARN, STATUS_ERROR):
            lines.extend(["", L("DZIAŁANIE AUTOMATYCZNE", "AUTOMATIC ACTION"), "", L("Dla tego wyniku nie ma bezpiecznej automatycznej naprawy. Wykonaj podane kroki ręcznie.", "No safe automatic repair is available for this result. Follow the instructions manually.")])
    else:
        if (item or {}).get("status") in (STATUS_OK, STATUS_INFO):
            lines.extend(["", L("Nie wykryto problemu wymagającego naprawy.", "No problem requiring repair was detected.")])
        else:
            lines.extend(["", L("Brak gotowej instrukcji dla tego wyniku. Zapisz raport i sprawdź dane techniczne.", "No ready-made instructions are available for this result. Save a report and review the technical data.")])
    if include_technical:
        lines.extend(["", L("DANE TECHNICZNE", "TECHNICAL DATA"), "", shown.get("details", L("Brak danych technicznych.", "No technical data."))])
    return "\n".join(lines)


_make_report_pl_23 = make_report

def make_report(results):
    if not is_english():
        return _make_report_pl_23(results)
    now = datetime.datetime.now()
    path = os.path.join(choose_writable_report_dir(), "E2Doctor_Report_%s.txt" % now.strftime("%Y%m%d_%H%M%S"))
    distro, version, build = get_image_info()
    lines = [
        "E2 Doctor diagnostic report", "Created: %s" % now.strftime("%Y-%m-%d %H:%M:%S"),
        "Plug-in version: %s" % PLUGIN_VERSION, "Author: %s" % PLUGIN_AUTHOR,
        "System: %s %s" % (distro, version), "Build: %s" % (build or "unknown"),
        "Python: %s" % sys.version.replace("\n", " "),
        "Architecture: %s" % (os.uname().machine if hasattr(os, "uname") else "unknown"), "",
        "NOTICE: The report does not contain passwords, OSCam server lines or the complete settings file.", "",
    ]
    for item in results:
        shown = translated_item(item)
        lines.extend(["=" * 72, "%s %s" % (status_prefix(item.get("status")), shown.get("title")), shown.get("summary"), "-" * 72, shown.get("details")])
        if item.get("status") in (STATUS_WARN, STATUS_ERROR) and item.get("solution_id"):
            lines.extend(["", "POSSIBLE SOLUTION", "-" * 72, build_solution_text(item, include_technical=False)])
        lines.append("")
    code, uptime, _ = run_command("uptime", timeout=3)
    if code == 0:
        lines.extend(["=" * 72, "System uptime", uptime, ""])
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


_ACTION_EN_23 = {
    "safe_flash_cleanup": ("Safely clean flash", "Remove only old crashlogs, OPKG archives and memory dumps. Enigma2 settings and data remain unchanged.", "Clean flash"),
    "find_large_files": ("Show largest files", "Find the files using the most space without deleting them.", "Large files"),
    "safe_ram_refresh": ("Safely refresh RAM", "Write pending data and release only kernel cache. Processes and configuration are not stopped.", "Refresh RAM"),
    "show_processes": ("Show RAM-consuming processes", "Check which processes use the most memory. Nothing will be terminated.", "RAM processes"),
    "repair_bouquet_refs": ("Repair bouquet references", "Back up the index files and remove only entries pointing to missing bouquets.", "Repair bouquets"),
    "reload_bouquets": ("Reload channel list", "Refresh channel lists without deleting bouquets, tuner settings or other configuration.", "Reload list"),
    "remove_opkg_lock": ("Remove inactive OPKG lock", "Remove the lock only when the package manager is not running.", "Remove lock"),
    "restart_oscam": ("Restart OSCam", "Find the correct system script and safely restart the service.", "Restart OSCam"),
    "sync_time": ("Synchronise date and time", "Start the time-synchronisation mechanism available in the image.", "Synchronise time"),
    "network_test": ("Run extended network test", "Check the interface, IP address, gateway, DNS and HTTPS without changing configuration.", "Network test"),
    "disable_suspect_plugin": ("Temporarily disable suspected plug-in", "Rename the plug-in directory without deleting it. The change can be reverted.", "Disable plug-in"),
    "cleanup_crashlogs": ("Remove old crashlogs", "Keep the three latest logs required for further diagnostics.", "Remove old logs"),
    "emergency_report": ("Create emergency report", "Save a report that can be sent to a support person.", "Emergency report"),
    "storage_diagnostic": ("Show storage diagnostics", "Display mounts, free space and recent kernel messages without repairing the filesystem.", "Diagnostics"),
    "restart_gui": ("Restart Enigma2 GUI", "Close and restart Enigma2. Recordings and running operations may be interrupted.", "Restart GUI"),
}


def action_title(action_name):
    if is_english() and action_name in _ACTION_EN_23:
        return _ACTION_EN_23[action_name][0]
    return ACTION_REGISTRY.get(action_name, {}).get("title", action_name)


def action_description(action_name):
    if is_english() and action_name in _ACTION_EN_23:
        return _ACTION_EN_23[action_name][1]
    return ACTION_REGISTRY.get(action_name, {}).get("description", "")


def action_button_label(action_name):
    if is_english() and action_name in _ACTION_EN_23:
        return _ACTION_EN_23[action_name][2]
    labels = {
        "safe_flash_cleanup": "Oczyść flash", "find_large_files": "Duże pliki", "safe_ram_refresh": "Odśwież RAM",
        "show_processes": "Procesy RAM", "repair_bouquet_refs": "Napraw bukiety", "reload_bouquets": "Przeładuj listę",
        "remove_opkg_lock": "Usuń blokadę", "restart_oscam": "Restart OSCam", "sync_time": "Synchronizuj czas",
        "network_test": "Test sieci", "disable_suspect_plugin": "Wyłącz wtyczkę", "cleanup_crashlogs": "Usuń stare logi",
        "emergency_report": "Raport awaryjny", "storage_diagnostic": "Diagnostyka", "restart_gui": "Restart GUI",
    }
    return labels.get(action_name, action_title(action_name))


# Localised confirmation and action output.
def _request_action_23(self, action_name, item=None, on_done=None):
    self._e2d_pending_action = action_name
    self._e2d_pending_item = item or {}
    self._e2d_pending_done = on_done
    if action_name == "safe_flash_cleanup":
        preview, entries, total = safe_flash_cleanup_preview()
        self._e2d_flash_entries = entries
        if not entries:
            self.session.open(E2DoctorTextScreen, L("Bezpieczne czyszczenie flash", "Safe flash cleanup"), preview, L("Brak plików do usunięcia", "No files to remove"))
            return
        text = L(
            "E2 Doctor znalazł %d bezpiecznych plików o łącznym rozmiarze %s.\n\nUsunięte zostaną wyłącznie stare crashlogi, archiwa OPKG i zrzuty pamięci. Ustawienia, listy kanałów, wtyczki, EPG i picony pozostaną bez zmian.\n\nKontynuować?",
            "E2 Doctor found %d safe files with a total size of %s.\n\nOnly old crashlogs, OPKG archives and memory dumps will be removed. Settings, channel lists, plug-ins, EPG and picons will remain unchanged.\n\nContinue?"
        ) % (len(entries), format_bytes(total))
        self.session.openWithCallback(self._confirmed_action, MessageBox, text, MessageBox.TYPE_YESNO)
        return
    confirmations = {
        "safe_ram_refresh": L("Bezpiecznie odświeżyć pamięć podręczną RAM?\n\nProcesy nie zostaną zakończone, a ustawienia nie zostaną zmienione.", "Safely refresh the RAM cache?\n\nProcesses will not be terminated and settings will not be changed."),
        "repair_bouquet_refs": L("Naprawić brakujące odwołania do bukietów?\n\nPrzed zmianą E2 Doctor utworzy kopię plików indeksu w /etc/enigma2.", "Repair missing bouquet references?\n\nE2 Doctor will back up the index files in /etc/enigma2 before making changes."),
        "remove_opkg_lock": L("Usunąć nieaktywną blokadę OPKG?", "Remove the inactive OPKG lock?"),
        "restart_oscam": L("Uruchomić ponownie OSCam?", "Restart OSCam?"),
        "sync_time": L("Spróbować zsynchronizować datę i czas systemowy?", "Try to synchronise the system date and time?"),
        "disable_suspect_plugin": L("Tymczasowo wyłączyć podejrzaną wtyczkę %s?\n\nKatalog zostanie jedynie przemianowany. Operację można cofnąć w Narzędziach E2 Doctor.", "Temporarily disable the suspected plug-in %s?\n\nIts directory will only be renamed. The operation can be reverted in E2 Doctor Tools.") % (item or {}).get("context", {}).get("plugin", ""),
        "cleanup_crashlogs": L("Usunąć stare crashlogi i pozostawić trzy najnowsze?", "Remove old crashlogs and keep the three newest?"),
        "reload_bouquets": L("Przeładować listę kanałów bez usuwania ustawień i bukietów?", "Reload the channel list without removing settings or bouquets?"),
        "restart_gui": L("Uruchomić ponownie GUI Enigma2?\n\nPrzed wykonaniem zakończ trwające nagrania i ważne operacje.", "Restart the Enigma2 GUI?\n\nFinish active recordings and important operations first."),
    }
    if action_name in confirmations:
        self.session.openWithCallback(self._confirmed_action, MessageBox, confirmations[action_name], MessageBox.TYPE_YESNO)
    else:
        self._execute_pending_action()


E2DoctorActionMixin.request_action = _request_action_23
_old_show_action_message_23 = E2DoctorActionMixin._show_action_message
_old_open_action_text_23 = E2DoctorActionMixin._open_action_text

def _show_action_message_23(self, message, changed=False, error=False):
    return _old_show_action_message_23(self, translate_text(message), changed, error)

def _open_action_text_23(self, title, text, status="E2 Doctor 2.3"):
    return _old_open_action_text_23(self, translate_text(title), translate_text(text), translate_text(status))

E2DoctorActionMixin._show_action_message = _show_action_message_23
E2DoctorActionMixin._open_action_text = _open_action_text_23


MODULE_TEXT_23 = {
    "repair": ("Centrum szybkiej naprawy", "Quick Repair Centre", "Działania bezpieczne dopasowane do wykrytych problemów", "Safe actions matched to detected problems"),
    "problems": ("Najważniejsze problemy", "Priority problems", "Najważniejsze alerty wymagające uwagi użytkownika", "The most important alerts requiring attention"),
    "system": ("System i wydajność", "System and performance", "Flash, RAM, CPU, temperatura i stan pracy tunera", "Flash, RAM, CPU, temperature and receiver health"),
    "crashlogs": ("Analizator crashlogów", "Crashlog analyser", "Analiza crashlogów, wskazanie błędu i źródła problemu", "Crashlog analysis, error location and likely source"),
    "network": ("Sieć i internet", "Network and internet", "Adresacja, DNS, brama i połączenie HTTPS", "Addressing, DNS, gateway and HTTPS connection"),
    "channels": ("Listy kanałów", "Channel lists", "Bukiety, lamedb, indeksy i brakujące odwołania", "Bouquets, lamedb, indexes and missing references"),
    "tuners": ("Głowice i sygnał", "Tuners and signal", "Wykryte głowice, konfiguracja i bieżący LOCK", "Detected tuners, configuration and current LOCK"),
    "storage": ("Nośniki i systemy plików", "Storage and filesystems", "Nośniki, miejsce, montowanie i bezpieczeństwo zapisu", "Devices, free space, mounts and write safety"),
    "packages": ("Pakiety OPKG", "OPKG packages", "Kontrola OPKG, zależności i niepełne instalacje", "OPKG status, dependencies and incomplete installations"),
    "oscam": ("OSCam", "OSCam", "Stan procesu, konfiguracja i szybki restart OSCam", "Process state, configuration and quick restart"),
    "media": ("EPG i picony", "EPG and picons", "EPG, picony i podstawowa poprawność danych", "EPG, picons and basic data integrity"),
    "history": ("Historia stanu dekodera", "Receiver health history", "Porównanie skanów i wykrywanie zmian w systemie", "Scan comparison and system-change detection"),
    "py3": ("Zgodność wtyczek z Python 3", "Python 3 compatibility", "Skan zgodności wtyczek z Pythonem 3", "Plug-in compatibility scan for Python 3"),
    "ipk": ("E2 Safe Installer", "E2 Safe Installer", "Analiza paczek IPK przed instalacją", "Analyse IPK packages before installation"),
    "tools": ("Bezpieczne narzędzia", "Safe tools", "Narzędzia ręczne, raport i cofanie zmian", "Manual tools, reports and rollback"),
    "update": ("Aktualizacja z GitHub", "GitHub update", "Sprawdź nową wersję i wykonaj aktualizację z GitHub", "Check for a new version and update from GitHub"),
}


def module_title_23(key):
    values = MODULE_TEXT_23.get(key, (key, key, "", ""))
    return values[1] if is_english() else values[0]


def module_hint_23(key):
    values = MODULE_TEXT_23.get(key, (key, key, "", ""))
    return values[3] if is_english() else values[2]


def module_badge(results, key):
    if key == "update":
        return STATUS_INFO, L("AKTUALIZUJ", "UPDATE")
    if key == "repair":
        count = len(quick_repair_entries(results))
        if not results:
            return STATUS_INFO, L("SKAN", "SCAN")
        if count:
            return STATUS_WARN, L("%d AKCJI", "%d ACTIONS") % count
        return STATUS_OK, L("GOTOWE", "READY")
    selected = module_results(results, key)
    if key in ("history", "py3", "ipk", "tools"):
        return STATUS_INFO, L("OTWÓRZ", "OPEN")
    if key == "problems" and not selected and results:
        return STATUS_OK, L("BRAK", "NONE")
    if not selected:
        return STATUS_INFO, L("BRAK", "NONE")
    errors = len([item for item in selected if item.get("status") == STATUS_ERROR])
    warnings = len([item for item in selected if item.get("status") == STATUS_WARN])
    if errors:
        if is_english():
            return STATUS_ERROR, "%d ERROR%s" % (errors, "" if errors == 1 else "S")
        return STATUS_ERROR, ("%d BŁĄD" % errors) if errors == 1 else ("%d BŁĘDY" % errors if errors <= 4 else "%d BŁĘDÓW" % errors)
    if warnings:
        return STATUS_WARN, L("%d OSTRZ.", "%d WARN.") % warnings
    return STATUS_OK, "OK"


def module_subtitle(results, key, default=""):
    if key == "repair":
        count = len(quick_repair_entries(results))
        if count:
            return L("Dostępne bezpieczne działania: %d", "%d safe actions available") % count
        return L("Brak wymaganych działań", "No actions required")
    selected = module_results(results, key)
    problematic = [item for item in selected if item.get("status") in (STATUS_ERROR, STATUS_WARN)]
    if problematic:
        problematic.sort(key=lambda item: STATUS_RANK.get(item.get("status"), 0), reverse=True)
        return translate_text(problematic[0].get("summary", module_hint_23(key)))
    return module_hint_23(key)


def dashboard_recommendation(results):
    if not results:
        return L("GOTOWY: uruchom pełny skan, aby E2 Doctor przygotował zalecenia i bezpieczne działania.", "READY: run a full scan so E2 Doctor can prepare recommendations and safe actions.")
    problems = [item for item in results if item.get("status") in (STATUS_ERROR, STATUS_WARN)]
    problems.sort(key=lambda item: STATUS_RANK.get(item.get("status"), 0), reverse=True)
    if problems:
        item = translated_item(problems[0])
        count = len(quick_repair_entries(results))
        return L("PRIORYTET: %s — %s | Centrum naprawy: %d działań", "PRIORITY: %s — %s | Repair centre: %d actions") % (item.get("title", ""), item.get("summary", ""), count)
    return L("SYSTEM W DOBREJ KONDYCJI: nie wykryto błędów ani ostrzeżeń wymagających działania.", "SYSTEM HEALTHY: no errors or warnings requiring action were detected.")


def compare_snapshots(current, previous):
    if not current or not previous:
        return L("To pierwszy zapisany skan E2 Doctor.", "This is the first saved E2 Doctor scan.")
    current_map = {x.get("key"): x for x in current.get("issues", [])}
    previous_map = {x.get("key"): x for x in previous.get("issues", [])}
    new_items, resolved, worsened = [], [], []
    for key, item in current_map.items():
        old = previous_map.get(key)
        if old is None:
            new_items.append(item)
        elif STATUS_RANK.get(item.get("status"), 0) > STATUS_RANK.get(old.get("status"), 0):
            worsened.append(item)
    for key, item in previous_map.items():
        if key not in current_map:
            resolved.append(item)
    diff = int(current.get("score", 0)) - int(previous.get("score", 0))
    lines = [L("Zmiana wyniku: %+d pkt", "Score change: %+d pts") % diff]
    if new_items:
        lines.append(L("Nowe problemy: %s", "New problems: %s") % ", ".join(translate_text(x.get("title", "")) for x in new_items[:4]))
    if worsened:
        lines.append(L("Pogorszenie: %s", "Worsened: %s") % ", ".join(translate_text(x.get("title", "")) for x in worsened[:4]))
    if resolved:
        lines.append(L("Rozwiązane: %s", "Resolved: %s") % ", ".join(translate_text(x.get("title", "")) for x in resolved[:4]))
    if not new_items and not worsened and not resolved:
        lines.append(L("Nie wykryto zmian w problemach.", "No changes in detected problems."))
    return " | ".join(lines)


def current_change_summary(results):
    history = load_history()
    current = compact_snapshot(results)
    previous = None
    if history:
        if snapshot_signature(history[0]) == snapshot_signature(current) and len(history) > 1:
            previous = history[1]
        else:
            previous = history[0]
    return compare_snapshots(current, previous)


# Correctly sized icons: Enigma2 MultiContent clips pixmaps instead of scaling them.
MODULE_ICONS_23 = {}
if LoadPixmap is not None:
    _icon_set = "fhd" if E2D_FHD else "hd"
    for _key in MODULE_TEXT_23.keys():
        _path = os.path.join(PLUGIN_PATH, "icons", _icon_set, "%s.png" % _key)
        try:
            MODULE_ICONS_23[_key] = LoadPixmap(cached=True, path=_path) if os.path.exists(_path) else None
        except Exception:
            MODULE_ICONS_23[_key] = None


class E2DoctorDashboardList(MenuList):
    def __init__(self, entries=None):
        MenuList.__init__(self, entries or [], enableWrapAround=True, content=eListboxPythonMultiContent)
        self.l.setFont(0, gFont("Regular", 18 if E2D_FHD else 14))
        self.l.setFont(1, gFont("Regular", E2D_FONT_TITLE))
        self.l.setFont(2, gFont("Regular", E2D_FONT_SMALL))
        self.l.setFont(3, gFont("Regular", E2D_FONT_TINY))
        self.l.setFont(4, gFont("Regular", 20 if E2D_FHD else 15))
        self.l.setItemHeight(92 if E2D_FHD else 72)
        self.l.setBuildFunc(self.build_entry)

    def build_entry(self, key, code, title, subtitle, status, badge):
        status_color = STATUS_COLORS.get(status, 0x008A9AA5)
        item_h = 92 if E2D_FHD else 72
        content_w = E2D_LIST_W
        icon_size = 54 if E2D_FHD else 42
        icon_box = 84 if E2D_FHD else 66
        badge_w = 180 if E2D_FHD else 142
        title_x = icon_box + 24
        text_w = content_w - title_x - badge_w - 26
        icon = MODULE_ICONS_23.get(key)
        short_note = {
            STATUS_OK: L("Bez działania", "No action"),
            STATUS_INFO: L("Otwórz moduł", "Open module"),
            STATUS_WARN: L("Sprawdź zalecenia", "Review advice"),
            STATUS_ERROR: L("Wymaga działania", "Action required"),
        }.get(status, "")
        entries = [
            None,
            MultiContentEntryText(pos=(0, 4), size=(content_w, item_h - 8), font=2, text="", backcolor=0x00122029, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(0, 4), size=(6, item_h - 8), font=2, text="", backcolor=status_color, backcolor_sel=status_color),
            MultiContentEntryText(pos=(18, 14 if E2D_FHD else 11), size=(icon_box, item_h - (28 if E2D_FHD else 22)), font=4, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text="", backcolor=0x00193342, backcolor_sel=0x0028495A),
            MultiContentEntryText(pos=(title_x, 10 if E2D_FHD else 8), size=(text_w, 22), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=code + L("  •  MODUŁ", "  •  MODULE"), color=0x0078DCE4, color_sel=0x0096ECF2, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(title_x, 28 if E2D_FHD else 21), size=(text_w, 34), font=1, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=title, color=0x00FFFFFF, color_sel=0x00FFFFFF, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(title_x, 58 if E2D_FHD else 46), size=(text_w, 22), font=3, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=subtitle, color=0x009BB2BD, color_sel=0x00D8E8EE, backcolor_sel=0x00223E4D),
            MultiContentEntryText(pos=(content_w - badge_w - 18, 18 if E2D_FHD else 12), size=(badge_w, item_h - (36 if E2D_FHD else 24)), font=4, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text="", backcolor=0x00142B35, backcolor_sel=0x00193442),
            MultiContentEntryText(pos=(content_w - badge_w - 18, 26 if E2D_FHD else 18), size=(badge_w, 24), font=2, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=badge, color=status_color, color_sel=status_color, backcolor_sel=0x00193442),
            MultiContentEntryText(pos=(content_w - badge_w - 18, 50 if E2D_FHD else 39), size=(badge_w, 18), font=3, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=short_note, color=0x00C0CCD4, color_sel=0x00FFFFFF, backcolor_sel=0x00193442),
        ]
        if icon is not None and MultiContentEntryPixmapAlphaBlend is not None:
            entries.append(MultiContentEntryPixmapAlphaBlend(pos=(18 + int((icon_box - icon_size) / 2), 14 if E2D_FHD else 11), size=(icon_size, icon_size), png=icon))
        else:
            entries.append(MultiContentEntryText(pos=(18, 14 if E2D_FHD else 11), size=(icon_box, item_h - (28 if E2D_FHD else 22)), font=4, flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER, text=code, color=0x00FFFFFF, color_sel=0x00FFFFFF, backcolor_sel=0x0028495A))
        return entries


# Main dashboard language-aware methods.
_old_dashboard_init_23 = E2DoctorDashboard.__init__

def _apply_dashboard_language_23(self):
    self.settings = load_e2doctor_settings()
    self["brand_badge"].setText(L("INTELIGENTNA DIAGNOSTYKA  •  BEZPIECZNA NAPRAWA  •  STAŁA OPIEKA", "SMART DIAGNOSTICS  •  SAFE REPAIR  •  LIVE CARE"))
    self["subtitle"].setText(L("Centrum diagnostyki i bezpiecznej naprawy Enigma2", "Enigma2 diagnostics and safe repair centre"))
    self["score_title"].setText(L("KONDYCJA TUNERA", "RECEIVER HEALTH"))
    self["ok_label"].setText(L("POPRAWNE", "PASSED"))
    self["info_label"].setText(L("INFORMACJE", "INFORMATION"))
    self["warn_label"].setText(L("OSTRZEŻENIA", "WARNINGS"))
    self["error_label"].setText(L("BŁĘDY", "ERRORS"))
    self["key_red"].setText(L("Skanuj", "Scan"))
    self["key_green"].setText(L("Otwórz / napraw", "Open / repair"))
    self["key_yellow"].setText(L("Raport", "Report"))
    self["key_blue"].setText(L("Wyjście", "Exit"))
    self["footer"].setText(L(
        "E2 Doctor %s  •  by %s  •  %s  •  0: aktualizacja  •  MENU: ustawienia",
        "E2 Doctor %s  •  by %s  •  %s  •  0: update  •  MENU: settings"
    ) % (PLUGIN_VERSION, PLUGIN_AUTHOR, PLUGIN_EMAIL))
    if not self.results:
        self["score_grade"].setText(L("BRAK SKANU", "NOT SCANNED"))
        self["change"].setText(L("Gotowy do pełnej kontroli tunera", "Ready for a full receiver check"))
        self["recommendation"].setText(dashboard_recommendation([]))
    else:
        self.update_summary()
    self.refresh_dashboard()


def _dashboard_init_23(self, session):
    _old_dashboard_init_23(self, session)
    _apply_dashboard_language_23(self)


def _dashboard_refresh_23(self):
    rows = []
    for key, code, _title, _default_subtitle in DASHBOARD_MODULES:
        status, badge = module_badge(self.results, key)
        rows.append((key, code, module_title_23(key), module_subtitle(self.results, key), status, badge))
    self["dashboard"].setList(rows)


def _dashboard_update_summary_23(self, change_text=None):
    counts = result_counts(self.results)
    score = calculate_health_score(self.results)
    self["score_value"].setText("%d/100" % score)
    self["score_grade"].setText(health_grade(score))
    self["score_bar"].setValue(score)
    self["ok_count"].setText(str(counts.get(STATUS_OK, 0)))
    self["info_count"].setText(str(counts.get(STATUS_INFO, 0)))
    self["warn_count"].setText(str(counts.get(STATUS_WARN, 0)))
    self["error_count"].setText(str(counts.get(STATUS_ERROR, 0)))
    self["change"].setText(translate_text(change_text) if change_text else current_change_summary(self.results))
    self["recommendation"].setText(dashboard_recommendation(self.results))


def _dashboard_scan_23(self):
    self["change"].setText(L("Trwa pełna diagnostyka systemu...", "Running full system diagnostics..."))
    self["recommendation"].setText(L("ANALIZA: sprawdzanie systemu, sieci, list, głowic, nośników, OPKG i crashlogów...", "ANALYSIS: checking system, network, channel lists, tuners, storage, OPKG and crashlogs..."))
    try:
        previous_history = load_history()
        self.results = run_all_checks(self.session)
        current = compact_snapshot(self.results)
        previous = previous_history[0] if previous_history else None
        change_text = compare_snapshots(current, previous)
        save_history_snapshot(self.results)
        self.update_summary(change_text)
        self.refresh_dashboard()
    except Exception as error:
        self["change"].setText(L("Błąd diagnostyki: %s", "Diagnostic error: %s") % error)
        self["recommendation"].setText(L("Diagnostyka nie została ukończona. Otwórz raport błędu.", "Diagnostics did not complete. Open the error report."))
        self.session.open(MessageBox, L("Diagnostyka nie powiodła się:\n%s\n\n%s", "Diagnostics failed:\n%s\n\n%s") % (error, traceback.format_exc()), MessageBox.TYPE_ERROR)


def _dashboard_first_show_23(self):
    if self._scan_started:
        return
    self._scan_started = True
    self.settings = load_e2doctor_settings()
    _apply_dashboard_language_23(self)
    if self.settings.get("auto_scan", True):
        self.scan()
    else:
        self["change"].setText(L("Automatyczny skan jest wyłączony. Naciśnij czerwony przycisk.", "Automatic scanning is disabled. Press the red button."))


def _dashboard_open_selected_23(self):
    key = self.selected_key()
    if not key:
        return
    if key == "update":
        self.open_update()
        return
    if key == "repair":
        if not self.results:
            self.scan()
        self.session.openWithCallback(self.repair_closed, E2DoctorQuickRepairScreen, self.results)
    elif key == "history":
        self.session.open(E2DoctorHistoryScreen)
    elif key == "py3":
        self["change"].setText(L("Trwa skanowanie zgodności wtyczek z Pythonem 3...", "Scanning plug-ins for Python 3 compatibility..."))
        try:
            report = python3_compatibility_report()
            self.session.open(E2DoctorTextScreen, L("Zgodność z Pythonem 3", "Python 3 compatibility"), report, L("Analiza bez modyfikowania plików", "Analysis without modifying files"))
        except Exception as error:
            self.session.open(MessageBox, L("Skan zgodności nie powiódł się:\n%s", "Compatibility scan failed:\n%s") % error, MessageBox.TYPE_ERROR)
        finally:
            self["change"].setText(current_change_summary(self.results) if self.results else L("Gotowy", "Ready"))
    elif key == "ipk":
        self.session.open(E2DoctorIPKBrowser)
    elif key == "tools":
        self.open_tools()
    else:
        if not self.results:
            self.scan()
        selected = module_results(self.results, key)
        if not selected:
            self.session.open(MessageBox, L("Brak wyników dla wybranego modułu.", "No results are available for the selected module."), MessageBox.TYPE_INFO, timeout=5)
            return
        self.session.openWithCallback(self.results_closed, E2DoctorResultsScreen, module_title_23(key), selected)


def _dashboard_save_report_23(self):
    if not self.results:
        self.scan()
    if not self.results:
        return
    try:
        path = make_report(self.results)
        self.session.open(MessageBox, L("Raport zapisano w:\n%s", "Report saved to:\n%s") % path, MessageBox.TYPE_INFO, timeout=9)
    except Exception as error:
        self.session.open(MessageBox, L("Nie udało się utworzyć raportu:\n%s", "The report could not be created:\n%s") % error, MessageBox.TYPE_ERROR)


def _dashboard_settings_closed_23(self, changed=False):
    if changed:
        self.settings = load_e2doctor_settings()
        _apply_dashboard_language_23(self)


E2DoctorDashboard.__init__ = _dashboard_init_23
E2DoctorDashboard.refresh_dashboard = _dashboard_refresh_23
E2DoctorDashboard.update_summary = _dashboard_update_summary_23
E2DoctorDashboard.scan = _dashboard_scan_23
E2DoctorDashboard.first_show = _dashboard_first_show_23
E2DoctorDashboard.open_selected = _dashboard_open_selected_23
E2DoctorDashboard.save_report = _dashboard_save_report_23
E2DoctorDashboard.settings_closed = _dashboard_settings_closed_23


class E2DoctorTextScreen(Screen):
    skin = premium_text_skin("E2DoctorTextScreen")
    def __init__(self, session, title, text, status="E2 Doctor 2.3"):
        Screen.__init__(self, session)
        self["header_bg"] = Label("")
        self["accent"] = Label("")
        self["footer_bg"] = Label("")
        self["title"] = Label(translate_text(title))
        self["status"] = Label(translate_text(status))
        self["body"] = ScrollLabel(translate_text(text))
        self["key_red"] = StaticText(L("Wróć", "Back"))
        self["key_green"] = StaticText("")
        self["key_yellow"] = StaticText("")
        self["key_blue"] = StaticText(L("Wyjście", "Exit"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
            "cancel": self.close, "red": self.close, "blue": self.close, "ok": self.close,
            "up": self["body"].pageUp, "down": self["body"].pageDown,
            "left": self["body"].pageUp, "right": self["body"].pageDown,
        }, -1)


class E2DoctorProblemActionsScreen(E2DoctorActionMixin, Screen):
    skin = premium_results_skin("E2DoctorProblemActionsScreen")
    def __init__(self, session, item, title=None):
        Screen.__init__(self, session)
        self.item = item or {}
        self.changed = False
        self.actions_list = available_problem_actions(self.item)
        for name in ("header_bg", "accent", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label(title or L("Działania dla problemu", "Actions for this problem"))
        self["status"] = Label(L("Wybierz działanie. Każda zmiana wymaga potwierdzenia.", "Select an action. Every change requires confirmation."))
        rows = [(ACTION_REGISTRY.get(action, {}).get("status", STATUS_INFO), action_title(action), action_description(action)) for action in self.actions_list]
        if not rows:
            rows.append((STATUS_INFO, L("Brak bezpiecznych działań", "No safe actions"), L("Dla tego problemu dostępna jest wyłącznie instrukcja ręczna.", "Only manual instructions are available for this problem.")))
        self["list"] = E2DoctorV2ResultList(rows)
        self["key_red"] = StaticText(L("Wróć", "Back"))
        self["key_green"] = StaticText(L("Wykonaj", "Run"))
        self["key_yellow"] = StaticText(L("Opis", "Description"))
        self["key_blue"] = StaticText(L("Wyjście", "Exit"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "cancel": self.finish, "red": self.finish, "blue": self.finish,
            "ok": self.execute_selected, "green": self.execute_selected, "yellow": self.show_selected,
        }, -1)
    def selected_action(self):
        index = self["list"].getSelectedIndex()
        return self.actions_list[index] if 0 <= index < len(self.actions_list) else None
    def show_selected(self):
        action = self.selected_action()
        if action:
            self.session.open(E2DoctorTextScreen, action_title(action), action_description(action), L("Podgląd działania — nic nie zostało wykonane", "Action preview — nothing has been executed"))
    def execute_selected(self):
        action = self.selected_action()
        if action:
            self.request_action(action, self.item, self.action_finished)
    def action_finished(self, changed=False):
        self.changed = self.changed or bool(changed)
    def finish(self):
        self.close(self.changed)


class E2DoctorSolutionScreen(E2DoctorActionMixin, Screen):
    skin = premium_text_skin("E2DoctorSolutionScreen")
    def __init__(self, session, item):
        Screen.__init__(self, session)
        self.item = item
        self.actions_list = available_problem_actions(item)
        self.primary_action = self.actions_list[0] if self.actions_list else None
        for name in ("header_bg", "accent", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label(L("Diagnoza i możliwe rozwiązanie", "Diagnosis and possible solution"))
        self["status"] = Label("%s — %s" % (status_name(item.get("status")), translate_text(item.get("title", ""))))
        self["body"] = ScrollLabel(build_solution_text(item, include_technical=False))
        self["key_red"] = StaticText(L("Wróć", "Back"))
        self["key_green"] = StaticText(action_button_label(self.primary_action) if self.primary_action else L("Brak auto-naprawy", "No auto-repair"))
        self["key_yellow"] = StaticText(L("Dane techniczne", "Technical data"))
        self["key_blue"] = StaticText(L("Działania", "Actions") if self.actions_list else L("Zapisz instrukcję", "Save instructions"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions", "InfoActions", "MenuActions"], {
            "cancel": self.close, "red": self.close, "green": self.perform_primary,
            "yellow": self.show_technical, "blue": self.open_actions_or_save,
            "info": self.save_instruction, "menu": self.save_instruction,
            "up": self["body"].pageUp, "down": self["body"].pageDown,
            "left": self["body"].pageUp, "right": self["body"].pageDown,
        }, -1)
    def perform_primary(self):
        if not self.primary_action:
            self.session.open(MessageBox, L("Dla tego wyniku nie ma bezpiecznej automatycznej naprawy. Wykonaj podane kroki ręcznie.", "No safe automatic repair is available for this result. Follow the instructions manually."), MessageBox.TYPE_INFO, timeout=7)
            return
        self.request_action(self.primary_action, self.item, self.primary_finished)
    def primary_finished(self, changed=False):
        if changed:
            self.close(True)
    def open_actions_or_save(self):
        if self.actions_list:
            self.session.openWithCallback(self.actions_closed, E2DoctorProblemActionsScreen, self.item)
        else:
            self.save_instruction()
    def actions_closed(self, changed=False):
        if changed:
            self.close(True)
    def show_technical(self):
        self.session.open(E2DoctorTextScreen, L("Dane techniczne — %s", "Technical data — %s") % translate_text(self.item.get("title", "")), self.item.get("details", L("Brak danych technicznych.", "No technical data.")), L("Surowe dane diagnostyczne", "Raw diagnostic data"))
    def save_instruction(self):
        try:
            path = save_solution_instruction(self.item)
            self.session.open(MessageBox, L("Instrukcję zapisano w:\n%s", "Instructions saved to:\n%s") % path, MessageBox.TYPE_INFO, timeout=8)
        except Exception as error:
            self.session.open(MessageBox, L("Nie udało się zapisać instrukcji:\n%s", "Instructions could not be saved:\n%s") % error, MessageBox.TYPE_ERROR)


class E2DoctorResultsScreen(Screen):
    skin = premium_results_skin("E2DoctorResultsScreen")
    def __init__(self, session, title, results, status_text=""):
        Screen.__init__(self, session)
        self.results = list(results or [])
        self.changed = False
        for name in ("header_bg", "accent", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label(translate_text(title))
        counts = result_counts(self.results)
        default_status = L("OK %d | Informacje %d | Ostrzeżenia %d | Błędy %d", "OK %d | Information %d | Warnings %d | Errors %d") % (
            counts.get(STATUS_OK, 0), counts.get(STATUS_INFO, 0), counts.get(STATUS_WARN, 0), counts.get(STATUS_ERROR, 0))
        self["status"] = Label(translate_text(status_text) if status_text else default_status)
        self["list"] = E2DoctorV2ResultList([])
        self["key_red"] = StaticText(L("Wróć", "Back"))
        self["key_green"] = StaticText(L("Odczyt / naprawa", "Read / repair"))
        self["key_yellow"] = StaticText(L("Raport", "Report"))
        self["key_blue"] = StaticText(L("Wyjście", "Exit"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "cancel": self.finish, "red": self.finish, "blue": self.finish,
            "ok": self.open_selected, "green": self.open_selected, "yellow": self.save_report,
        }, -1)
        self.refresh_list()
    def refresh_list(self):
        self["list"].setList([(item.get("status"), translate_text(item.get("title", "")), translate_text(item.get("summary", ""))) for item in self.results])
    def open_selected(self):
        index = self["list"].getSelectedIndex()
        if 0 <= index < len(self.results):
            self.session.openWithCallback(self.solution_closed, E2DoctorSolutionScreen, self.results[index])
    def solution_closed(self, changed=False):
        if changed:
            self.changed = True
    def save_report(self):
        try:
            path = make_report(self.results)
            self.session.open(MessageBox, L("Raport zapisano w:\n%s", "Report saved to:\n%s") % path, MessageBox.TYPE_INFO, timeout=9)
        except Exception as error:
            self.session.open(MessageBox, L("Nie udało się utworzyć raportu:\n%s", "The report could not be created:\n%s") % error, MessageBox.TYPE_ERROR)
    def finish(self):
        self.close(self.changed)


class E2DoctorQuickRepairScreen(E2DoctorActionMixin, Screen):
    skin = premium_results_skin("E2DoctorQuickRepairScreen")
    def __init__(self, session, results):
        Screen.__init__(self, session)
        self.results = list(results or [])
        self.entries = quick_repair_entries(self.results)
        self.changed = False
        for name in ("header_bg", "accent", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label(L("Centrum szybkiej naprawy", "Quick Repair Centre"))
        self["status"] = Label(L("Dostępne działania: %d | Nic nie zostanie wykonane bez potwierdzenia", "Available actions: %d | Nothing will run without confirmation") % len(self.entries))
        rows = []
        for entry in self.entries:
            action = entry.get("action")
            item = entry.get("item") or {}
            rows.append((ACTION_REGISTRY.get(action, {}).get("status", STATUS_INFO), action_title(action), L("Problem: %s — %s", "Problem: %s — %s") % (translate_text(item.get("title", "")), translate_text(item.get("summary", "")))))
        if not rows:
            rows.append((STATUS_OK, L("Brak problemów wymagających bezpiecznej naprawy", "No problems require safe repair"), L("System nie zgłasza działań, które E2 Doctor może wykonać automatycznie.", "The system reports no actions that E2 Doctor can perform automatically.")))
        self["list"] = E2DoctorV2ResultList(rows)
        self["key_red"] = StaticText(L("Wróć", "Back"))
        self["key_green"] = StaticText(L("Wykonaj", "Run"))
        self["key_yellow"] = StaticText(L("Opis", "Description"))
        self["key_blue"] = StaticText(L("Wyjście", "Exit"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "cancel": self.finish, "red": self.finish, "blue": self.finish,
            "ok": self.execute_selected, "green": self.execute_selected, "yellow": self.show_selected,
        }, -1)
    def selected_entry(self):
        index = self["list"].getSelectedIndex()
        return self.entries[index] if 0 <= index < len(self.entries) else None
    def show_selected(self):
        entry = self.selected_entry()
        if not entry:
            return
        action = entry.get("action")
        item = entry.get("item") or {}
        text = "%s\n\n%s\n\n%s\n%s\n%s\n\n%s\n%s" % (
            action_title(action), action_description(action), L("WYKRYTY PROBLEM", "DETECTED PROBLEM"),
            translate_text(item.get("title", "")), translate_text(item.get("summary", "")),
            L("Dane techniczne:", "Technical data:"), translate_text(item.get("details", "")))
        self.session.open(E2DoctorTextScreen, L("Podgląd działania", "Action preview"), text, L("E2 Doctor nie wykonał jeszcze żadnej zmiany", "E2 Doctor has not made any changes"))
    def execute_selected(self):
        entry = self.selected_entry()
        if entry:
            self.request_action(entry.get("action"), entry.get("item"), self.action_finished)
    def action_finished(self, changed=False):
        self.changed = self.changed or bool(changed)
    def finish(self):
        self.close(self.changed)


class E2DoctorSettingsScreen(Screen):
    skin = premium_results_skin("E2DoctorSettingsScreen")
    def __init__(self, session):
        Screen.__init__(self, session)
        self.settings = load_e2doctor_settings()
        self.options = ["language", "auto_scan", "monitor_enabled", "monitor_interval_hours", "history_limit"]
        for name in ("header_bg", "accent", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label(L("Ustawienia E2 Doctor", "E2 Doctor settings"))
        self["status"] = Label(L("Lewo / prawo zmienia wartość. Zielony zapisuje ustawienia.", "Left / right changes the value. Green saves settings."))
        self["list"] = E2DoctorV2ResultList([])
        self["key_red"] = StaticText(L("Anuluj", "Cancel"))
        self["key_green"] = StaticText(L("Zapisz", "Save"))
        self["key_yellow"] = StaticText(L("Domyślne", "Defaults"))
        self["key_blue"] = StaticText(L("Wyjście", "Exit"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions"], {
            "cancel": self.close, "red": self.close, "blue": self.close,
            "green": self.save, "yellow": self.defaults,
            "left": self.change_left, "right": self.change_right, "ok": self.change_right,
        }, -1)
        self.refresh()
    def option_text(self, key):
        if key == "language":
            value = self.settings.get("language", "auto")
            if value == "pl":
                shown = "Polski"
            elif value == "en":
                shown = "English"
            else:
                shown = L("Automatycznie — język systemu", "Automatic — system language") + " (%s)" % ("Polski" if _system_language_code() == "pl" else "English")
            return L("Język wtyczki", "Plug-in language"), shown
        if key == "auto_scan":
            return L("Automatyczny skan po otwarciu", "Automatic scan on opening"), L("włączony", "enabled") if self.settings.get(key) else L("wyłączony", "disabled")
        if key == "monitor_enabled":
            return L("Monitor krytycznych problemów w tle", "Background critical-problem monitor"), L("włączony", "enabled") if self.settings.get(key) else L("wyłączony", "disabled")
        if key == "monitor_interval_hours":
            return L("Odstęp kontroli monitora", "Monitor check interval"), L("%d godz.", "%d hours") % self.settings.get(key, 6)
        if key == "history_limit":
            return L("Liczba zapisanych skanów", "Number of saved scans"), "%d" % self.settings.get(key, 20)
        return key, str(self.settings.get(key))
    def refresh(self):
        rows = []
        for key in self.options:
            title, value = self.option_text(key)
            rows.append((STATUS_INFO, title, L("Wartość: %s", "Value: %s") % value))
        self["list"].setList(rows)
    def modify(self, direction):
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.options):
            return
        key = self.options[index]
        if key == "language":
            values = ["auto", "pl", "en"]
            current = self.settings.get(key, "auto")
            try:
                pos = values.index(current)
            except Exception:
                pos = 0
            self.settings[key] = values[(pos + direction) % len(values)]
        elif key in ("auto_scan", "monitor_enabled"):
            self.settings[key] = not bool(self.settings.get(key))
        elif key == "monitor_interval_hours":
            values = [1, 3, 6, 12, 24]
            current = self.settings.get(key, 6)
            try:
                pos = values.index(current)
            except Exception:
                pos = 2
            self.settings[key] = values[(pos + direction) % len(values)]
        elif key == "history_limit":
            values = [5, 10, 20, 30, 50]
            current = self.settings.get(key, 20)
            try:
                pos = values.index(current)
            except Exception:
                pos = 2
            self.settings[key] = values[(pos + direction) % len(values)]
        self.refresh()
        try:
            self["list"].moveToIndex(index)
        except Exception:
            pass
    def change_left(self):
        self.modify(-1)
    def change_right(self):
        self.modify(1)
    def defaults(self):
        self.settings = dict(DEFAULT_SETTINGS)
        self.refresh()
    def save(self):
        try:
            save_e2doctor_settings(self.settings)
            self.session.openWithCallback(lambda *args: self.close(True), MessageBox, L("Ustawienia zostały zapisane.", "Settings have been saved."), MessageBox.TYPE_INFO, timeout=6)
        except Exception as error:
            self.session.open(MessageBox, L("Nie udało się zapisać ustawień:\n%s", "Settings could not be saved:\n%s") % error, MessageBox.TYPE_ERROR)


class E2DoctorHistoryScreen(Screen):
    skin = premium_results_skin("E2DoctorHistoryScreen")
    def __init__(self, session):
        Screen.__init__(self, session)
        self.history = load_history()
        for name in ("header_bg", "accent", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label(L("Historia stanu dekodera", "Receiver health history"))
        self["status"] = Label(L("Porównuj wyniki i sprawdzaj, co zmieniło się w systemie", "Compare scans and see what changed in the system"))
        self.entries = []
        for snapshot in self.history:
            counts = snapshot.get("counts") or {}
            title = "%s — %d/100 (%s)" % (snapshot.get("timestamp", L("brak daty", "no date")), snapshot.get("score", 0), translate_text(snapshot.get("grade", "")))
            summary = L("Błędy %d | Ostrzeżenia %d | %s", "Errors %d | Warnings %d | %s") % (counts.get(STATUS_ERROR, 0), counts.get(STATUS_WARN, 0), snapshot.get("system", "Enigma2"))
            status = STATUS_ERROR if counts.get(STATUS_ERROR, 0) else STATUS_WARN if counts.get(STATUS_WARN, 0) else STATUS_OK
            self.entries.append((status, title, summary))
        if not self.entries:
            self.entries.append((STATUS_INFO, L("Brak zapisanej historii", "No saved history"), L("Uruchom pełny skan E2 Doctor.", "Run a full E2 Doctor scan.")))
        self["list"] = E2DoctorV2ResultList(self.entries)
        self["key_red"] = StaticText(L("Wróć", "Back"))
        self["key_green"] = StaticText(L("Szczegóły", "Details"))
        self["key_yellow"] = StaticText(L("Wyczyść historię", "Clear history"))
        self["key_blue"] = StaticText(L("Wyjście", "Exit"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "cancel": self.close, "red": self.close, "blue": self.close,
            "ok": self.show_selected, "green": self.show_selected, "yellow": self.confirm_clear,
        }, -1)
    def show_selected(self):
        index = self["list"].getSelectedIndex()
        if not self.history or index < 0 or index >= len(self.history):
            return
        snapshot = self.history[index]
        previous = self.history[index + 1] if index + 1 < len(self.history) else None
        counts = snapshot.get("counts") or {}
        lines = [
            L("SKAN: %s", "SCAN: %s") % snapshot.get("timestamp", ""),
            L("Wynik: %d/100 — %s", "Score: %d/100 — %s") % (snapshot.get("score", 0), translate_text(snapshot.get("grade", ""))),
            "System: %s | Python %s" % (snapshot.get("system", ""), snapshot.get("python", "")),
            L("OK: %d | Informacje: %d | Ostrzeżenia: %d | Błędy: %d", "OK: %d | Information: %d | Warnings: %d | Errors: %d") % (counts.get(STATUS_OK, 0), counts.get(STATUS_INFO, 0), counts.get(STATUS_WARN, 0), counts.get(STATUS_ERROR, 0)),
            "", L("PORÓWNANIE Z POPRZEDNIM SKANEM", "COMPARISON WITH PREVIOUS SCAN"), compare_snapshots(snapshot, previous), "", L("WYKRYTE PROBLEMY", "DETECTED PROBLEMS"),
        ]
        issues = snapshot.get("issues") or []
        if issues:
            for issue in issues:
                lines.append("%s %s — %s" % (status_prefix(issue.get("status")), translate_text(issue.get("title", "")), translate_text(issue.get("summary", ""))))
        else:
            lines.append(L("Brak ostrzeżeń i błędów.", "No warnings or errors."))
        self.session.open(E2DoctorTextScreen, L("Historia — %s", "History — %s") % snapshot.get("timestamp", ""), "\n".join(lines))
    def confirm_clear(self):
        if self.history:
            self.session.openWithCallback(self.clear_history, MessageBox, L("Usunąć zapisaną historię skanów E2 Doctor?", "Delete the saved E2 Doctor scan history?"), MessageBox.TYPE_YESNO)
    def clear_history(self, answer):
        if answer:
            try:
                save_json_file(E2D_HISTORY_FILE, [])
                self.session.openWithCallback(lambda *args: self.close(), MessageBox, L("Historia została usunięta.", "History has been deleted."), MessageBox.TYPE_INFO, timeout=6)
            except Exception as error:
                self.session.open(MessageBox, L("Nie udało się usunąć historii:\n%s", "History could not be deleted:\n%s") % error, MessageBox.TYPE_ERROR)


class E2DoctorIPKBrowser(Screen):
    skin = premium_results_skin("E2DoctorIPKBrowser")
    def __init__(self, session):
        Screen.__init__(self, session)
        self.paths = []
        for name in ("header_bg", "accent", "footer_bg"):
            self[name] = Label("")
        self["title"] = Label(L("E2 Safe Installer — analiza IPK", "E2 Safe Installer — IPK analysis"))
        self["status"] = Label(L("Analiza bez instalowania i bez modyfikowania systemu", "Analysis without installation or system modification"))
        self["list"] = E2DoctorV2ResultList([])
        self["key_red"] = StaticText(L("Wróć", "Back"))
        self["key_green"] = StaticText(L("Analizuj", "Analyse"))
        self["key_yellow"] = StaticText(L("Odśwież", "Refresh"))
        self["key_blue"] = StaticText(L("Wyjście", "Exit"))
        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "cancel": self.close, "red": self.close, "blue": self.close,
            "ok": self.analyze_selected, "green": self.analyze_selected, "yellow": self.refresh,
        }, -1)
        self.refresh()
    def refresh(self):
        self.paths = find_ipk_files()
        rows = []
        for path in self.paths:
            try:
                summary = "%s | %s" % (format_bytes(os.path.getsize(path)), os.path.dirname(path))
            except Exception:
                summary = os.path.dirname(path)
            rows.append((STATUS_INFO, os.path.basename(path), summary))
        if not rows:
            rows.append((STATUS_INFO, L("Nie znaleziono paczek IPK", "No IPK packages found"), L("Skopiuj plik IPK do /tmp lub na nośnik w /media.", "Copy an IPK file to /tmp or a device mounted in /media.")))
        self["list"].setList(rows)
        self["status"].setText(L("Znalezione paczki: %d | E2 Doctor nie instaluje wskazanego pliku", "Packages found: %d | E2 Doctor does not install the selected file") % len(self.paths))
    def analyze_selected(self):
        index = self["list"].getSelectedIndex()
        if index < 0 or index >= len(self.paths):
            return
        path = self.paths[index]
        try:
            self.session.open(E2DoctorTextScreen, L("Analiza — %s", "Analysis — %s") % os.path.basename(path), analyze_ipk(path), "E2 Safe Installer")
        except Exception as error:
            self.session.open(MessageBox, L("Nie udało się przeanalizować paczki:\n%s", "The package could not be analysed:\n%s") % error, MessageBox.TYPE_ERROR)


# Localise the existing tools screen while preserving all tested action logic.
_OldToolsScreen23 = E2DoctorTools
class E2DoctorTools(_OldToolsScreen23):
    skin = premium_results_skin("E2DoctorTools")
    def __init__(self, session):
        _OldToolsScreen23.__init__(self, session)
        self["title"].setText(L("Bezpieczne narzędzia E2 Doctor", "E2 Doctor safe tools"))
        self["status"].setText(L("Bezpieczne narzędzia ręczne | każda zmiana wymaga potwierdzenia", "Manual safe tools | every change requires confirmation"))
        self["key_red"].setText(L("Wróć", "Back"))
        self["key_green"].setText(L("Wykonaj", "Run"))
        self["key_yellow"].setText(L("Opis", "Description"))
        self["key_blue"].setText(L("Wyjście", "Exit"))
        self["list"].setList([(STATUS_INFO, translate_text(title), translate_text(subtitle)) for title, _action, subtitle in self.tool_entries])


# Update screen: fixed labels and dynamic status translation.
_old_update_init_23 = E2DoctorUpdateScreen.__init__
_old_update_set_status_23 = E2DoctorUpdateScreen._set_status

def _update_init_23(self, session):
    _old_update_init_23(self, session)
    self["title"].setText(L("Aktualizacja E2 Doctor z GitHub", "Update E2 Doctor from GitHub"))
    self["subtitle"].setText(L("Bezpieczne sprawdzanie wersji, weryfikacja SHA-256 i instalacja IPK", "Safe version check, SHA-256 verification and IPK installation"))
    self["source"].setText(L("Źródło: github.com/OliOli2013/E2-Doctor-Plugin", "Source: github.com/OliOli2013/E2-Doctor-Plugin"))
    self["local_title"].setText(L("ZAINSTALOWANA WERSJA", "INSTALLED VERSION"))
    self["remote_title"].setText(L("WERSJA NA GITHUB", "GITHUB VERSION"))
    self["status_title"].setText(L("STATUS AKTUALIZACJI", "UPDATE STATUS"))
    self["notes_title"].setText(L("Informacje o wydaniu", "Release information"))
    self["key_red"].setText(L("Wróć", "Back"))
    self["key_green"].setText(L("Sprawdź", "Check"))
    self["key_yellow"].setText(L("Sprawdź ponownie", "Check again"))
    self["key_blue"].setText(L("Wyjście", "Exit"))
    self["remote_version"].setText(L("sprawdzanie...", "checking..."))
    self["status"].setText(translate_text(self["status"].getText()))
    self["notes"].setText(translate_text(self["notes"].getText()))


def _update_set_status_23(self, text, notes=None):
    return _old_update_set_status_23(self, translate_text(text), translate_text(notes) if notes is not None else None)


E2DoctorUpdateScreen.__init__ = _update_init_23
E2DoctorUpdateScreen._set_status = _update_set_status_23


# Dynamic plug-in-menu description follows the active language.
def Plugins(**kwargs):
    description = L("Centrum diagnostyki i bezpiecznej naprawy Enigma2", "Enigma2 diagnostics and safe repair centre")
    descriptors = [
        PluginDescriptor(name="E2 Doctor", description=description, where=PluginDescriptor.WHERE_PLUGINMENU, icon="plugin.png", fnc=main),
        PluginDescriptor(name="E2 Doctor", description=description, where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=main),
    ]
    try:
        descriptors.append(PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=session_start))
    except Exception:
        pass
    return descriptors

# Additional English phrases used by the safe-tools screen and updater.
_EXACT_EN.update({
    "Bezpiecznie oczyść pamięć flash": "Safely clean flash",
    "Tylko stare crashlogi, archiwa OPKG i zrzuty pamięci": "Only old crashlogs, OPKG archives and memory dumps",
    "Bezpiecznie odśwież pamięć RAM": "Safely refresh RAM",
    "Zwalnia cache bez kończenia procesów": "Releases cache without terminating processes",
    "Pokaż diagnostykę nośników": "Show storage diagnostics",
    "Bez formatowania i bez naprawy aktywnego systemu plików": "No formatting and no repair of an active filesystem",
    "Przeładuj listę kanałów": "Reload channel list",
    "Bez usuwania list i ustawień tunera": "Without removing lists or tuner settings",
    "Usuń nieaktywną blokadę OPKG": "Remove inactive OPKG lock",
    "Tylko gdy OPKG nie jest uruchomiony": "Only when OPKG is not running",
    "Usuń stare crashlogi": "Remove old crashlogs",
    "Pozostawia 3 najnowsze pliki": "Keeps the three newest files",
    "Uruchom ponownie OSCam": "Restart OSCam",
    "Wyszukuje dostępny skrypt startowy": "Finds an available startup script",
    "Pokaż procesy zużywające RAM": "Show RAM-consuming processes",
    "Diagnostyka bez kończenia procesów": "Diagnostics without terminating processes",
    "Znajdź największe pliki": "Find the largest files",
    "Analiza bez automatycznego usuwania": "Analysis without automatic deletion",
    "Utwórz raport awaryjny": "Create emergency report",
    "Działa również z polecenia e2doctor-report": "Also available through the e2doctor-report command",
    "Cofnij ostatnią bezpieczną zmianę": "Undo the last safe change",
    "Przywraca backup lub wyłączoną wtyczkę": "Restores a backup or disabled plug-in",
    "Ustawienia E2 Doctor": "E2 Doctor settings",
    "Monitoring, historia i automatyczny skan": "Monitoring, history and automatic scanning",
    "Uruchom ponownie GUI": "Restart GUI",
    "Wymaga potwierdzenia": "Requires confirmation",
    "Łączenie z GitHub...": "Connecting to GitHub...",
    "Trwa pobieranie pliku update.json...": "Downloading update.json...",
    "Pobieranie i sprawdzanie pliku update.json.": "Downloading and checking update.json.",
    "DOSTĘPNA NOWA WERSJA": "NEW VERSION AVAILABLE",
    "MASZ NAJNOWSZĄ WERSJĘ": "YOU HAVE THE LATEST VERSION",
    "BŁĄD POŁĄCZENIA": "CONNECTION ERROR",
    "POBIERANIE PACZKI": "DOWNLOADING PACKAGE",
    "BŁĄD POBIERANIA": "DOWNLOAD ERROR",
    "AKTUALIZACJA ODRZUCONA": "UPDATE REJECTED",
    "PACZKA ZWERYFIKOWANA": "PACKAGE VERIFIED",
    "INSTALOWANIE AKTUALIZACJI": "INSTALLING UPDATE",
    "BŁĄD INSTALACJI": "INSTALLATION ERROR",
    "AKTUALIZACJA ZAINSTALOWANA": "UPDATE INSTALLED",
    "Pobierz i zainstaluj": "Download and install",
    "Sprawdź ponownie": "Check again",
    "Spróbuj ponownie": "Try again",
    "Pobieranie...": "Downloading...",
    "Instalowanie...": "Installing...",
    "Gotowe": "Done",
    "sprawdzanie...": "checking...",
})


def _translate_component_text_23(screen, name):
    try:
        component = screen[name]
        getter = getattr(component, "getText", None)
        if getter is not None:
            component.setText(translate_text(getter()))
    except Exception:
        pass


# Replace the earlier updater initialiser with a guarded variant.
_old_update_init_guarded_23 = _old_update_init_23

def _update_init_guarded_23(self, session):
    _old_update_init_guarded_23(self, session)
    self["title"].setText(L("Aktualizacja E2 Doctor z GitHub", "Update E2 Doctor from GitHub"))
    self["subtitle"].setText(L("Bezpieczne sprawdzanie wersji, weryfikacja SHA-256 i instalacja IPK", "Safe version check, SHA-256 verification and IPK installation"))
    self["source"].setText(L("Źródło: github.com/OliOli2013/E2-Doctor-Plugin", "Source: github.com/OliOli2013/E2-Doctor-Plugin"))
    self["local_title"].setText(L("ZAINSTALOWANA WERSJA", "INSTALLED VERSION"))
    self["remote_title"].setText(L("WERSJA NA GITHUB", "GITHUB VERSION"))
    self["status_title"].setText(L("STATUS AKTUALIZACJI", "UPDATE STATUS"))
    self["notes_title"].setText(L("Informacje o wydaniu", "Release information"))
    self["key_red"].setText(L("Wróć", "Back"))
    self["key_green"].setText(L("Sprawdź", "Check"))
    self["key_yellow"].setText(L("Sprawdź ponownie", "Check again"))
    self["key_blue"].setText(L("Wyjście", "Exit"))
    _translate_component_text_23(self, "remote_version")
    _translate_component_text_23(self, "status")
    _translate_component_text_23(self, "notes")

E2DoctorUpdateScreen.__init__ = _update_init_guarded_23


def _wrap_update_method_23(method_name):
    original = getattr(E2DoctorUpdateScreen, method_name, None)
    if original is None:
        return
    def wrapped(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        for component_name in ("key_green", "key_yellow", "remote_version", "status", "notes"):
            _translate_component_text_23(self, component_name)
        return result
    setattr(E2DoctorUpdateScreen, method_name, wrapped)

for _method_name in ("check_update", "green_action", "start_download", "_download_finished", "_install_confirmed", "start_install", "_install_finished"):
    _wrap_update_method_23(_method_name)

_EXACT_EN.update({
    "ZNAKOMITY": "EXCELLENT",
    "DOBRY": "GOOD",
    "WYMAGA UWAGI": "NEEDS ATTENTION",
    "KRYTYCZNY": "CRITICAL",
    "Bezpieczeństwo aktualizacji:": "Update security:",
    "• paczka jest pobierana wyłącznie przez HTTPS z GitHub,": "• the package is downloaded only over HTTPS from GitHub,",
    "• przed instalacją sprawdzana jest suma SHA-256,": "• the SHA-256 checksum is verified before installation,",
    "• instalacja wymaga potwierdzenia użytkownika,": "• installation requires user confirmation,",
    "• po instalacji proponowany jest restart GUI.": "• a GUI restart is offered after installation.",
    "Trwa pobieranie aktualizacji z GitHub. Nie wyłączaj dekodera.": "The update is being downloaded from GitHub. Do not switch off the receiver.",
    "Paczka została pobrana i poprawnie zweryfikowana sumą SHA-256.": "The package was downloaded and successfully verified with SHA-256.",
    "OPKG instaluje zweryfikowaną paczkę. Nie wyłączaj dekodera.": "OPKG is installing the verified package. Do not switch off the receiver.",
    "Nowa wersja E2 Doctor została zainstalowana poprawnie. Wykonaj restart GUI, aby wczytać nowe pliki.": "The new E2 Doctor version was installed successfully. Restart the GUI to load the new files.",
})
_LINE_REPLACEMENTS_EN.extend([
    ("Data wydania:", "Release date:"),
    ("Nie udało się sprawdzić aktualizacji.", "The update check failed."),
    ("Sprawdź internet, DNS, prawidłową datę systemową oraz dostęp do GitHub.", "Check the internet connection, DNS, system date and access to GitHub."),
    ("Nie udało się pobrać paczki.", "The package could not be downloaded."),
    ("Kod:", "Code:"),
    ("Oczekiwana:", "Expected:"),
    ("Pobrana:", "Downloaded:"),
    ("OPKG zakończył pracę kodem", "OPKG finished with code"),
])

_old_fetch_update_manifest_23 = fetch_update_manifest

def fetch_update_manifest(timeout=10):
    manifest = _old_fetch_update_manifest_23(timeout)
    if is_english() and isinstance(manifest.get("notes_en"), list):
        manifest = dict(manifest)
        manifest["notes"] = manifest.get("notes_en")
    return manifest
