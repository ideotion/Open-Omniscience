"""Row 260 (0.6 gate row D): the Wikipedia coverage file the Field data button saves, and the script that reads it back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The file is the lane's counters from ``/api/wiki/lane/counters``, the same reading the Diagnostics zip carries. What it must
never carry is the lane's CONTENT: no page title, no text, no address. What the script must never do is turn an absent figure
into a 0, or read a set of pieces with one missing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.versioned.models import VersionedChange, VersionedGap
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import located as L
from src.wiki.lane_models import WikiWalkCursor
from tests.test_wiki_located import HALL, _geo, _hit, _page

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "wiki_coverage_readback.py"
T0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
PART = 200 * 1000  # the Field data button's piece size (app-diagnostics.js FIELD_PART_BYTES)


def _script():
    spec = importlib.util.spec_from_file_location("oo_wiki_coverage_readback", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _script()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    L.reset()
    create_lane("wiki")
    try:
        yield tmp_path
    finally:
        L.reset()
        dispose_all()


def _seed(monkeypatch):
    with lane_session("wiki") as s:
        _page(s, "en", "Fixture Hall", HALL, 1)
        s.add(WikiWalkCursor(edition="en", pages_seen=40, edition_articles=1000, edition_articles_read_at=T0,
                             started_at=T0, updated_at=T0))
        s.add(WikiWalkCursor(edition="fr", pages_seen=7, started_at=T0, updated_at=T0))
        s.add(VersionedChange(change_ref="1", feed="stream:en", change_kind="edit", occurred_at=T0, recorded_at=T0))
        s.add(VersionedGap(feed="stream:en", detected_at=T0, reason="restart", from_time=T0, to_time=T0))
        s.commit()
    monkeypatch.setattr(L, "_osm_scope", lambda: ('[["FXL", "2026-10-01"]]', []))
    monkeypatch.setattr("src.osm.places.geocode", _geo({"2 Fixture Road, Fixtureville": [_hit(48.85, 2.35)]}))
    monkeypatch.setattr("src.wiki.coverage.walk_switch", lambda: False)


def _route_file(tmp_path) -> Path:
    from src.api.wiki_lane import lane_counters_route

    out = tmp_path / "oo-field-20261121-1400-p8000-wiki-coverage.json"
    out.write_text(json.dumps(lane_counters_route(window_days=7)), encoding="utf-8")
    return out


def test_the_file_carries_counts_and_codes_never_the_lane_s_content(lane, monkeypatch):
    _seed(monkeypatch)
    text = _route_file(lane).read_text(encoding="utf-8")
    for content in ("Fixture Hall", "Fixture Road", "Fixtureville", "is a hall", "example.org", "48.85"):
        assert content not in text, f"the lane's content {content!r} reached the Field data file"
    doc = json.loads(text)
    en = next(r for r in doc["coverage"]["editions"] if r["edition"] == "en")
    assert en["pages_seen"] == 40 and en["edition_articles"] == 1000
    assert doc["coverage"]["located"]["per_edition"]["en"] == {"found": 1, "located": 1}
    assert len(text.encode("utf-8")) < PART, "a twelve-edition reading should fit one piece; the button cuts it if not"


def test_the_readback_prints_the_twelve_editions_and_says_why_a_total_is_absent(lane, monkeypatch):
    _seed(monkeypatch)
    lines = R.report(R.load(_route_file(lane)))
    text = "\n".join(lines)
    assert "en: 40 of 1,000 pages seen · total read 2026-11-20 08:00 UTC, no longer refreshed: the page walk is off" in text
    assert "fr: 7 pages seen, total unknown · total not read: the page walk is off" in text
    assert "1 gaps (restart 1)" in text
    assert "located addresses: 1 of 1 found addresses located" in text
    assert sum(1 for ln in lines if ln.split(":")[0] in {"ar", "bn", "de", "es", "hi", "id", "ja", "pt", "ru", "zh"}) == 10
    assert "de: no run yet (no-run-yet)" in text
    assert "%" not in text and "de: 0" not in text, "an absent figure was printed as a measurement"


def test_a_piece_set_is_joined_and_a_missing_piece_is_named_never_guessed(lane, monkeypatch, tmp_path):
    _seed(monkeypatch)
    data = _route_file(lane).read_bytes()
    cut = len(data) // 2
    p1 = tmp_path / "oo-field-x-wiki-coverage-part-001-of-002.json"
    p2 = tmp_path / "oo-field-x-wiki-coverage-part-002-of-002.json"
    p1.write_bytes(data[:cut])
    p2.write_bytes(data[cut:])
    assert R.load(p2)["coverage"]["measured"] is True
    p1.unlink()
    with pytest.raises(ValueError, match="pieces 1 of 2 missing"):
        R.load(p2)


def test_a_lane_that_never_ran_says_so_and_prints_no_figure(tmp_path):
    from src.api.wiki_lane import _ABSENT

    f = tmp_path / "absent.json"
    f.write_text(json.dumps(_ABSENT), encoding="utf-8")
    text = "\n".join(R.report(R.load(f)))
    assert "the Wikipedia lane was not read: the Wikipedia lane has no database file yet" in text
    assert "pages seen" not in text


def test_a_row_from_an_older_build_and_an_unknown_state_are_said_as_such():
    assert R.total_words({"last_refusal": None}) == "state not recorded by this build"
    assert "unknown to this script" in R.total_words({"state": "from-the-future"})
    assert R.total_words({"state": "not_read_paused", "reason": "network_off"}) == "not read: the walk is paused (network_off)"


def test_every_total_state_the_report_gives_has_words_here():
    from src.wiki.coverage import TOTAL_STATES

    assert set(TOTAL_STATES) == set(R._TOTAL_WORDS)


def test_the_script_runs_stdlib_only_from_the_command_line(lane, monkeypatch, tmp_path):
    _seed(monkeypatch)
    f = _route_file(lane)
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(f)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    assert "en: 40 of 1,000 pages seen" in out.stdout
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(bad)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 2 and "not a JSON file" in out.stderr
