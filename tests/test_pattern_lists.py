"""The full lists behind the pattern Leads, corpus-wide Who, and the missing undo controls (R685).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Lane M's route sweep found twelve reader features with no button. This pins:

* the nine list routes say WHEN they were computed (R685), stamped inside the cached compute so
  a cache hit carries the time the scan ran, not the time it was served;
* the page's registry of the eight pattern lists matches the server's routes and the array each
  one answers with, so a renamed route or key fails here, not as an empty dialog;
* each control is wired where its task happens: a Lead's back opens its list, a dismissed card leaves
  an Undo button in its place, the Briefing header brings dismissed cards back, a hidden keyword has its undo beside it;
* the three undo POSTs answer a person's click only (event.isTrusted, as R673 does);
* every word the lists add is in all 12 locales with its placeholders, and no item frame carries a
  verdict word (R685: the pattern's name carries the label, the caveat qualifies it).

The renderers themselves run as real code in tests/pattern_lists_node_test.js.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.database.session import init_db
from tests.js_source_helper import function_source

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"
_JS = (_STATIC / "app-patterns.js").read_text(encoding="utf-8")

_LIST_ROUTES = {
    "/api/insights/copypasta": "items",
    "/api/insights/flooded-topics": "items",
    "/api/insights/headline-body-mismatch": "items",
    "/api/insights/manufactured-emergence": "items",
    "/api/insights/recycled-claims": "clusters",
    "/api/insights/source-laundering": "clusters",
    "/api/signals/disputed-chronology": "items",
    "/api/signals/story-propagation": "items",
    "/api/insights/who": "entities",
}


@pytest.mark.parametrize("route,key", sorted(_LIST_ROUTES.items()))
def test_every_list_route_says_when_it_was_computed(route, key):
    init_db()
    c = TestClient(app)
    r = c.get(route)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body.get(key), list), f"{route} answers its list under {key!r}"
    assert re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$", body.get("computed_at") or ""), body.get("computed_at")
    assert body.get("caveat"), f"{route} still carries its caveat"


def test_a_cached_answer_keeps_the_time_it_was_computed():
    init_db()
    c = TestClient(app)
    first = c.get("/api/insights/copypasta?limit=37").json()["computed_at"]
    again = c.get("/api/insights/copypasta?limit=37").json()["computed_at"]
    assert first == again, "the stamp is inside the cache, so a hit does not claim to be fresh"


def test_the_page_registry_matches_the_server_routes_and_keys():
    reg = re.findall(r'\{type: "(\w+)", path: "([^"]+)", key: "(\w+)"\}', _JS)
    assert len(reg) == 8
    for _type, path, key in reg:
        assert _LIST_ROUTES.get(path) == key, (path, key)
    # Each type is a real Lead type, so a card's back can find its list.
    producers = (_ROOT / "src" / "briefing" / "producers.py").read_text(encoding="utf-8")
    for type_, _path, _key in reg:
        assert re.search(rf'type="{type_}"', producers), f"{type_} is a Lead type"


def test_each_control_sits_where_its_task_happens():
    home = (_STATIC / "app-home.js").read_text(encoding="utf-8")
    insights = (_STATIC / "app-insights.js").read_text(encoding="utf-8")
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
    # A Lead's back opens its list, beside "Open corpus".
    assert re.search(r"\$\{openBtn\}\s*\$\{typeof ooPatternListButton === \"function\" \? ooPatternListButton\(c\) : \"\"\}", home)
    # Dismissing offers its undo; the header offers to bring every dismissed card back.
    assert "ooCardDismissedUndo(el, id)" in function_source(home, "_dismissCardNow")
    assert "ooPaintBriefDismissed(data.dismissed_count)" in home
    assert '<span id="brief-dismissed"' in html
    # A hidden keyword gets its undo right beside the button that hid it.
    assert "ooKeywordUndoButton(btn.dataset.norm, btn)" in function_source(insights, "kxHide")
    # Insights gains the two lazy views; the dialog and the script ship with the page.
    assert '<button data-tab="patterns">Patterns</button>' in html and '<button data-tab="who">Who</button>' in html
    assert 'id="ins-patterns"' in html and 'id="ins-who"' in html
    assert 'if (cat === "patterns"' in insights and 'if (cat === "who"' in insights
    assert '<dialog id="pattern-list"' in html
    assert html.index('src="/static/app-patterns.js"') > html.index('src="/static/app-insights.js"')
    assert '"/static/app-patterns.js",' in sw


def test_the_undo_posts_answer_a_persons_click_only():
    for fn, route in (("ooPaintBriefDismissed", "/api/briefing/dismissed/clear"), ("ooKeywordUndoButton", "/api/insights/include")):
        src = function_source(_JS, fn)
        assert f'api("{route}"' in src, route
        assert src.index("if (!ev.isTrusted) return;") < src.index(f'api("{route}"'), route
    # The single-card Undo is a real button left where the card was (keyboard and screen readers reach it,
    # a toast they could not), and it too answers a person's click only.
    undo = function_source(_JS, "ooCardDismissedUndo")
    assert 'undo.addEventListener("click", (ev) => { if (!ev.isTrusted) return;' in undo and "ooRestoreCard(id)" in undo
    assert 'undo.type = "button"' in undo and "undo.focus()" in undo


def test_no_new_name_joins_the_declarative_allow_list():
    # The lists wire their own listeners, so oo-on.js's OO_ACTIONS is untouched by this work.
    assert not re.search(r'data-on-\w+=', _JS)


def test_every_word_the_lists_add_is_in_all_twelve_locales():
    keys = set(re.findall(r'(?<![\w.])(?:t|tf|_failMsg)\(\s*"((?:[^"\\]|\\.)*)"', _JS))
    keys |= set(re.findall(r'_patT\(\)\("((?:[^"\\]|\\.)*)"', _JS))
    assert len(keys) > 40
    ph = lambda s: sorted(re.findall(r"\{(\w+)\}", s))  # noqa: E731
    for f in sorted((_STATIC / "locales").glob("*.json")):
        table = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert k in table, f"{f.name}: {k!r}"
            assert ph(table[k]) == ph(k), f"{f.name}: placeholders of {k!r}"


_VERDICT = re.compile(r"\b(fake|manipulat\w*|propaganda|disinformation|misinformation|lies?|bots?|trolls?|coordinated|flood\w*|launder\w*)\b", re.I)


def test_no_item_frame_carries_a_verdict_word():
    body = function_source(_JS, "patternItemText")
    frames = re.findall(r'tf\("((?:[^"\\]|\\.)*)"', body)
    assert len(frames) == 10, "eight patterns; headline vs body names which of its two checks passed"
    for fr in frames:
        assert not _VERDICT.search(fr), fr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_renderers_run_as_real_code():
    proc = subprocess.run(["node", str(Path(__file__).with_name("pattern_lists_node_test.js"))],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checks passed" in proc.stdout
