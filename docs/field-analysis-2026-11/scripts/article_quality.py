#!/usr/bin/env python3
"""Article-quality measures over the source-samples export: ONE seeded-random stored
article per source with >=1 article (the export's own pick, see its manifest), full text.

This is an unbiased per-SOURCE sample (each source weighs 1), not a per-article sample.
For every article it computes metadata-only and text-only flags (no network, no model):
  words<50 / words<100 (app's word_count = len(text.split()) at ingest)
  stub phrase families (paywall / consent / login / js-wall / error page), own regexes
  truncation: ends mid-sentence or with an ellipsis / 'read more' marker
  repeated text: a sentence of >=8 words occurring >=3 times in the body
  dates: published_at missing / after created_at+1d (future) / within 120 s of created_at
         (likely fetch-time fallback) / >365 d before created_at
  title: empty / generic (home, news, index...) / equal to the source name
  language: script of the body vs the stated language (Latin/Cyrillic/Arabic/CJK/... only)
Writes PRIVATE DERIVED/article-flags-<inst>.jsonl and prints aggregate tables.
Usage: python3 -I article_quality.py DATA_ROOT INSTANCES_JSON DERIVED
"""
import glob, json, os, re, sys, unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta

data_root, inst_json, derived = sys.argv[1:4]
labels = json.load(open(inst_json))

STUB = {
    'paywall': re.compile(r"subscribe (now|to (continue|read))|subscribers only|for subscribers|abonnez-vous|réservé aux abonnés|"
                          r"allerede abonnent|vain tilaajille|riservato agli abbonati|nur für abonnenten|solo para suscriptores|"
                          r"exclusivo para assinantes|you have reached your (free )?(article )?limit|to continue reading|"
                          r"this (article|content) is (only )?available to|premium content|plus-artikel|abonnement", re.I),
    'consent': re.compile(r"we use cookies|cookie (policy|settings|preferences)|accept (all )?cookies|consent to (the use|our)|"
                          r"manage (your )?(privacy|consent)|nous utilisons des cookies|wir verwenden cookies|utilizamos cookies|"
                          r"privacy preference center", re.I),
    'login': re.compile(r"(sign|log) in to (continue|read|view)|create (a free )?account to|please log ?in", re.I),
    'js_wall': re.compile(r"enable javascript|javascript is (disabled|required)|please enable (js|javascript|cookies)|"
                          r"your browser (is|does) not support|are you a robot|verify you are (a )?human|access denied|"
                          r"checking your browser|just a moment", re.I),
    'error_page': re.compile(r"page not found|404 not found|error 404|the page you (are looking for|requested)|"
                             r"no longer available|has been removed", re.I),
}
TRUNC_END = re.compile(r"(\.\.\.|…|\[…\]|\[\.\.\.\]|read more|continue reading|lire la suite|weiterlesen|leer más|leia mais|"
                       r"читать далее|ler mais|続きを読む)\s*$", re.I)
GENERIC_TITLE = re.compile(r"^(home|homepage|news|index|accueil|startseite|inicio|главная|untitled|page not found|404|"
                           r"error|access denied|just a moment\.*|attention required.*)$", re.I)
SCRIPT_OF_LANG = {
    'ru': 'CYRILLIC', 'uk': 'CYRILLIC', 'bg': 'CYRILLIC', 'sr': None, 'mk': 'CYRILLIC', 'be': 'CYRILLIC', 'kk': 'CYRILLIC',
    'ky': 'CYRILLIC', 'mn': 'CYRILLIC', 'tg': 'CYRILLIC',
    'ar': 'ARABIC', 'fa': 'ARABIC', 'ur': 'ARABIC', 'ps': 'ARABIC', 'ku': None,
    'he': 'HEBREW', 'yi': 'HEBREW', 'el': 'GREEK', 'hy': 'ARMENIAN', 'ka': 'GEORGIAN',
    'hi': 'DEVANAGARI', 'mr': 'DEVANAGARI', 'ne': 'DEVANAGARI', 'bn': 'BENGALI', 'as': 'BENGALI', 'pa': 'GURMUKHI',
    'gu': 'GUJARATI', 'ta': 'TAMIL', 'te': 'TELUGU', 'kn': 'KANNADA', 'ml': 'MALAYALAM', 'si': 'SINHALA',
    'th': 'THAI', 'lo': 'LAO', 'km': 'KHMER', 'my': 'MYANMAR', 'am': 'ETHIOPIC', 'ti': 'ETHIOPIC',
    'zh': 'CJK', 'ja': 'CJK', 'ko': 'HANGUL',
}
LATIN_LANGS = set('en fr de es pt it nl sv no nb nn da fi is et lv lt pl cs sk sl hr bs ro hu tr az sq ca eu gl ga cy mt id ms tl vi sw ha yo ig zu xh so af eo la uz tk'.split())


