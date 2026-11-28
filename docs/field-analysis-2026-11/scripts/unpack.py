#!/usr/bin/env python3
"""Unpack Open Omniscience field/diagnostic archives into one folder per archive.

Read-only on the source folder. Byte-split sets (fixed-size parts where only part 1
starts with a zip header) are concatenated in a temp file first; independent
zip parts are extracted one by one. Loose .json files are copied.
Usage: python3 -I unpack.py SRC_ROOT DEST_ROOT
"""
import os, re, shutil, sys, zipfile, tempfile
from collections import defaultdict

src_root, dest_root = sys.argv[1], sys.argv[2]
PART = re.compile(r'^(?P<base>.+?)-part-(?P<n>\d+)-of-(?P<t>\d+)\.zip$')


def safe_extract(zf, dest):
    for m in zf.infolist():
        dest = os.path.abspath(dest); p = os.path.normpath(os.path.join(dest, m.filename))
        if not p.startswith(os.path.abspath(dest) + os.sep) and p != os.path.abspath(dest):
            raise RuntimeError(f'unsafe path {m.filename}')
        if m.is_dir():
            os.makedirs(p, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with zf.open(m) as r, open(p, 'wb') as w:
            shutil.copyfileobj(r, w)


def is_zip_header(path):
    with open(path, 'rb') as f:
        return f.read(4) == b'PK\x03\x04'

for inst in sorted(os.listdir(src_root)):
    sdir = os.path.join(src_root, inst)
    ddir = os.path.join(dest_root, inst)
    os.makedirs(ddir, exist_ok=True)
    groups = defaultdict(list)
    singles = []
    for fn in sorted(os.listdir(sdir)):
        m = PART.match(fn)
        if m:
            groups[(m['base'], int(m['t']))].append((int(m['n']), fn))
        else:
            singles.append(fn)
    for (base, total), parts in sorted(groups.items()):
        parts.sort()
        nums = [n for n, _ in parts]
        missing = sorted(set(range(1, total + 1)) - set(nums))
        if missing:
            print(f'{inst}: {base} MISSING parts {missing}')
        all_headers = all(is_zip_header(os.path.join(sdir, f)) for _, f in parts)
        if all_headers:
            for n, f in parts:
                out = os.path.join(ddir, f[:-4])
                os.makedirs(out, exist_ok=True)
                with zipfile.ZipFile(os.path.join(sdir, f)) as z:
                    safe_extract(z, out)
            print(f'{inst}: {base}: {len(parts)} independent zips')
        else:
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False, dir=dest_root) as tmp:
                for _, f in parts:
                    with open(os.path.join(sdir, f), 'rb') as r:
                        shutil.copyfileobj(r, tmp)
                tmpname = tmp.name
            out = os.path.join(ddir, base)
            os.makedirs(out, exist_ok=True)
            try:
                with zipfile.ZipFile(tmpname) as z:
                    safe_extract(z, out)
                print(f'{inst}: {base}: {len(parts)} byte-split parts joined')
            except Exception as e:
                print(f'{inst}: {base}: JOIN FAILED {e}')
            finally:
                os.unlink(tmpname)
    for fn in singles:
        sp = os.path.join(sdir, fn)
        if fn.endswith('.zip'):
            out = os.path.join(ddir, fn[:-4])
            os.makedirs(out, exist_ok=True)
            try:
                with zipfile.ZipFile(sp) as z:
                    safe_extract(z, out)
            except Exception as e:
                print(f'{inst}: {fn}: FAILED {e}')
        else:
            shutil.copy2(sp, os.path.join(ddir, fn))
    print(f'{inst}: {len(singles)} single files')
