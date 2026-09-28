"""Seed a plaintext data folder for the Claim Workspace walk (S05-11 S1, gate row K).

A wire story re-run three ways (a near-identical copy, a rewrite attributing the wire, a
report citing the same origin page), two reports with nothing linking them, a statistics
office's record, an Arabic report, and an unrelated market story. Everything is invented and
labelled so (the ``.invalid`` hosts).
"""
from datetime import datetime, timedelta

from src.database.models import Article, ArticleLink, Source
from src.database.session import SessionLocal, init_db

init_db()
now = datetime(2026, 9, 1, 12, 0)
BODY = ("Glacier melt in the Alps doubled between 2000 and 2020, a study published on Monday "
        "found. The researchers measured the ice loss of 180 glaciers with satellite images. "
        "The loss accelerated after 2015, the authors said.")
db = SessionLocal()
try:
    spec = [
        ("wire", "Walk Wire Desk", "wiredesk.invalid", "gb", "en", "news"),
        ("echo1", "Walk Echo Daily", "echo1.invalid", "us", "en", "news"),
        ("echo2", "Walk Echo Times", "echo2.invalid", "au", "en", "news"),
        ("cite", "Walk Citing Post", "cite.invalid", "ca", "en", "news"),
        ("indep", "Walk Alpine Review", "alpine.invalid", "ch", "de", "news"),
        ("stats", "Walk Stat Office", "stats.invalid", "fr", "fr", "statistics"),
        ("arab", "Walk Arab Daily", "arab.invalid", "eg", "ar", "news"),
        ("other", "Walk Market Gazette", "other.invalid", "jp", "ja", "news"),
    ]
    src = {}
    for key, name, dom, cc, lang, st in spec:
        s = Source(name=name, domain=dom, country=cc, language=lang, source_type=st)
        db.add(s)
        db.flush()
        src[key] = s

    def art(key, i, title, body, days, lang=None):
        a = Article(url=f"https://{src[key].domain}/{i}", canonical_url=f"https://{src[key].domain}/{i}",
                    source_id=src[key].id, title=title, content=body, hash=f"walk{i}".ljust(64, "0"),
                    language=lang or src[key].language, word_count=len(body.split()),
                    created_at=now - timedelta(days=days), published_at=now - timedelta(days=days))
        db.add(a)
        db.flush()
        return a

    wire = art("wire", 1, "Alps glacier melt doubled", "(Reuters) " + BODY, 5)
    art("echo1", 2, "Alps glacier melt doubled, study", "(Reuters) " + BODY, 4)
    art("echo2", 3, "Study: Alpine ice loss twice as fast",
        "Melt of Alpine glaciers doubled over two decades, according to Reuters. "
        "Scientists counted the ice lost from 180 glaciers.", 4)
    citer = art("cite", 4, "Glacier melt doubled in the Alps",
                "A new study says the melt of glaciers in the Alps doubled. The paper looked at "
                "satellite images.", 3)
    art("indep", 5, "Zurich glaciologists on the ice",
        "Glaciologists in Zurich say the melt of Alpine ice has doubled in their own "
        "measurements of twelve glaciers.", 1, lang="en")
    art("stats", 6, "Glacier inventory 2020",
        "The glacier inventory records the melt of Alpine glaciers since 2000.", 30, lang="en")
    art("arab", 7, "ذوبان الأنهار الجليدية في جبال الألب",
        "تضاعف ذوبان الأنهار الجليدية في جبال الألب منذ عام 2000 بحسب دراسة جديدة عن glacier melt.", 2)
    art("other", 8, "Stock markets close higher", "Shares rose in Tokyo on Friday.", 2)
    origin = "https://journal.invalid/glacier-study"
    for a in (wire, citer):
        db.add(ArticleLink(article_id=a.id, url=origin, normalized_url=origin))
    db.commit()
finally:
    db.close()
print("seeded")
