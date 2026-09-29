"""Seed a plaintext data folder for the dossier-seed walk (S05-11 S4, gate 0.5 row K).

One invented item, "Zermatt" under the synthetic id Q999999101, reached by all three routes and
all five joined rails: two press articles name it as a place (the Place route), a Wikipedia page
carries it as a keyword (the keyword route), a law names the "Zermatt" municipal council as an
organisation (the named-entity route), the Wikipedia lane holds a page with the item and the
OpenStreetMap lane an object tagged with it. A second name, "Matter", is given to TWO items, so the
article that uses only it joins neither. Everything is invented; every host is ``.invalid`` or local.
The ring file is this data folder's own local ring file, which the app reads at start.
"""
from datetime import datetime, timedelta

from src.database.models import (
    Article,
    ArticleEntity,
    ArticleKeyword,
    ArticleMentionedPlace,
    Keyword,
    Place,
    Source,
    WikidataItem,
)
from src.database.session import SessionLocal, init_db
from src.paths import data_dir

QID = "Q999999101"

rings = data_dir() / "rings"
rings.mkdir(parents=True, exist_ok=True)
(rings / "keyword_rings_local.yml").write_text(
    "rings:\n"
    f"  - id: walk-zermatt\n    qid: {QID}\n    members: ['en:zermatt', 'fr:zermatt', 'ar:تسيرمات', 'de:zermatt']\n"
    "  - id: walk-matter-river\n    qid: Q999999102\n    members: ['en:matter', 'de:matter']\n"
    "  - id: walk-matter-valley\n    qid: Q999999103\n    members: ['en:matter', 'fr:matter']\n",
    encoding="utf-8",
)

init_db()
now = datetime(2026, 9, 1, 12, 0)
db = SessionLocal()
try:
    src = {}
    for key, name, dom, st, cc in [
        ("press1", "Walk Alpine Review", "alpine.invalid", "news", "ch"),
        ("press2", "Walk Valley Post", "valley.invalid", "news", "it"),
        ("wiki", "Wikipedia (fr)", "fr.wikipedia.org", "wiki", None),
        ("law", "Walk Swiss law", "law.ch.local", "legal", "ch"),
    ]:
        s = Source(name=name, domain=dom, language="en", source_type=st, country=cc)
        db.add(s)
        db.flush()
        src[key] = s

    def article(key, title, days, lang="en"):
        a = Article(url=f"https://{src[key].domain}/{abs(hash(title))}",
                    canonical_url=f"https://{src[key].domain}/{abs(hash(title))}",
                    source_id=src[key].id, title=title, content=title + ".", language=lang,
                    hash=("dossier" + title).encode().hex()[:64].ljust(64, "0"),
                    created_at=now - timedelta(days=days),
                    published_at=(now - timedelta(days=days)) if days is not None else None)
        db.add(a)
        db.flush()
        return a

    for t, d in [("Zermatt closes the Gornergrat line after a rockfall", 60),
                 ("Tourism season ends early in Zermatt", 12)]:
        a = article("press1" if d == 60 else "press2", t, d)
        db.add(ArticleMentionedPlace(article_id=a.id, name="Zermatt", country="ch", kind="city", mentions=1))
    w = article("wiki", "Zermatt (commune suisse)", 90, lang="fr")
    k = Keyword(term="Zermatt", normalized_term="zermatt", language="fr")
    db.add(k)
    db.flush()
    db.add(ArticleKeyword(article_id=w.id, keyword_id=k.id))
    lw = article("law", "Ordinance of the Zermatt municipal council on car-free streets", 30, lang=None)
    db.add(ArticleEntity(article_id=lw.id, name="Zermatt", entity_class="organization", mentions=2))
    m = article("press2", "Matter flows high after the storm", 5)
    db.add(ArticleEntity(article_id=m.id, name="Matter", entity_class="organization", mentions=1))
    db.add(Place(id="node/240037735", qid=QID, name="Zermatt", country="ch", kind="village"))
    db.add(WikidataItem(qid=QID, status="ok",
                        labels_json='{"en": "Zermatt", "ar": "تسيرمات", "fr": "Zermatt"}',
                        descriptions_json='{"en": "municipality in Valais (walk fixture)", "ar": "بلدية في فاليه (بيانات تجربة)"}',
                        fetched_at=now))
    db.commit()
finally:
    db.close()

from src.osm.lane_models import osm_objects_table as T  # noqa: E402
from src.osm.tags import column_name  # noqa: E402
from src.versioned.pipeline import ensure_entity  # noqa: E402
from src.versioned.store import create_lane, lane_session  # noqa: E402

create_lane("wiki")
with lane_session("wiki") as lane:
    ensure_entity(lane, "fr:p4242", title="Zermatt", qid=QID)
create_lane("osm")
with lane_session("osm") as lane:
    lane.execute(T.insert().values(osm_type="n", osm_id=240037735, country_alpha3="CHE", kind="place",
                                   lat=46.0207, lon=7.7491,
                                   **{column_name("wikidata"): QID, column_name("name"): "Zermatt"}))
print("seeded the dossier walk for", QID)
