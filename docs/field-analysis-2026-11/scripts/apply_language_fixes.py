#!/usr/bin/env python3
"""Apply reviewed catalogue language fixes to a repo checkout, line-exact (YAML layout kept).
Each fix names file, domain, rss_url, the language it must currently have, and the new one.
An entry is the block from its '- name:' line to the next; it must hold the domain line and
(when given) the rss_url line, and exactly one 'language: <old>' line. Refuses otherwise.
Usage: python3 -I apply_language_fixes.py REPO FIXES.json"""
import json, sys
repo, fixes = sys.argv[1], json.load(open(sys.argv[2]))
by_file = {}
for f in fixes:
    by_file.setdefault(f['file'], []).append(f)
for path, fs in by_file.items():
    lines = open(f'{repo}/{path}').read().split('\n')
    starts = [i for i, l in enumerate(lines) if l.startswith('- ')] + [len(lines)]
    for f in fs:
        hits = []
        for a, b in zip(starts, starts[1:]):
            block = lines[a:b]
            if f'  domain: {f["domain"]}' in block or f'- domain: {f["domain"]}' in block:
                if f.get('rss_url') and not any(l.strip() in (f'rss_url: {f["rss_url"]}', f"rss_url: '{f['rss_url']}'") for l in block):
                    continue
                hits.append((a, b))
        if len(hits) != 1:
            sys.exit(f'{path}: {f["domain"]}: {len(hits)} matching entries, refusing')
        a, b = hits[0]
        idx = [i for i in range(a, b) if lines[i].strip() == f'language: {f["old"]}']
        if len(idx) != 1:
            sys.exit(f'{path}: {f["domain"]}: expected one "language: {f["old"]}" line, found {len(idx)}')
        lines[idx[0]] = lines[idx[0]].replace(f'language: {f["old"]}', f'language: {f["new"]}')
        print(f'{path}:{idx[0] + 1} {f["domain"]}: {f["old"]} -> {f["new"]}')
    open(f'{repo}/{path}', 'w').write('\n'.join(lines))
