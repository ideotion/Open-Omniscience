#!/usr/bin/env python3
"""Index the shipped source catalogue on a repo checkout by (domain, feed_key).

feed_key is computed (and masked as exports write it: shown_feed_key, R734) with the repo's own src/database/feed_key.py (the one
implementation the app uses), imported from REPO.
Writes OUT (JSON list): one row per catalogue entry with its file and position.
Usage: python3 -I catalogue_index.py REPO OUT.json
"""
import json, sys
repo, out = sys.argv[1:3]
sys.path.insert(0, repo)
import yaml  # noqa: E402
from src.database.feed_key import feed_key, shown_feed_key  # noqa: E402

FILES = ['configs/sources.yml', 'configs/sources_spectrum.yml', 'configs/academic_sources.yml',
         'configs/official_sources.yml', 'configs/markets_sources.yml', 'configs/legal_sources.yml',
         'configs/legal_sources_generated.yml']
rows = []
for f in FILES:
    d = yaml.safe_load(open(f'{repo}/{f}'))
    for i, e in enumerate(d.get('sources') or []):
        if not isinstance(e, dict):
            continue
        rows.append({'file': f, 'index': i, 'name': e.get('name'), 'domain': (e.get('domain') or '').lower(),
                     'rss_url': e.get('rss_url'), 'feed_key': shown_feed_key(feed_key(e.get('rss_url'))),
                     'feed_key_raw': feed_key(e.get('rss_url')),
                     'enabled': e.get('enabled', True), 'source_type': e.get('source_type'),
                     'country': e.get('country'), 'language': e.get('language'),
                     'reliability_score': e.get('reliability_score'), 'priority': e.get('priority'),
                     'tags': e.get('tags')})
json.dump(rows, open(out, 'w'), ensure_ascii=False)
from collections import Counter
print(Counter(r['file'] for r in rows))
keys = Counter((r['domain'], r['feed_key']) for r in rows)
print('entries', len(rows), 'unique (domain,feed_key)', len(keys), 'dup keys', sum(1 for v in keys.values() if v > 1))
