"""Fix batch B22 of the 2026-09-27 delegated re-walk, pinned: Home's at-a-glance strip and
its chrome.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

* H-1 / P-5 / T-4 / U-1 (one defect): the strip said "(server busy)" on every idle
  install, because ``cache_age_s`` counts from the value's BUILD and an idle app never
  rebuilds. The served cache now publishes ``verified_current`` and ``recount_running_s``,
  and the note keys on those (``tests/rewalk_b22_node_test.js`` runs the client half).
* P-2 / P-4: the French strip pushed the page 28 px sideways at 375 px.
* T-9: "Most recent" squeezed onto two lines at 1440 px by a full-width <select>.
* T-3 / U-8 / U-10 / S-10: text that stayed in a previous language, raw channel codes,
  a French agreement, and a split figure labelled by the wrong population.

Every fix was reproduced in Chromium first (``/tmp/claude-0/fix/B22``); CI runs no
browser, so the behaviour runs as EXTRACTED code under node and the layout is pinned by
the CSS rule each fix rests on.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

from src.api import database as dbmod
from src.api import served_cache
from src.database.models import Source
from src.database.session import SessionLocal, init_db
from tests.js_source_helper import css_rule, function_body, object_literal, read_static

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def setup_module(_module):
    init_db()


@pytest.fixture(autouse=True)
def _clean_cache():
    served_cache.invalidate()
    yield
    served_cache.invalidate()


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _serve(key: str, compute) -> dict:
    s = SessionLocal()
    try:
        return served_cache.cached(key, compute, s, ttl_s=30)
    finally:
        s.close()


def _add_source() -> None:
    s = SessionLocal()
    try:
        s.add(Source(name=f"s-{uuid.uuid4().hex[:8]}", domain=f"{uuid.uuid4().hex[:8]}.test"))
        s.commit()
    finally:
        s.close()


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "rewalk_b22_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- H-1, P-5, T-4, U-1: what the served payload says it knows ------------------ #


def test_an_idle_value_is_verified_current_however_old():
    """The re-walk's exact state: nothing written, the value minutes old. The age stays
    honest (it is the real build age) AND the payload says the value is still exact --
    which is what lets the strip stop calling an idle server busy."""
    _serve("t:idle", lambda s: {"n": 1})
    with served_cache._LOCK:
        entry = served_cache._CACHE["t:idle"]
        entry["built_at"] -= 300
        entry["checked_at"] -= 10_000
    out = _serve("t:idle", lambda s: {"n": 2})
    assert out["n"] == 1, "an idle value must not be rebuilt"
    assert out["cache_age_s"] >= 300, "the age must stay the value's real age"
    assert out["verified_current"] is True
    assert out["recount_running_s"] is None, "no recount runs on an idle app"


def test_a_value_behind_a_write_is_not_verified_and_its_recount_is_timed():
    """After a write the value is NOT verified, and the recount it kicked is timed from
    its start -- the measurement a "server busy" claim may rest on."""
    release = threading.Event()
    calls = {"n": 0}

    def compute(_s):
        calls["n"] += 1
        if calls["n"] > 1:
            release.wait(10)
        return {"n": calls["n"]}

    _serve("t:behind", compute)
    _add_source()
    with served_cache._LOCK:
        served_cache._CACHE["t:behind"]["checked_at"] -= 10_000
    try:
        kicked = _serve("t:behind", compute)
        assert kicked["verified_current"] is False
        assert isinstance(kicked["recount_running_s"], int) and kicked["recount_running_s"] >= 0
        with served_cache._LOCK:
            served_cache._RECOUNT_STARTED["t:behind"] -= 45
        later = _serve("t:behind", compute)
        assert later["recount_running_s"] >= 45, "a long recount must say how long it has run"
        assert later["verified_current"] is False
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with served_cache._LOCK:
            if "t:behind" not in served_cache._RECOUNT_STARTED:
                break
        time.sleep(0.02)
    done = _serve("t:behind", compute)
    assert done["recount_running_s"] is None, "a finished recount still reads as running"
    assert done["n"] == 2, "the recount's value is what is served next"


def test_the_stats_endpoint_carries_both_fields():
    s = SessionLocal()
    try:
        cold = dbmod.database_stats(s)
        warm = dbmod.database_stats(s)
    finally:
        s.close()
    for out in (cold, warm):
        assert "verified_current" in out and "recount_running_s" in out
    assert warm["verified_current"] is True, "an unchanged database verifies on the next poll"


# --- P-2, P-4: the strip at 375 px ------------------------------------------------ #


def test_a_strip_item_wraps_inside_itself_rather_than_widening_the_page():
    css = read_static("app.css")
    strip = css_rule(css, ".stat-strip").replace(" ", "")
    assert "min-width:0" in strip, "the strip must be allowed below its widest item"
    item = css_rule(css, ".stat-strip .s").replace(" ", "")
    assert "white-space:nowrap" not in item, "a whole-item nowrap is what widened the page"
    assert "max-width:100%" in item
    number = css_rule(css, ".stat-strip .s b").replace(" ", "")
    assert "white-space:nowrap" in number, "a number must never break"


# --- T-9: the "Most recent" heading ------------------------------------------------ #


def test_a_select_beside_a_panel_heading_does_not_squeeze_it():
    rule = css_rule(read_static("app.css"), ".phead > select").replace(" ", "")
    assert "width:auto" in rule and "max-width:60%" in rule and "min-width:0" in rule


# --- T-3: the three surfaces a switch left in the old language --------------------- #


def test_the_collection_toggle_records_the_state_it_painted():
    body = function_body(read_static("app-sources.js"), "_paintCollectToggle")
    assert 'btn.setAttribute("data-collect-state", running ? "on" : "off")' in body


# --- U-8, U-10, S-10: every new string keyed x12 ----------------------------------- #


def test_every_new_string_is_keyed_in_all_twelve_locales():
    home = read_static("app-home.js")
    labels = re.findall(r':\s*"([^"]+)"', object_literal(home, "HOME_CHANNEL_LABELS"))
    assert len(labels) >= 30
    keys = labels + [
        "as of {time} (recount pending)",
        "Automatic collection: {pill}running{endpill}",
        "Automatic collection: {pill}stopped{endpill}",
        "Not enabled",
        "{channel}: the channel its sources assert (source type “{code}”), never a quality score. Click to explore its articles.",
        "Each chip is a content channel its sources assert, never a quality score. Click a channel to explore its corpus.",
    ]
    for code, loc in _locales().items():
        for k in keys:
            assert isinstance(loc.get(k), str) and loc[k], f"{code}: no value for {k!r}"
            for slot in re.findall(r"\{\w+\}", k):
                assert slot in loc[k], f"{code}: {k!r} lost its {slot}"


def test_french_agrees_the_collection_state_with_its_noun():
    fr = _locales()["fr"]
    assert fr["Automatic collection: {pill}stopped{endpill}"] == "Collecte automatique : {pill}arrêtée{endpill}"


def test_the_disabled_figure_is_labelled_by_its_predicate():
    home = read_static("app-home.js")
    assert 'sources_candidates: "Not enabled"' in object_literal(home, "HOME_STAT_LABELS")
    hover = object_literal(home, "HOME_SOURCE_SPLIT_HOVER")
    assert "switched off" in hover and "admission was undone" in hover
