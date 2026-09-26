"""Scratch: remove the R24 index stamps from a SOURCE corpus, so its export looks like a
backup made before 2026-09-24 (every article owes a re-index on import). Source only."""
import sys
sys.path.insert(0, "/home/user/Open-Omniscience")
from sqlalchemy import text
from src.database.session import SessionLocal, init_db
init_db(); s = SessionLocal()
n = s.execute(text("SELECT COUNT(*) FROM article_index_stamps")).scalar()
s.execute(text("DELETE FROM article_index_stamps")); s.commit()
print("stamps removed:", n, "articles:", s.execute(text("SELECT COUNT(*) FROM articles")).scalar())