def script_of(ch):
    try:
        n = unicodedata.name(ch)
    except ValueError:
        return None
    for s in ('LATIN', 'CYRILLIC', 'ARABIC', 'HEBREW', 'GREEK', 'ARMENIAN', 'GEORGIAN', 'DEVANAGARI', 'BENGALI', 'GURMUKHI',
              'GUJARATI', 'TAMIL', 'TELUGU', 'KANNADA', 'MALAYALAM', 'SINHALA', 'THAI', 'LAO', 'KHMER', 'MYANMAR', 'ETHIOPIC',
              'HANGUL'):
        if n.startswith(s):
            return s
    if n.startswith('CJK') or n.startswith('HIRAGANA') or n.startswith('KATAKANA'):
        return 'CJK'
    return None


def dominant_script(text):
    c = Counter()
    for ch in text[:4000]:
        if ch.isalpha():
            s = script_of(ch)
            if s:
                c[s] += 1
    tot = sum(c.values())
    if tot < 50:
        return None, 0.0
    s, n = c.most_common(1)[0]
    return s, n / tot


def parse(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def repeated_sentence(text):
    sents = [s.strip().lower() for s in re.split(r'(?<=[.!?。！？])\s+', text) if len(s.split()) >= 8]
    c = Counter(sents)
    return any(v >= 3 for v in c.values())


def flags_for(src, art):
    text = art.get('content') or ''
    wc = art.get('word_count')
    lang = (art.get('language') or src.get('language') or '').lower()[:2]
    f = {}
    f['words_lt_50'] = wc is not None and wc < 50
    f['words_lt_100'] = wc is not None and wc < 100
    head = text[:3000]
    for k, rx in STUB.items():
        f['stub_' + k] = bool(rx.search(head)) and (wc or 0) < 400
        f['phrase_' + k] = bool(rx.search(text))
    tail = text.rstrip()[-200:]
    f['ends_with_marker'] = bool(TRUNC_END.search(tail))
    last = tail[-1:] if tail else ''
    f['ends_mid_sentence'] = bool(tail) and last.isalnum() and lang not in ('zh', 'ja', 'th')
    f['repeated_sentence'] = repeated_sentence(text)
    p, c = parse(art.get('published_at')), parse(art.get('created_at'))
    f['date_missing'] = p is None
    f['date_future'] = bool(p and c and p > c + timedelta(days=1))
    f['date_eq_fetch'] = bool(p and c and abs((p - c).total_seconds()) <= 120)
    f['date_old_gt_365d'] = bool(p and c and (c - p).days > 365)
    t = (art.get('title') or '').strip()
    f['title_empty'] = not t
    f['title_generic'] = bool(GENERIC_TITLE.match(t))
    f['title_eq_source_name'] = bool(t) and t.lower() == (src.get('name') or '').strip().lower()
    s, share = dominant_script(text)
    want = SCRIPT_OF_LANG.get(lang, 'LATIN' if lang in LATIN_LANGS else None)
    f['lang_checkable'] = bool(want and s)
    f['lang_script_mismatch'] = bool(want and s and s != want and share >= 0.6)
    f['lang_stated_missing'] = not art.get('language')
    f['detected_differs'] = bool(art.get('detected_language') and art.get('language') and art['detected_language'][:2] != art['language'][:2])
    f['quarantined'] = bool(art.get('quarantined'))
    f['body_equals_title'] = bool(t) and text.strip().lower() == t.lower()
    return f, {'wc': wc, 'lang': lang, 'script': s, 'source_type': src.get('source_type'), 'via': next((x.strip()[4:] for x in (src.get('tags') or '').split(',') if x.strip().startswith('via:')), None),
               'quarantine_reason': art.get('quarantine_reason'), 'domain': src.get('domain'), 'source_id': src.get('id'),
               'article_id': art.get('id'), 'country': src.get('country')}

ALL = {}
for folder, label in labels.items():
    out = open(os.path.join(derived, f"article-flags-{label.replace(' ', '_')}.jsonl"), 'w')
    agg = Counter(); n = 0
    for f in glob.glob(os.path.join(data_root, folder, '*source-samples-*', 'samples', '*.json')):
        s = json.load(open(f))
        art = s.get('article')
        if not art:
            continue
        fl, meta = flags_for(s['source'], art)
        n += 1
        for k, v in fl.items():
            agg[k] += bool(v)
        out.write(json.dumps({'flags': fl, 'meta': meta}, ensure_ascii=False) + '\n')
    out.close()
    ALL[label] = (n, agg)

keys = list(next(iter(ALL.values()))[1].keys()) if ALL else []
order = ['Windows', 'Linux A', 'Linux B', 'Linux C']
print('| flag | ' + ' | '.join(order) + ' |')
print('|---|' + '---:|' * len(order))
print('| n (sources sampled) | ' + ' | '.join(str(ALL[o][0]) for o in order) + ' |')
allkeys = sorted({k for o in order for k in ALL[o][1]})
for k in allkeys:
    print(f'| {k} | ' + ' | '.join(f"{ALL[o][1][k]} ({100*ALL[o][1][k]/ALL[o][0]:.1f}%)" for o in order) + ' |')
