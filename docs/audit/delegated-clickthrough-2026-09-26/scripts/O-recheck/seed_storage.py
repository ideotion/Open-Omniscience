"""Seed a plaintext data folder for the Storage walk: a corpus, a real wiki lane file, and
lane_mib history -- 19 days for the corpus (a measured rate) and 3 days for the wiki lane
(too short, so the refusal shows)."""
from datetime import UTC, datetime, timedelta

from src.database.models import StatSnapshot
from src.database.session import SessionLocal, init_db
from src.versioned.store import create_lane, lane_file_bytes

init_db()
create_lane("wiki")
print("wiki lane bytes:", lane_file_bytes("wiki"))
now = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0)
rows = [("lane_mib_press", 20, 3), ("lane_mib_press", 10, 5), ("lane_mib_press", 1, 9),
        ("lane_mib_wiki", 3, 0), ("lane_mib_wiki", 1, 0)]
with SessionLocal() as s:
    for metric, days, mib in rows:
        s.add(StatSnapshot(metric=metric, taken_at=now - timedelta(days=days), value=mib))
    s.commit()
print("seeded", len(rows), "lane_mib rows")
