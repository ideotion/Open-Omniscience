"""Batch B10's cross-batch findings, pinned: the keyword surfaces' last English and the
surfaces a language switch did not reach (K-strings, K-repaint, K-mindmap, K-reader,
K-cache), plus the Bulletin half of M7.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each was found by a sibling batch's Chromium walk (2026-09-27) and re-measured here.
CI runs no browser, so the behaviour runs as REAL extracted code under node
(``tests/bulletin_repaint_node_test.js``) and the strings are checked where they are
decided: the English a surface shows must be a key, translated, in all twelve locales.
The server's own fixed sentences are read from the code that produces them (never
copied into this file), so a reworded method or caveat fails here instead of silently
rendering English again.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import (
    array_literal,
    assert_absent,
    event_listener_bodies,
    function_body,
    read_static,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _assert_keyed_x12(keys, *, translated_in=("fr", "ar", "zh")):
    """Every key in all 12 locales, and a REAL translation (not the English) in the
    languages the walk measured. A placeholder set that changed is a broken frame."""
    loc = _locales()
    missing = [(lg, k) for k in keys for lg, d in loc.items() if k not in d]
    assert not missing, f"keys missing from the locales: {missing[:8]}"
    for k in keys:
        holes = set(re.findall(r"\{(\w+)\}", k))
        for lg, d in loc.items():
            assert set(re.findall(r"\{(\w+)\}", d[k])) == holes, (lg, k, d[k])
        for lg in translated_in:
            assert loc[lg][k] != k, f"{lg}.json carries {k!r} untranslated"


def test_the_bulletin_panel_repaints_and_speaks_the_ui_language_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "bulletin_repaint_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- K-strings: the Bulletin Review panel ------------------------------------- #


def _bulletin_block() -> str:
    js = read_static("app-agenda.js")
    start = js.index("// -- The Bulletin (design record")
    end = js.index("// -- Calendar feed directory")
    return js[start:end]


def test_every_bulletin_literal_is_a_key_in_all_twelve_locales():
    """The i18n gates scan ``t(``/``tf(`` only, so the panel's own ``_bulT``/``_bulTf``
    helpers -- and the status keys handed to ``_bulSay`` -- were invisible to them:
    25 of its sentences had no key at all and rendered English in every locale."""
    js = _bulletin_block()
    lits: set[str] = set()
    for rx in (
        r'_bulTf?\(\s*"((?:[^"\\]|\\.)*)"',
        r'_bulSay\(\s*"[\w-]+",\s*"((?:[^"\\]|\\.)*)"',
    ):
        lits.update(json.loads(f'"{m}"') for m in re.findall(rx, js))
    assert len(lits) > 40, f"the scan found too little to be scanning the panel: {len(lits)}"
    loc = _locales()
    missing = sorted(k for k in lits for d in loc.values() if k not in d)
    assert not missing, f"Bulletin sentences with no key: {sorted(set(missing))[:10]}"
    # The "X: " + message welds are frames now, so a locale can place the value.
    assert_absent(js, '_bulT("Could not ', why="an error line is welded English + message")
    assert_absent(js, '_bulT("row(s)")', why="a count and its noun are one frame")


def _privacy_sentences() -> list[str]:
    tree = ast.parse((_ROOT / "src" / "bulletin" / "privacy.py").read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_CAVEAT" for t in node.targets):
            assert isinstance(node.value, ast.Constant)
            out.append(node.value.value)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_item":
            for arg in node.args[1:3]:
                assert isinstance(arg, ast.Constant), "an item's what/why is no longer a fixed sentence"
                out.append(arg.value)
    return out


def test_the_review_panels_server_sentences_are_keyed_x12():
    """The review caveat and method, each section's heading, the fixed skip reasons and
    the whole export-privacy enumeration arrive from the server in English. They are
    the consent text an operator reads before a file leaves the machine (the privacy
    block is §18's disclosure), so they ship x12 like every other caveat."""
    from src.bulletin.review import review_view

    v = review_view({"sections": []})
    headings = [s.replace("_", " ").capitalize() for s in (
        "rising_concepts", "across_channels", "by_topic_tag", "through_time", "alerts",
        "changes_of_record", "country_coverage")]
    skips = [
        "no rising concepts to attribute for this period",
        "the period's concepts resolved to no plain keywords",
        "none of the period's concepts resolved to a stored keyword",
    ]
    privacy = _privacy_sentences()
    assert len(privacy) == 17, f"the enumeration changed shape: {len(privacy)} sentences"
    _assert_keyed_x12([v["caveat"], v["method"], *headings, *skips, *privacy])
    # ...and the panel actually looks them up.
    js = _bulletin_block()
    for needle in ("_bulT(v.caveat", "_bulT(v.method", "_bulT(it.what)", "_bulT(it.why_it_matters)",
                   "_bulT(d.caveat", "_bulT(s.skipped)", "_bulT(slug.charAt(0).toUpperCase()"):
        assert needle in js, f"the Review panel no longer translates via {needle}"


# --- K-repaint -------------------------------------------------------------------- #


def test_the_bulletin_repaints_from_what_it_drew_on_a_language_switch():
    boot = read_static("app-boot.js")
    bodies = event_listener_bodies(boot, "oo:langchange")
    assert any("_bulRepaint()" in b for b in bodies), (
        f"{len(bodies)} listener(s) found, none repaints the Bulletin panel")
    body = function_body(_bulletin_block(), "_bulRepaint")
    for call in ("_bulPaintGate()", "_bulPaintEditions()", "_bulRender(_bulView)",
                 "_bulPaintPrivacy()", "_bulPaintMsg(id)"):
        assert call in body, f"_bulRepaint no longer redraws via {call}"
    assert "api(" not in body, "a language switch must never fetch for the Bulletin"


def test_the_trend_and_group_surfaces_repaint_on_a_language_switch():
    """Insights -> Groups draws the keyword label and the rate line; the Trends rows'
    value labels are keyed frames now, so `loadTrends` re-running draws them again."""
    js = read_static("app-corpus.js")
    callers = array_literal(function_body(js, "ooKwRepaintOnLangChange"), "callers")
    for entry in ('["sg-list", "loadSuperGroups"]', '["trd-top", "loadTrends"]',
                  '["trd-windows", "loadTrendWindows"]'):
        assert entry in callers, f"{entry} is not repainted on a switch"


# --- K-strings: Trends, the super-group rate line, the method and the caveat ----- #


def test_the_trend_value_lines_are_keyed_frames_x12():
    js = read_static("app-corpus.js")
    frames = [
        "↑{growth}× · {recent} recent",
        "↑{growth}× ({recent} recent · {prior} prior)",
        "↑{growth}× ({recent} recent · {prior} prior, {window} days vs {baseline} days)",
        "Rising = {method}",
    ]
    for f in frames:
        assert f'"{f}"' in js, f"the frame {f!r} is not in app-corpus.js"
    _assert_keyed_x12(frames)
    for name in ("loadTrends", "loadTrendWindows"):
        body = function_body(js, name)
        assert_absent(body, "} recent`", why=f"{name} still composes an English value line")
        assert_absent(body, '"Rising = " +', why="the method line is welded English")
    ins = read_static("app-insights.js")
    assert "trendRateText(g.rate, {window: true})" in ins, (
        "the super-group rate line is not the keyed frame")
    # Measured in the walk: the fr card read "Dominé par « voting »" above a chip reading
    # "vote". The dominance line names its member through the same label as the chip.
    sg = function_body(ins, "sgCard")
    assert "kwLabelParts(Object.assign({}, domM" in sg and "member: domName" in sg
    _assert_keyed_x12(["group · {n}", "also in: {groups}"])


def test_the_trend_method_and_window_caveat_the_server_sends_are_keyed_x12():
    """Read from the producers, not restated: the caveat is a caveat, so x12."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.analytics import queries as q
    from src.database.models import Base

    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    rising = q.trending(s, window_days=7, baseline_days=30)
    windows = q.trending_windows(s)
    _assert_keyed_x12([rising["method"], windows["caveat"]])
    js = read_static("app-corpus.js")
    assert "T(rising.method)" in function_body(js, "loadTrends")
    assert "t(d.caveat)" in function_body(js, "loadTrendWindows")


# --- K-mindmap ------------------------------------------------------------------- #


def test_the_mind_map_controls_and_its_own_sentences_are_keyed():
    js = read_static("app-analysis.js")
    body = function_body(js, "renderAnMindmap")
    assert 'esc(t("Map"))' in body and 'esc(t("Cloud"))' in body
    assert_absent(body, '})">Map</button>', why="the Map button is an English literal")
    assert_absent(body, '})">Cloud</button>', why="the Cloud button is an English literal")
    assert "t(g.method)" in body and "t(g.caveat)" in body

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.analytics import queries as q
    from src.database.models import Base

    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    empty = q.article_graph(sessionmaker(bind=eng, future=True)(), article_ids=[1])
    full_caveat = "A concept map of the keywords present, not a co-occurrence network; not causation."
    assert full_caveat in (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    _assert_keyed_x12(["Map", "Cloud", empty["method"], empty["caveat"], full_caveat],
                      translated_in=("fr", "ar"))


# --- K-reader / K-cache ------------------------------------------------------------ #


def test_the_readers_hover_stats_cache_the_payload_and_speak_the_ui_language():
    """The reader cached the FORMATTED line per term and prepended it once per element,
    so a keyword hovered before a language switch kept the old language's stats line
    (and its caveat was appended untranslated). The payload is cached now and the line
    is composed on each hover."""
    js = read_static("reader.js")
    body = function_body(js, "enrichKwStat")
    assert "_kwStatCache[term] = line" not in body, "the reader caches the composed line again"
    assert "_kwStatCache[term] = d" in body
    assert "data-kwstat-done" not in body, "a one-shot flag freezes the first language's line"
    assert "T(d.caveat)" in function_body(js, "kwStatLine")
    # The Keywords tab's own method and caveat lines, under the label (M7's port): the
    # method is a fixed sentence, the caveat carries a count and arrives as a frame.
    rk = function_body(js, "renderKeywords")
    assert "T(d.method" in rk and "TF(d.caveat_i18n" in rk
    src = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    method = re.search(r'res\["method"\] = "(Keyword counts across[^"]+)"', src)
    frame = re.search(r'res\["caveat_i18n"\] = \(\s*"([^"]+)"', src)
    assert method and frame, "the corpus-keywords method/caveat frame moved"
    _assert_keyed_x12([method.group(1), frame.group(1)])
    # The SPA's bubble (app-boot.js `ooKwStatInit`) already caches the payload; pinned so
    # the two stay the same shape.
    boot = read_static("app-boot.js")
    assert "applyTo(el, fmt(v), true)" in boot and "cache.set(term, d || {})" in boot
