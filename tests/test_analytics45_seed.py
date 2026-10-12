"""The fixture state behind the Chromium look at analytics 4-5 stays honest, and its phone-width rule stays.

``scripts/analytics45_seed.py`` writes the rows the look then reads the page against. If the readers
(``src/wiki/cross_edition.py``) drifted from what the seed's printed truth claims, the look would be
judging the page against a fiction; this runs the seed and asks the real readers the same questions.
The CSS rule is the one fix the look's 390 px run found (both tables were wider than their frame).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_ASK = r"""
import json
from src.database.session import SessionLocal
from src.versioned.store import lane_session
from src.wiki import cross_edition as X
from src.scheduler.settings import load_settings
eds = tuple(load_settings().wiki_lane_editions)
with lane_session("wiki") as lane:
    div = X.divergence(lane, "Q34", editions=eds)
with SessionLocal() as corpus:
    att = X.attention(corpus, edition="en")
print(json.dumps({"div": div, "att": att}, default=str))
"""


def _run(code_args: list[str], data_dir: Path) -> str:
    env = {**os.environ, "OO_DATA_DIR": str(data_dir), "OO_DB_PLAINTEXT": "1", "OO_AUTOSEED": "0", "OO_NO_SCHEDULER": "1"}
    done = subprocess.run([sys.executable, *code_args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout


def test_the_seed_says_what_the_readers_then_read(tmp_path):
    truth = json.loads(_run([str(ROOT / "scripts" / "analytics45_seed.py")], tmp_path))
    got = json.loads(_run(["-c", _ASK], tmp_path).strip().splitlines()[-1])
    div, att = got["div"], got["att"]
    by = {r["edition"]: r for r in div["editions"]}
    want = truth["divergence"]
    assert sorted(e for e, r in by.items() if r["state"] == "found") == sorted(want["found"])
    assert {e: by[e]["length_bytes"] for e in want["sizes"]} == want["sizes"]
    assert (div["smallest"]["edition"], div["largest"]["edition"]) == (want["smallest"], want["largest"])
    assert {e: by[e]["changes_in_window"] for e in want["changes"]} == want["changes"]  # None = unknown, never 0
    assert by["es"]["state"] == "walk-never-ran" and by["ar"]["state"] == "none-after-complete-walk"
    rows = {r["title"]: r for r in att["rows"]}
    for title, w in truth["attention"].items():
        assert rows[title]["views"] == w["views"]
        assert (rows[title]["press_day"], rows[title]["press_7d"]) == (w["day"], w["week"]), title


def test_the_two_analytics_tables_tighten_their_cells_at_phone_width():
    css = (ROOT / "src" / "static" / "app.css").read_text(encoding="utf-8")
    assert "@media (max-width: 480px) { .wiki-table-wrap .living-table th, .wiki-table-wrap .living-table td { padding-inline: 3px; } }" in css
