#!/usr/bin/env python3
"""How a freshness rule would classify the instance-qualified candidates (candidates.json):
age = export generated_at minus evidence.last_article (newest PUBLISHER date of a stored
article; quarantined included). Prints, per instance and threshold, how many candidates a
'newest article within N days' rule would keep, and how many are undated.
Also counts candidates with < 5 stored articles (qualification judges from 1, TRIAL_MIN_ARTICLES).
Usage: python3 -I freshness_rule.py DATA_ROOT INSTANCES_JSON"""
import glob, json, sys
from datetime import datetime
root, inst = sys.argv[1], json.load(open(sys.argv[2]))
print('| instance | candidates | undated | <=30 d | <=90 d | <=180 d | <=365 d | >365 d | <5 articles stored |')
print('|---|---:|---:|---:|---:|---:|---:|---:|---:|')
for folder, label in inst.items():
    d = json.load(open(glob.glob(f'{root}/{folder}/*-candidate-sources/candidates.json')[0]))
    g = datetime.fromisoformat(d['generated_at'].replace('Z', '+00:00')).replace(tzinfo=None)
    ages = []; und = 0; few = 0
    for c in d['candidates']:
        e = c['evidence']; few += (e.get('articles_stored') or 0) < 5
        if not e.get('last_article'):
            und += 1; continue
        ages.append((g - datetime.fromisoformat(e['last_article'].replace('Z', '+00:00')).replace(tzinfo=None)).days)
    n = len(d['candidates'])
    f = lambda k: sum(a <= k for a in ages)
    print(f'| {label} | {n} | {und} | {f(30)} | {f(90)} | {f(180)} | {f(365)} | {sum(a > 365 for a in ages)} | {few} |')
