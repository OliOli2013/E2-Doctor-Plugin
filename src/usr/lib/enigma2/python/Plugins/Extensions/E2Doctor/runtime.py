# -*- coding: utf-8 -*-
"""Bounded I/O helpers; no Enigma2 dependencies. Python 3.5+."""
import hashlib
import json
import os
import re
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import tarfile
import io
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

MAX_IPK = 32 * 1024 * 1024
ALLOWED_HOSTS = {'raw.githubusercontent.com', 'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}


def atomic_write(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix='.e2doctor-', dir=parent)
    try:
        if os.path.exists(path):
            info = os.stat(path)
            os.fchmod(fd, stat.S_IMODE(info.st_mode))
            try:
                os.fchown(fd, info.st_uid, info.st_gid)
            except PermissionError:
                pass
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            fd = None
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_command(command, timeout=8):
    # Temporary files avoid unbounded PIPE buffering from verbose commands.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = None
        try:
            process = subprocess.Popen(command, shell=isinstance(command, str), stdout=out, stderr=err,
                                       start_new_session=True, close_fds=True)
            process.wait(timeout=timeout)
            code = process.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.wait()
            return 124, '', 'Timeout / przekroczono limit czasu'
        except Exception as error:
            return 255, '', str(error)
        values = []
        for handle in (out, err):
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 256 * 1024))
            values.append(handle.read().decode('utf-8', 'replace').strip())
        return code, values[0], values[1]


def broken_package_status(value):
    parts = value.split()
    if len(parts) != 3:
        return True
    want, flag, state = parts
    return flag != 'ok' or state not in ('installed', 'not-installed', 'config-files') or (want == 'install' and state != 'installed')


def installed_names(packages):
    names = set()
    for item in packages:
        if item.get('status', '').split()[-1:] != ['installed']:
            continue
        if item.get('package'):
            names.add(item['package'])
        for provided in item.get('provides', '').split(','):
            name = re.sub(r'\([^)]*\)', '', provided).strip()
            if name:
                names.add(name)
    return names


def read_ar_members(path):
    if os.path.getsize(path) > MAX_IPK:
        raise ValueError('IPK exceeds 32 MiB analysis limit')
    result = {}
    with open(path, 'rb') as stream:
        if stream.read(8) != b'!<arch>\n':
            raise ValueError('Invalid IPK/ar header')
        while True:
            header = stream.read(60)
            if not header:
                break
            if len(header) != 60 or header[58:] != b'`\n':
                raise ValueError('Truncated IPK member header')
            size = int(header[48:58].strip())
            if size < 0 or size > MAX_IPK:
                raise ValueError('Invalid IPK member size')
            name = header[:16].decode('ascii').strip().rstrip('/')
            if name in result:
                raise ValueError('Duplicate IPK member')
            data = stream.read(size)
            if len(data) != size or (size % 2 and len(stream.read(1)) != 1):
                raise ValueError('Truncated IPK member')
            result[name] = data
            if len(result) > 8:
                raise ValueError('Too many IPK members')
    if result.get('debian-binary') != b'2.0\n':
        raise ValueError('Unsupported IPK format')
    return result


def tar_members(archive):
    members = []
    total = 0
    for member in archive:
        total += member.size
        if len(members) >= 10000 or total > 128 * 1024 * 1024:
            raise ValueError('Archive exceeds analysis limit (10000 entries / 128 MiB)')
        if member.name.startswith('/') or '..' in member.name.split('/'):
            raise ValueError('Unsafe archive path: ' + member.name)
        if member.isdev() or member.isfifo():
            raise ValueError('Unsupported special file: ' + member.name)
        if member.islnk() or member.issym():
            if member.linkname.startswith('/') or '..' in member.linkname.split('/'):
                raise ValueError('External archive link: ' + member.name)
        members.append(member)
    return members


def valid_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme == 'https' and parsed.hostname in ALLOWED_HOSTS and parsed.port in (None, 443) and not parsed.username and not parsed.password
    except (ValueError, TypeError):
        return False


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not valid_url(newurl):
            raise ValueError('Unsafe update redirect')
        return HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def download(url, path, limit=MAX_IPK):
    if not valid_url(url):
        raise ValueError('Invalid update URL')
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), SafeRedirect())
    req = Request(url, headers={'User-Agent': 'E2Doctor/2.4.1', 'Cache-Control': 'no-cache'})
    with opener.open(req, timeout=15) as response, open(path, 'wb') as output:
        total = 0
        while True:
            block = response.read(65536)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise ValueError('Download exceeds size limit')
            output.write(block)


def verify_ipk(path, manifest):
    if os.path.islink(path):
        raise ValueError('IPK must not be a symlink')
    with open(path, 'rb') as stream:
        actual = hashlib.sha256(stream.read(MAX_IPK + 1)).hexdigest()
    if actual != str(manifest.get('sha256', '')).strip().lower():
        raise ValueError('SHA-256 mismatch')
    members = read_ar_members(path)
    control_name = next((x for x in members if x.startswith('control.tar')), None)
    if control_name is None or not any(x.startswith('data.tar') for x in members):
        raise ValueError('Missing IPK archives')
    with tarfile.open(fileobj=io.BytesIO(members[control_name]), mode='r:*') as archive:
        controls = [x for x in tar_members(archive) if x.name in ('control', './control') and x.isfile()]
        if len(controls) != 1 or controls[0].size > 65536:
            raise ValueError('Invalid package control')
        fields = dict(line.split(':', 1) for line in archive.extractfile(controls[0]).read().decode('utf-8').splitlines() if ':' in line and not line.startswith(' '))
    if fields.get('Package', '').strip() != 'enigma2-plugin-extensions-e2doctor':
        raise ValueError('Wrong update package name')
    if fields.get('Version', '').strip() != str(manifest['version']):
        raise ValueError('Package and manifest version mismatch')
    if fields.get('Architecture', '').strip() != 'all':
        raise ValueError('Unexpected update architecture')
    return True


def redact(text):
    text = re.sub(r'(?i)(https?://)[^/\s:@]+:[^/\s@]+@', r'\1[REDACTED]@', text)
    text = re.sub(r'(?i)((?:password|passwd|token|api_key|apikey|secret|authorization)\s*[=:]\s*)[^\s&;,]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(https?://[^/\s]+/(?:live|movie|series)/)[^/\s]+/[^/\s]+/', r'\1[REDACTED]/[REDACTED]/', text)
    return text


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'network':
            context = ssl.create_default_context()
            with socket.create_connection(('github.com', 443), timeout=4) as raw:
                with context.wrap_socket(raw, server_hostname='github.com') as connection:
                    print('github.com:443 / ' + connection.version() + ' / certificate verified')
        elif sys.argv[1] == 'download':
            download(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else MAX_IPK)
        else:
            raise ValueError('Unknown command')
    except Exception as error:
        sys.stderr.write(str(error) + '\n')
        sys.exit(1)
