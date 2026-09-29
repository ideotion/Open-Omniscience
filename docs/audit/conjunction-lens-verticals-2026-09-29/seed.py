"""Seed a plaintext data folder for the Conjunction Lens walk (S05-11 S3, gate 0.5 row K).

Three verticals carry the same few keywords, so a combination reads differently in each:
press (two newsroom sources), Wikipedia (``en.wikipedia.org``) and law (``law.fr.local``, the
law tracker's own domain shape). Four articles name Zermatt, which is a Place, so the place card
opens the lens scoped to them. Everything is invented; every host is ``.invalid`` or local.
"""
from datetime import date, datetime, timedelta

from src.database.models import (
    Article,
    ArticleMentionedPlace,
    Keyword,
    KeywordMention,
    Place,
    Source,
)
from src.database.session import SessionLocal, init_db

init_db()
now = datetime(2026, 9, 1, 12, 0)
db = SessionLocal()
try:
    spec = [
        ("press1", "Walk Alpine Review", "alpine.invalid", "news"),
        ("press2", "Walk Valley Post", "valley.invalid", "news"),
        ("wiki", "Wikipedia (en)", "en.wikipedia.org", "wiki"),
        ("law", "Walk French law", "law.fr.local", "law"),
    ]
    src = {}
    for key, name, dom, st in spec:
        s = Source(name=name, domain=dom, language="en", source_type=st)
        db.add(s)
        db.flush()
        src[key] = s

    # (source, title, days ago, keywords, names Zermatt)
    rows = [
        ("press1", "Drought empties the Rhone reservoirs", 60, ["drought", "reservoir", "hydropower"], True),
        ("press1", "Glacier melt feeds the river, for now", 45, ["glacier", "drought", "river"], True),
        ("press2", "Farmers ask for water permits", 30, ["drought", "water permit", "harvest"], False),
        ("press2", "Hydropower output falls in the Valais", 20, ["hydropower", "drought", "reservoir"], True),
        ("press1", "Tourism season ends early", 10, ["tourism", "glacier"], True),
        ("press2", "Rain returns to the valley", 5, ["river", "harvest"], False),
        ("wiki", "Drought in Switzerland", 90, ["drought", "glacier", "river", "hydropower"], False),
        ("wiki", "Rhone Glacier", 80, ["glacier", "river", "tourism"], False),
        ("wiki", "Grande Dixence Dam", 70, ["reservoir", "hydropower", "glacier"], False),
        ("law", "Water code, article L211-3 (drought restrictions)", 40, ["drought", "water permit", "river"], False),
        ("law", "Decree on hydropower concessions", 25, ["hydropower", "reservoir", "water permit"], False),
    ]
    kws = {}
    for i, (key, title, days, terms, zermatt) in enumerate(rows, start=1):
        body = f"{title}. " + " ".join(terms) + "."
        a = Article(url=f"https://{src[key].domain}/{i}", canonical_url=f"https://{src[key].domain}/{i}",
                    source_id=src[key].id, title=title, content=body, hash=f"lens{i:03d}".ljust(64, "0"),
                    language="en", word_count=len(body.split()),
                    created_at=now - timedelta(days=days), published_at=now - timedelta(days=days))
        db.add(a)
        db.flush()
        for j, term in enumerate(terms):
            if term not in kws:
                k = Keyword(term=term, normalized_term=term, language="en")
                db.add(k)
                db.flush()
                kws[term] = k
            db.add(KeywordMention(keyword_id=kws[term].id, article_id=a.id, count=1 + j,
                                  observed_on=(now - timedelta(days=days)).date()))
        if zermatt:
            db.add(ArticleMentionedPlace(article_id=a.id, name="Zermatt", country="ch", kind="city",
                                         lat=46.0207, lon=7.7491, mentions=1, note="walk seed"))
    db.add(Place(id="node/240037735", name="Zermatt", country="ch", kind="village"))
    db.commit()
    print("seeded", len(rows), "articles,", len(kws), "keywords, Zermatt in",
          sum(1 for r in rows if r[4]), "of them; as of", date.today().isoformat())
finally:
    db.close()
