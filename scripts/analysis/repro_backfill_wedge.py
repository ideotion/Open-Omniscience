"""Reproducer: ``backfill_corpus`` makes no forward progress past an article
that legitimately yields zero keywords.

``_unindexed_query`` (src/analytics/store.py:445) selects articles with no
KeywordMention rows, ordered by id, limited -- with NO cursor. An article that
correctly produces zero kept terms (empty/whitespace body, all-stopword text, or a
body killed by self-name suppression) never leaves that set, so it is re-selected
on every pass forever and everything behind it is never reached. ``indexed`` counts
ATTEMPTS, not progress, so the caller's ``r.indexed === 0`` break condition
(src/static/app.js, autoIndexInsights) never fires either.

Run:  .venv/bin/python3.13 scripts/analysis/repro_backfill_wedge.py

Expected on unfixed code: four passes, ``indexed=4`` every time, ``remaining``
unchanged, and the real articles behind the duds never gain a single mention.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""
import os, sys, tempfile
sys.path.insert(0, "/home/user/Open-Omniscience")
tmp = tempfile.mkdtemp(prefix="oo-wedge-")
os.environ.update(OO_DATA_DIR=tmp, OO_DB_PLAINTEXT="1", OO_NO_SCHEDULER="1")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.models import Base, Article, Source, KeywordMention
from src.analytics.extract import get_extractor
from src.analytics.store import backfill_corpus

eng = create_engine(f"sqlite:///{tmp}/w.db", future=True)
Base.metadata.create_all(eng)
S = sessionmaker(bind=eng, future=True, autoflush=False, expire_on_commit=False)
s = S()
src = Source(name="Wedge News", domain="wedge.example", enabled=True)
s.add(src); s.flush()

# 4 articles that legitimately produce zero kept terms, then 3 real ones.
duds = ["", "     ", "the of and to in for on with a is", "Wedge News"]
for i, txt in enumerate(duds):
    s.add(Article(title="", url=f"https://wedge.example/d{i}", canonical_url=f"https://wedge.example/d{i}",
                  content=txt, language="en", source_id=src.id, hash=f"d{i}"))
real = ("Parliament approved the regional infrastructure budget after a long committee inquiry "
        "into energy policy and inflation across the northern districts. ") * 6
for i in range(3):
    s.add(Article(title=f"Real {i}", url=f"https://wedge.example/r{i}", canonical_url=f"https://wedge.example/r{i}",
                  content=real, language="en", source_id=src.id, hash=f"r{i}"))
s.commit()
ex = get_extractor("baseline")

print("limit=4, seven articles: four un-indexable then three real\n")
for p in range(1, 5):
    r = backfill_corpus(s, extractor=ex, limit=4)
    got = {a for (a,) in s.query(KeywordMention.article_id).distinct()}
    print(f"  pass {p}: indexed={r['indexed']} remaining={r['remaining']}  articles with mentions={sorted(got)}")
ids = [a.id for a in s.query(Article).order_by(Article.id)]
print(f"\n  real article ids = {ids[4:]}")
print("  -> if these never appear above, the queue is wedged and nothing behind it is ever reached.")
