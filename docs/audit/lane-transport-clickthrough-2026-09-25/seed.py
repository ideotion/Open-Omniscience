"""Seed a plaintext data folder for the S5 walk.

Protected mode is ON with a proxy that does not answer (socks5h://127.0.0.1:9, the
discard port, where nothing listens), so the walk can show the Wikipedia stream WAITING
behind a dead proxy for real, with nothing able to leave the machine: every fetch is
handed that proxy explicitly.

Two download states are written the way a process leaves them, because the walk cannot
produce them on demand: one map region as the Pause button leaves it, and one as a process
killed mid-download leaves it (status "downloading"), which the next boot demotes itself.
Everything else the walk shows is produced live.
"""
from src.database.session import init_db
from src.geo.osm_downloads import get_manager as osm_manager
from src.safety.settings import save_settings

init_db()
save_settings({"fetch_mode": "protected", "http_proxy": "socks5h://127.0.0.1:9"})

m = osm_manager()
paused = m._entry_for("asia")
paused.status, paused.paused_by = "paused", "operator"
paused.total_bytes, paused.downloaded_bytes = 1_300_000_000, 212_000_000
killed = m._entry_for("africa")
killed.status = "downloading"
killed.total_bytes, killed.downloaded_bytes = 6_900_000_000, 48_000_000
m._save()
print("seeded: protected mode through a dead proxy; asia paused by the operator; africa mid-download")
