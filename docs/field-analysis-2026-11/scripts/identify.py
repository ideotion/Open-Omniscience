#!/usr/bin/env python3
"""Print identity facts (generation time, platform, CPU, RAM, app version, git head, corpus size,
instance id where exported) for every diagnostics/field export under the given roots.
Prints machine facts for LOCAL matching only; the report shows only instance labels.
Usage: python3 -I identify.py ROOT [ROOT...]"""
import glob, json, os, sys
def j(p):
    try: return json.load(open(p))
    except Exception: return None
for root in sys.argv[1:]:
    for inst in sorted(os.listdir(root)):
        d = os.path.join(root, inst)
        if not os.path.isdir(d): continue
        for m in sorted(glob.glob(d + '/*/manifest.json')):
            x = j(m) or {}
            sub = os.path.basename(os.path.dirname(m))
            if 'members' in x or x.get('kind') in ('all-diagnostics', 'diagnostics'):
                mach = x.get('machine') or {}
                b = (mach.get('build') or {}); code = b.get('code') or {}
                hw = (x.get('run') or {}).get('hardware') or {}
                corp = (x.get('run') or {}).get('corpus') or {}
                print(f"{root[-12:]}/{inst} {sub[:40]:40s} gen={x.get('generated_at')} ver={b.get('app_version') or x.get('app_version')} head={(code.get('git_head') or '')[:9]} plat={x.get('platform')} cpu={hw.get('cpu_model')} ram={hw.get('ram_total_bytes')} articles={corp.get('articles')}")
            elif x.get('schema', '').startswith('oo-source-quality') or 'corpus_totals' in x:
                print(f"{root[-12:]}/{inst} {sub[:40]:40s} gen={x.get('generated_at')} schema={x.get('schema')} sources={x['corpus_totals'].get('sources')} articles={x['corpus_totals'].get('articles')}")
            elif 'instance' in x:
                print(f"{root[-12:]}/{inst} {sub[:40]:40s} gen={x.get('generated_at')} instance={x.get('instance')} ")
