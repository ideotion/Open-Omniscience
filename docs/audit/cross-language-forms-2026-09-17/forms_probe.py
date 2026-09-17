"""Q509 acceptance: the per-form counts, and the total that does NOT sum them.

Seeds the same synthetic corpus as the S1 agreement probe through the REAL
``index_article``, then calls the shipped ``/api/insights/concept-forms`` handler
directly and prints what a reader would see -- including the two refusals that are the
point of the readout: an unmeasurable form is ABSENT with a reason rather than a 0, and
the per-form figures OVERLAP so they do not add up to the total.
"""
import os, tempfile

tmp = tempfile.mkdtemp(prefix="oo-forms-")
os.environ["OO_DATA_DIR"] = tmp
os.environ["OO_DB_PLAINTEXT"] = "1"
os.environ["OO_NO_SCHEDULER"] = "1"
os.environ["OO_AUTOSEED"] = "0"

from datetime import UTC, datetime, timedelta                  # noqa: E402

from src.analytics.extract import BaselineExtractor            # noqa: E402
from src.analytics.store import index_article                  # noqa: E402
from src.api.insights import insights_concept_forms            # noqa: E402
from src.database.fts import ensure_fts                        # noqa: E402
from src.database.models import Article, Base, Source          # noqa: E402
from src.database.session import SessionLocal, engine          # noqa: E402

Base.metadata.create_all(engine)
s = SessionLocal()

DOCS = [
    ("en", "Climate report", "climate policy and the climate summit", 6),
    ("en", "Climate action",  "climate change is accelerating", 5),
    ("fr", "Rapport climat",  "le climat se rechauffe cette annee", 4),
    ("fr", "Climat urgent",   "urgence climat pour la planete", 3),
    ("de", "Klima Bericht",   "das Klima veraendert sich rasch", 2),
    ("es", "Informe clima",   "el clima cambia rapidamente", 1),
    # Carries TWO forms of the one concept, so it is counted under each of them and ONCE
    # in the total. Without a document like this the overlap caveat is a claim with no
    # measurement behind it -- the readout would look additive and nobody would know.
    ("en", "Bilingual note",  "the climate summit, or le climat, in one article", 7),
    # A ring that is BIGGER than the 40-form cap, so the cap actually bites and the
    # measured/total split is exercised rather than asserted.
    ("en", "Covid brief",     "covid-19 case numbers rose again this week", 8),
    ("es", "Informe covid",   "los casos de covid aumentaron esta semana", 9),
    ("en", "Unrelated",       "football results and transfer news", 0),
]
_EX = BaselineExtractor()
srcs: dict[str, Source] = {}
for lg, title, body, day in DOCS:
    if lg not in srcs:
        src = Source(name=f"src-{lg}", rss_url=f"https://{lg}.example/feed",
                     domain=f"{lg}.example")
        s.add(src); s.flush(); srcs[lg] = src
    _u = f"https://{lg}.example/{title.replace(' ', '-')}"
    a = Article(title=title, content=body, url=_u, canonical_url=_u,
                source_id=srcs[lg].id, language=lg,
                published_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=day),
                hash=f"h-{title}")
    s.add(a); s.flush()
    index_article(s, a, extractor=_EX)
s.commit()
ensure_fts(engine, rebuild="always")

for term, ui in (("climate", "en"), ("climat", "fr"), ("Klima", "de"), ("covid-19", "en")):
    for cap in (True, False):
        d = insights_concept_forms(term=term, ui_lang=ui, sense=None, literal_cap=cap, db=s)
        nonzero = [f for f in d["forms"] if (f.get("articles") or 0) > 0]
        unmeasured = [f for f in d["forms"] if "articles" not in f]
        print(f"\n=== term={term!r} ui_lang={ui!r} literal_cap={cap} ===")
        print("  forms with a hit : "
              + (" · ".join(f"{f['form']} {f['articles']}" for f in nonzero) or "-"))
        print(f"  sum of the forms : {sum(f['articles'] for f in nonzero)}")
        print(f"  TOTAL (distinct) : {d.get('total')}")
        print(f"  measured_forms   : {d['measured_forms']}   total_forms: {d['total_forms']}"
              f"   capped: {d['capped']}   ordering: {d['ordering']}")
        print(f"  unmeasured forms : {len(unmeasured)} (drawn with a reason, never as 0)")
s.close()
