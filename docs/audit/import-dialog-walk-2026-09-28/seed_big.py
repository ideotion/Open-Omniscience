import os, random, sys
from datetime import datetime, timedelta
from src.database.models import Article, Source
from src.database.session import SessionLocal, init_db
N = int(sys.argv[1]); init_db(); db = SessionLocal(); rnd = random.Random(1)
words = "glacier market election river budget court vaccine harbour tariff drought summit parliament".split()
srcs = []
for i in range(40):
    s = Source(name=f"Imp Source {i}", domain=f"s{i}.invalid", country="fr", language="en", source_type="news"); db.add(s); srcs.append(s)
db.flush(); now = datetime(2026, 9, 1)
tag = os.environ.get("TAG", "a")
for i in range(N):
    body = " ".join(rnd.choice(words) for _ in range(120))
    db.add(Article(url=f"https://s{i%40}.invalid/{tag}{i}", canonical_url=f"https://s{i%40}.invalid/{tag}{i}", source_id=srcs[i%40].id,
        title=f"Story {tag}{i} {rnd.choice(words)}", content=body, hash=__import__("hashlib").sha256(f"{tag}{i}".encode()).hexdigest(), language="en", word_count=120,
        created_at=now - timedelta(hours=i % 5000), published_at=now - timedelta(hours=i % 5000)))
    if i % 5000 == 4999: db.commit()
db.commit(); db.close(); print("seeded", N)
