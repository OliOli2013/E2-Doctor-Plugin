#!/usr/bin/env python3
"""Reproducible IPK builder. No receiver commands are executed."""
import ast
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import re

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'src'
init=(SRC/'usr/lib/enigma2/python/Plugins/Extensions/E2Doctor/__init__.py').read_text()
version=re.search(r'PLUGIN_VERSION = "([^"]+)"',init)[1]
build=re.search(r'PLUGIN_BUILD = "([^"]+)"',init)[1]
for path in list(SRC.rglob('*.py'))+[SRC/'usr/bin/e2doctor-report']:
    ast.parse(path.read_text(),filename=str(path),feature_version=(3,5))
files={}
for path in sorted(SRC.rglob('*')):
    if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.pyo'):
        files[path.relative_to(SRC).as_posix()]=(path.read_bytes(),0o755 if path.name=='e2doctor-report' else 0o644)
control=(ROOT/'packaging/control/control').read_text()
control=re.sub(r'^Version:.*$', 'Version: '+version,control,flags=re.M)
control+='Installed-Size: %d\n'%((sum(len(x[0]) for x in files.values())+1023)//1024)
checks=''.join(hashlib.md5(data).hexdigest()+'  '+name+'\n' for name,(data,mode) in files.items())
controls={'control':(control.encode(),0o644),'md5sums':(checks.encode(),0o644),'postinst':((ROOT/'packaging/control/postinst').read_bytes(),0o755)}

def archive(files):
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.USTAR_FORMAT) as tar:
        for name,(data,mode) in files.items():
            entry=tarfile.TarInfo('./'+name);entry.size=len(data);entry.mode=mode;entry.uid=entry.gid=0;entry.mtime=0
            tar.addfile(entry,io.BytesIO(data))
    return gzip.compress(raw.getvalue(),mtime=0)

def ar_member(name,data):
    header=('%-16s%-12s%-6s%-6s%-8s%-10s`\n'%(name+'/',0,0,0,'100644',len(data))).encode('ascii')
    assert len(header)==60
    return header+data+(b'\n' if len(data)%2 else b'')

package=b'!<arch>\n'+b''.join(ar_member(name,data) for name,data in [('debian-binary',b'2.0\n'),('control.tar.gz',archive(controls)),('data.tar.gz',archive(files))])
filename='enigma2-plugin-extensions-e2doctor_%s_all.ipk'%version
(ROOT/'releases').mkdir(exist_ok=True)
(ROOT/'releases'/filename).write_bytes(package)
manifest=json.loads((ROOT/'update.json').read_text())
manifest.update(version=version,build=build,release_date='2026-09-10',download_url='https://raw.githubusercontent.com/OliOli2013/E2-Doctor-Plugin/main/releases/'+filename,sha256=hashlib.sha256(package).hexdigest())
(ROOT/'update.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
paths=['releases/'+filename,'installer.sh','update.json']
(ROOT/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()+'  '+path+'\n' for path in paths))
print(filename+'\nSHA256: '+manifest['sha256']+'\nSize: '+str(len(package)))
