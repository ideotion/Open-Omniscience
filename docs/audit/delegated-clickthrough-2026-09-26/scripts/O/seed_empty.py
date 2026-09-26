"""O12: an EMPTY encrypted corpus (schema only, no articles) plus the legacy scheduler file."""
import json
from src.database.session import init_db
from src.paths import data_dir
init_db()
(data_dir() / "scheduler_settings.json").write_text(json.dumps({"mode": "markets"}) + "\n", "utf-8")
print("empty encrypted corpus + legacy scheduler_settings.json {'mode': 'markets'} at", data_dir())
