"""Seed a plaintext data folder for the onboarding-tour / evidence-review walk (S05-11 S5, gate 0.5 row K).

Six invented articles from three invented sources (every host is ``.invalid``), enough for the
evidence review to have real numbers to show. No key is created here: the walk needs the
"no evidence key yet" state first.
"""
from datetime import datetime, timedelta

from src.database.models import Article, Source
from src.database.session import SessionLocal, init_db

init_db()
now = datetime(2026, 9, 1, 12, 0)
db = SessionLocal()
try:
    for si, (name, dom) in enumerate([("Walk Alpine Review", "alpine.invalid"),
                                      ("Walk Valley Post", "valley.invalid"),
                                      ("Walk Harbour Times", "harbour.invalid")]):
        s = Source(name=name, domain=dom, language="en", source_type="news", country="ch")
        db.add(s)
        db.flush()
        for i in range(2):
            title = f"Glacier report {si}-{i}: the ice keeps retreating"
            db.add(Article(url=f"https://{dom}/{i}", canonical_url=f"https://{dom}/{i}", source_id=s.id,
                           title=title, content=title + ". The glacier lost mass again this season.",
                           language="en", hash=(f"tour{si}{i}").encode().hex().ljust(64, "0")[:64],
                           created_at=now - timedelta(days=si * 3 + i),
                           published_at=now - timedelta(days=si * 3 + i)))
    db.commit()
finally:
    db.close()
print("seeded")
