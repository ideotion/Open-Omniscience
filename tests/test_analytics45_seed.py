"""The fixture state behind the Chromium look at analytics 4-5 stays honest, and its phone-width rule stays.

``scripts/analytics45_seed.py`` writes the rows the look then reads the page against. If the readers
(``src/wiki/cross_edition.py``) drifted from what the seed's printed truth claims, the look would be
judging the page against a fiction; this runs the seed and asks the real readers the same questions.
The CSS rules are the fix the look's phone-width runs found (both tables were wider than their frame at 390, 360 and 320 px).

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
    cands = X.divergence_candidates(lane)
with SessionLocal() as corpus:
    att = X.attention(corpus, edition="en")
print(json.dumps({"div": div, "att": att, "cands": cands}, default=str))
"""


def _run(code_args: list[str], data_dir: Path) -> str:
    env = {**os.environ, "OO_DATA_DIR": str(data_dir), "OO_DB_PLAINTEXT": "1", "OO_AUTOSEED": "0", "OO_NO_SCHEDULER": "1"}
    env.pop("DATABASE_URL", None)  # it overrides OO_DATA_DIR: a stray one would send these writes to another store
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
    # the suggestions the look judges by number: Q42 (9 changes, found in 2 editions) then Q34 (3, 4)
    items = [(c["qid"], c["changes_in_window"], c["editions_found"]) for c in got["cands"]["items"]]
    assert items[:2] == [("Q42", 9, 2), ("Q34", 3, 4)], items
    rows = {r["title"]: r for r in att["rows"]}
    for title, w in truth["attention"].items():
        assert rows[title]["views"] == w["views"]
        assert (rows[title]["press_day"], rows[title]["press_7d"]) == (w["day"], w["week"]), title


def test_the_two_analytics_tables_shrink_to_their_frame_at_phone_widths():
    css = (ROOT / "src" / "static" / "app.css").read_text(encoding="utf-8")
    sel = ".wiki-table-wrap .living-table"
    for width, size, pad, head in (("480", "12px", "2px", "10px"), ("340", "11px", "1px", "9px")):
        block = css.split(f"@media (max-width: {width}px) {{", 1)[1].split("\n}\n", 1)[0]
        assert f"{sel} {{ font-size: {size}; }}" in block, width
        assert f"{sel} th, {sel} td {{ padding-inline: {pad}; }}" in block, width
        assert f"{sel} th {{ font-size: {head}; }}" in block, width


def _seed_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("analytics45_seed", ROOT / "scripts" / "analytics45_seed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_seed_refuses_a_store_that_is_in_use_and_a_database_url(tmp_path):
    refuse = _seed_module().refuse_unless_scratch
    fresh = tmp_path / "fresh"
    assert refuse({"OO_DATA_DIR": str(fresh)}) is None  # does not exist yet
    fresh.mkdir()
    assert refuse({"OO_DATA_DIR": str(fresh)}) is None  # empty
    (fresh / "open_omniscience.db").write_bytes(b"x")
    assert "not empty" in refuse({"OO_DATA_DIR": str(fresh)})
    assert "OO_DATA_DIR" in refuse({})
    empty = tmp_path / "empty"
    empty.mkdir()
    assert "DATABASE_URL" in refuse({"OO_DATA_DIR": str(empty), "DATABASE_URL": "sqlite:////elsewhere.db"})


def test_the_seed_script_itself_exits_before_touching_anything_when_refused(tmp_path):
    held = tmp_path / "held"
    held.mkdir()
    (held / "settings.json").write_text("{}", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "analytics45_seed.py")], cwd=ROOT, capture_output=True, text=True, timeout=60,
        env={**os.environ, "OO_DATA_DIR": str(held), "OO_DB_PLAINTEXT": "1", "OO_NO_SCHEDULER": "1"} | {"DATABASE_URL": ""},
    )
    assert done.returncode != 0 and "not empty" in done.stderr
    assert sorted(p.name for p in held.iterdir()) == ["settings.json"]  # nothing was added
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "analytics45_seed.py")], cwd=ROOT, capture_output=True, text=True, timeout=60,
        env={**os.environ, "OO_DATA_DIR": str(tmp_path / "new"), "DATABASE_URL": "sqlite:////nonexistent/x.db"},
    )
    assert done.returncode != 0 and "DATABASE_URL" in done.stderr
    assert not (tmp_path / "new").exists()
