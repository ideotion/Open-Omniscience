#!/usr/bin/env python3
"""Phase-0 inventory per instance: export kinds and generation times, app version, build
commit and its distance from a repo checkout's HEAD, corpus totals, row counts of the field
files, member outcomes of each diagnostics bundle, and the stored-date range of the per-source
random articles (created_at = when the instance stored it).
Usage: python3 -I inventory.py DATA_ROOT INSTANCES_JSON REPO"""
import glob, json, os, subprocess, sys
from collections import Counter
root, inst, repo = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]
def behind(h):
    try:
        n = subprocess.run(['git', '-C', repo, 'rev-list', '--count', f'{h}..HEAD'], capture_output=True, text=True).stdout.strip()
        d = subprocess.run(['git', '-C', repo, 'log', '-1', '--format=%cs', h], capture_output=True, text=True).stdout.strip()
        return d, n
    except Exception:
        return '?', '?'
def lines(p):
    return sum(1 for _ in open(p)) if os.path.exists(p) else 'absent'
for folder, label in inst.items():
    b = f'{root}/{folder}'
    print(f'## {label}')
    for m in sorted(glob.glob(b + '/*/manifest.json')):
        x = json.load(open(m))
        if 'members' in x:
            code = (x['machine']['build'].get('code') or {}); h = code.get('git_head') or ''
            d, n = behind(h) if h else ('?', '?')
            oc = Counter(mm.get('outcome') for mm in x['members'])
            os_ = 'Windows 11' if x['platform'].startswith('Windows') else 'Linux'
            corp = x['run'].get('corpus') or {}
            print(f"- diagnostics bundle generated {x['generated_at']}: {os_}, Python {x['python']}, app {x['machine']['build'].get('app_version')}, "
                  f"build {h[:9]} ({d}, {n} commits behind main), corpus articles {corp.get('articles', 'not read: ' + str(corp.get('reason', ''))[:60])}, "
                  f"members {dict(oc)}; not complete: {[mm['file'] + '=' + mm['outcome'] for mm in x['members'] if mm.get('outcome') != 'ok']}")
    sq = (sorted(glob.glob(b + '/*-source-quality')) or [None])[0]
    if sq:
        t = json.load(open(sq + '/manifest.json'))
        ct = t['corpus_totals']
        print(f"- source-quality export generated {t['generated_at']}: sources {ct['sources']}, with articles {ct['sources_with_articles']}, "
              f"articles {ct['articles']}, ratio-audited {ct['articles_ratio_audited']}, keyword-indexed {ct['pct_articles_keyword_indexed']}%, "
              f"sample_articles {lines(sq + '/sample_articles.jsonl')}, keyword_outliers {lines(sq + '/keyword_outliers.jsonl')}")
    samples = glob.glob(b + '/*source-samples-*/samples/*.json')
    created = sorted(json.load(open(f)).get('article', {}).get('created_at') or '' for f in samples)
    created = [c for c in created if c]
    print(f"- source-samples: {len(glob.glob(b + '/*source-samples-*'))} zips, {len(samples)} sampled sources; stored dates of the sampled articles {created[0][:10] if created else '-'} .. {created[-1][:10] if created else '-'}")
    for f in glob.glob(b + '/*-candidate-sources/candidates.json'):
        c = json.load(open(f)); print(f"- candidate-sources: {len(c['candidates'])} candidates, left out {c['left_out']}")
    for f in glob.glob(b + '/*source-qualification.json'):
        q = json.load(open(f)); print(f"- source-qualification: split {q['split']}, basis {{k: v for k, v in q['basis'].items() if isinstance(v, int)}}".replace('{k: v for k, v in q[\'basis\'].items() if isinstance(v, int)}', str({k: v for k, v in q['basis'].items() if isinstance(v, int) and not isinstance(v, bool)})))
    others = sorted(os.path.basename(p) for p in glob.glob(b + '/*p8000*.json'))
    if others:
        print(f"- other field files: {', '.join(o.split('-p8000-')[1] for o in others)}")
