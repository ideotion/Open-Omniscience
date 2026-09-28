"""Scratch: add a DISTINCT batch of articles to the source corpus (through the real
index_article chokepoint), so each successive export differs in content, not only bytes.
usage: OO_DATA_DIR=... OO_DB_PASSPHRASE=... python seed_extra.py <batch-tag> <n>"""
import os, sys, random, hashlib
sys.path.insert(0, "/home/user/Open-Omniscience")
sys.path.insert(0, "/home/user/Open-Omniscience/scripts")
from datetime import UTC, date, datetime
import ui_clickthrough_seed as S
from src.database.session import SessionLocal, init_db
from src.analytics.extract import get_extractor
from src.analytics.store import index_article
from src.database.models import Article, Source

tag, n = sys.argv[1], int(sys.argv[2])
init_db()
s = SessionLocal()
rng = random.Random(hash(tag) & 0xffff)
ext = get_extractor("baseline")
langs = ["en", "fr", "de", "zh"]
srcs = {}
for lang in langs:
    src = Source(name=f"Batch {tag} {lang.upper()} Wire", domain=f"batch-{tag}-{lang}.example",
                 language=lang, country={"en": "us", "fr": "fr", "de": "de", "zh": "cn"}[lang],
                 source_type="news", tags="news", status="qualified", enabled=True,
                 qualified_at=datetime.now(UTC), qualification_criteria_version="v1")
    s.add(src); s.flush(); srcs[lang] = src
for i in range(n):
    lang = langs[i % 4]; src = srcs[lang]
    topic, body = S.LANG_PARAGRAPHS[lang][i % len(S.LANG_PARAGRAPHS[lang])]
    content = body + f" [batch-{tag}-{lang}-{topic}-{i}]"
    pub = S._rand_date(rng, date(2025, 1, 1), date(2026, 7, 1))
    a = Article(url=f"https://{src.domain}/{topic}-{i}", canonical_url=f"https://{src.domain}/{topic}-{i}",
                source_id=src.id, title=f"Batch {tag} {topic} {i} — {lang}", content=content,
                published_at=pub, language=lang, hash=hashlib.sha256(content.encode()).hexdigest(),
                word_count=len(content.split()), created_at=pub, updated_at=pub)
    s.add(a); s.commit()
    index_article(s, a, extractor=ext, country=src.country)
s.commit(); s.close()
print("added", n, "articles for batch", tag)
