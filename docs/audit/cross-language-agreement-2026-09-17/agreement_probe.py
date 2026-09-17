"""S1 acceptance: does every analysis tab agree with the Articles list on ONE concept?

Seeds a synthetic corpus through the REAL index_article (never by inserting rows), then
asks the Articles list and each analysis tab for the same concept and compares.
"""
import os, sys, tempfile, json

tmp = tempfile.mkdtemp(prefix="oo-agree-")
os.environ["OO_DATA_DIR"] = tmp
os.environ["OO_DB_PLAINTEXT"] = "1"
os.environ["OO_NO_SCHEDULER"] = "1"
os.environ["OO_AUTOSEED"] = "0"

from src.database.models import Article, Base, Source          # noqa: E402
from src.database.session import SessionLocal, engine          # noqa: E402
from src.analytics.store import index_article                  # noqa: E402
from src.analytics.extract import BaselineExtractor            # noqa: E402
from src.database.fts import ensure_fts, search_ids, search_total  # noqa: E402
from src.analytics import queries as q                         # noqa: E402
from src.analytics.equivalence import resolve_concept          # noqa: E402
from datetime import datetime, timedelta, UTC                  # noqa: E402

Base.metadata.create_all(engine)
s = SessionLocal()

# Three languages, one concept. The ring `climate-change` really carries these.
DOCS = [
    ("en", "Climate report", "climate policy and the climate summit", 6),
    ("en", "Climate action",  "climate change is accelerating", 5),
    ("fr", "Rapport climat",  "le climat se rechauffe cette annee", 4),
    ("fr", "Climat urgent",   "urgence climat pour la planete", 3),
    ("de", "Klima Bericht",   "das Klima veraendert sich rasch", 2),
    ("es", "Informe clima",   "el clima cambia rapidamente", 1),
    ("en", "Unrelated",       "football results and transfer news", 0),
]
_EX = BaselineExtractor()
srcs = {}
for lg, title, body, day in DOCS:
    if lg not in srcs:
        src = Source(name=f"src-{lg}", rss_url=f"https://{lg}.example/feed",
                     domain=f"{lg}.example")
        s.add(src); s.flush(); srcs[lg] = src
    _u = f"https://{lg}.example/{title.replace(' ','-')}"
    a = Article(title=title, content=body, url=_u, canonical_url=_u,
                source_id=srcs[lg].id, language=lg,
                published_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=day),
                hash=f"h-{title}")
    s.add(a); s.flush()
    index_article(s, a, extractor=_EX)
s.commit()
ensure_fts(engine, rebuild="always")

def row(label, **kw):
    print(f"  {label:<34} " + " · ".join(f"{k}={v}" for k, v in kw.items()))

for term, ui in (("climate", "en"), ("climat", "fr")):
    for expand in (True, False):
        print(f"\n=== term={term!r} ui_lang={ui!r} expand={expand} ===")
        c = resolve_concept(term, ui_lang=ui, expand=expand,
                            frequency=q.keyword_frequency(s) if expand else None)
        ck = q.resolve_concept_keywords(s, term, ui_lang=ui, expand=expand)
        ids = search_ids(s, term, expand=c, exclude_quarantined=True) or []
        total = search_total(s, term, expand=c, exclude_quarantined=True)
        row("ARTICLES (search_ids / total)", ids=len(ids), total=total)
        row("resolve_concept", forms_searched=c.searched_forms, forms_total=c.total_forms,
            capped=c.cap_applied, ordering=c.ordering)
        row("concept keywords in corpus", n=len(ck.keywords),
            terms=",".join(k.normalized_term for k in ck.keywords) or "-")
        t = q.trend(s, term, bucket="day", concept=ck)
        row("TREND tab", articles=t.get("articles"), mentions=t.get("total"),
            langs=",".join(sorted(t.get("by_language", {}))) or "-")
        kids = q.corpus_keywords(s, article_ids=ids[:900], limit=5)
        row("KEYWORDS tab (over the same ids)", n_articles=kids.get("n_articles", len(ids[:900])))
        ctx = q.context(s, term, limit=50, concept=ck)
        row("CONTEXT tab", mentions=len(ctx.get("mentions", [])))
        assoc = q.associations(s, term, limit=5, min_cooccur=1, concept=ck)
        row("ASSOCIATIONS / mindmap", n_with_term=assoc.get("n_articles_with_term"))
        verdict = "AGREE" if total == len(ids) else "DISAGREE"
        agree_trend = "AGREE" if t.get("articles") == len(ids) else (
            f"trend={t.get('articles')} vs articles={len(ids)}")
        print(f"  -> total vs ids: {verdict} | trend articles vs articles list: {agree_trend}")
s.close()
