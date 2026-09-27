"""Batch B14 of the 2026-09-26 delegated click-through, pinned: leads earlier fix batches
found beside their own work. Numbers through the ruled formatter (Z1), size panels
repainted on a language switch (Z2), the locale's own "label: value" separator (Z3), the
Governments group aggregates keyed from codes with a whole-series refusal said once (Z4),
the Quality gates criteria keyed and labelled (Z5), two orphan keys removed (Z7), the main
app following a language picked in another tab (Z8) and a dead task-manager rule (Z10).
Z9 (the data-folder probe's own clean-up) is pinned in tests/test_data_location.py.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced first. CI runs no browser, so the behaviour runs as real,
EXTRACTED code under node (``tests/clickthrough_b14_node_test.js``); what is a contract
between two files (the aggregation engine's English and the frames the screen draws, the
gates payload and the locale files) is pinned here from the shipped sources themselves.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    event_listener_bodies,
    function_body,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_LOCALES = _STATIC / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(key: str) -> None:
    for code, d in _locales().items():
        assert key in d, f"{code}.json has no key {key!r}"
        want = sorted(re.findall(r"\{(\w+)\}", key))
        assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, (
            f"{code}.json changes the placeholders of {key!r}: {d[key]!r}"
        )


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b14_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- Z1: numbers through fmtNum, never the browser's locale ----------------------- #

#: Files another agent owned while this batch ran, or that cannot reach the formatter,
#: each with its reason. A number there is still a known gap, not a ruled exception.
_Z1_NOT_SWEPT = {
    "app-map.js": "the map statistics tables were another batch's region",
    "app-backup.js": "the import dialog (and the Insights header's animateCount) were another batch's file",
    "app-diagnostics.js": "the re-index panels were another batch's file",
}
#: The only toLocaleString() calls left in the swept files: each formats a DATE, whose
#: locale is the reader's clock, not the number convention.
_Z1_DATE_CALLS = {
    "app-markets.js": ["return isFinite(+d) ? d.toLocaleString() : String(iso);"],
    "app-shell.js": ["} catch (e) { return d.toLocaleString(); }"],
}


def test_user_read_numbers_never_go_through_to_locale_string():
    """toLocaleString() reads the BROWSER's locale, which the app's language switcher never
    changes: a French strip under an English browser read "6,402". The ruled formatter is
    fmtNum (Latin digits, a decimal point, U+202F grouping) in every locale."""
    offenders: dict[str, list[str]] = {}
    for path in sorted(_STATIC.glob("app-*.js")):
        if path.name in _Z1_NOT_SWEPT:
            continue
        lines = [ln.strip() for ln in strip_comments(path.read_text(encoding="utf-8")).splitlines()
                 if ".toLocaleString(" in ln]
        allowed = _Z1_DATE_CALLS.get(path.name, [])
        bad = [ln for ln in lines if ln not in allowed]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"numbers formatted by the browser's locale: {offenders}"


def test_the_home_strip_counts_use_fmt_num():
    home = read_static("app-home.js")
    for fn in ("homeSourceSplitHover", "renderHomeStats", "renderCorpusTier"):
        body = function_body(home, fn)
        assert_present(body, "fmtNum(", why=f"{fn} renders a user-read count")
        assert_absent(strip_comments(body), "toLocaleString(")


# --- Z2: sizes repainted on a language switch, from cache ------------------------- #


def test_the_size_panels_repaint_on_a_language_switch_without_a_fetch():
    """Every size on Settings -> Storage and the Library overview tiles is written with its
    unit translated at render ("35.6 MB" / "35.6 Mo"), so the DOM walker could not repaint
    it and the panel kept the old locale while it stayed open."""
    boot = read_static("app-boot.js")
    listeners = "\n".join(event_listener_bodies(boot, "oo:langchange"))
    for fn in ("repaintLaneStorageFromCache", "repaintLibraryOverviewFromCache"):
        assert_present(listeners, f"{fn}()", why="the ONE oo:langchange listener must call it")
    settings = read_static("app-settings.js")
    body = function_body(settings, "repaintLaneStorageFromCache")
    assert_absent(body, "api(", why="a language switch must never refetch")
    assert_present(function_body(settings, "loadLaneStorage"), "_laneStorageLast = rep;")
    lib = read_static("app-library.js")
    assert_absent(function_body(lib, "repaintLibraryOverviewFromCache"), "api(")
    assert_present(function_body(lib, "renderLibraryOverview"), "_libOvLast = {d, fig};")


# --- Z3: the locale's own separator ------------------------------------------------ #

#: Surfaces the click-through walked (Home, Library, Settings, the task manager,
#: Insights, the Quality gates panel), where a ": " was welded after a t() label.
_Z3_FILES = ("app-home.js", "app-library.js", "app-settings.js", "app-insights.js",
             "app-ai-tools.js", "app-core.js", "taskmanager.html")
#: Left, each in a region another batch owned while this one ran.
_Z3_LEFT = {
    ("app-home.js", "Trending now"): "the Trends strip was the keyword batch's region",
    ("app-ai-tools.js", "app folder, not in use"): "the model-store sizes were the import batch's region",
}


def test_no_label_on_a_walked_surface_welds_its_own_colon():
    """"seuil absolu: 0.5", "Privé (local ; …): 12 Go": a colon welded after t() is the
    English separator in every language. French puts a space before it; Chinese and
    Japanese write a full-width one."""
    welded = re.compile(r't\("([^"]+)"\)\)?\}:[\s<]')
    found = []
    for name in _Z3_FILES:
        src = strip_comments(read_static(name))
        for m in welded.finditer(src):
            if (name, m.group(1)) not in _Z3_LEFT:
                found.append((name, m.group(1)))
    assert not found, f"a label welds its own colon: {found}"


def test_the_separator_is_one_keyed_frame_every_locale_states():
    core = read_static("app-core.js")
    for fn in ("ooLabelHtml", "ooLabelText"):
        assert_present(function_body(core, fn), 'tf("{prefix}: {text}"')
    _keyed_everywhere("{prefix}: {text}")
    loc = _locales()
    assert loc["fr"]["{prefix}: {text}"] == "{prefix} : {text}"
    assert loc["zh"]["{prefix}: {text}"] == "{prefix}：{text}"
    assert loc["ja"]["{prefix}: {text}"] == "{prefix}：{text}"
    lib = read_static("app-library.js")
    body = function_body(lib, "_sfPaint")
    assert_present(body, 'ooLabelHtml(esc(t("Private (local; corpus encrypted at rest)"))')
    assert_present(body, 'ooLabelHtml(esc(t("Re-downloadable (dumps / maps / models)"))')


# --- Z4: group aggregates in the reader's language --------------------------------- #


def _gov_body() -> str:
    return function_body(read_static("app-gov-law.js"), "_govGroupHtml")


def _frame(pattern: str) -> str:
    m = re.search(pattern, _gov_body())
    assert m, f"no frame matching {pattern!r} in _govGroupHtml"
    return m.group(1)


def _agg(code: str, members, weights=None, allow_incomplete=False):
    from src.stats.aggregate import Member, aggregate_indicator
    from src.stats.indicators import indicator_aggregation, indicator_meta

    return aggregate_indicator(
        indicator=indicator_meta(code), aggregation=indicator_aggregation(code),
        members=[Member(a, v) for a, v in members], weights=weights,
        allow_incomplete=allow_incomplete,
    )


_FULL = [("fr", 1.0), ("de", 2.0), ("it", 4.0)]
_POP = {"fr": 68.0, "de": 84.0, "it": 59.0}


def test_every_aggregate_result_carries_a_code_the_screen_can_key():
    cases = [
        _agg("SI.POV.GINI", _FULL),                                   # no aggregate at all
        _agg("NY.GDP.PCAP.CD", [(a, None) for a, _ in _FULL]),         # nobody reported
        _agg("NY.GDP.PCAP.CD", _FULL[:2] + [("it", None)]),            # partial roster
        _agg("NY.GDP.PCAP.CD", _FULL, {"population": _POP}),           # intensive, exact
        _agg("NY.GDP.PCAP.CD", _FULL, {"population": {"fr": 1.0}}),    # a missing weight
        _agg("NY.GDP.PCAP.CD", _FULL, {"population": dict.fromkeys(_POP, 0.0)}),
        _agg("SP.POP.TOTL", _FULL),                                    # extensive
    ]
    for out in cases:
        for key, r in out["strategies"].items():
            assert r.get("label"), f"{key}: no label, so the screen would print the key"
            if "refused" in r:
                assert r.get("refused_code"), f"{key}: a refusal with no code: {r['refused']!r}"
            else:
                assert r.get("method_code"), f"{key}: a method with no code: {r['method']!r}"
                if r["method_code"].startswith("weighted"):
                    assert r.get("weight"), f"{key}: a weighted method that does not name its weight"


def test_the_screen_frames_say_exactly_what_the_engine_says_in_english():
    """Each code is redrawn as a keyed frame from the payload's numbers; filled with the
    engine's own values the English frame must BE the engine's sentence, or the screen
    and an API caller would disagree about what was computed."""
    lit = lambda code: _frame(rf'case "{code}": return t\("([^"]+)"\)')  # noqa: E731
    tfr = lambda code: _frame(rf'case "{code}": return _govTf\("([^"]+)"')  # noqa: E731
    meth = lambda code: _frame(rf'r\.method_code === "{code}"\) s = t\("([^"]+)"\)')  # noqa: E731

    assert _agg("NY.GDP.PCAP.CD", [(a, None) for a, _ in _FULL])["strategies"]["mean"]["refused"] \
        == lit("no_data")
    full = _agg("NY.GDP.PCAP.CD", _FULL, {"population": _POP})["strategies"]
    assert full["sum"]["refused"] == lit("intensive")
    assert full["mean"]["method"] == meth("members")
    assert full["median"]["method"] == meth("median")
    exact = _frame(r'r\.method_code === "weighted_exact"\) \{\s*s = _govTf\("([^"]+)"')
    assert full["population_weighted"]["method"] == exact.replace("{weight}", "population")
    assert full["gdp_weighted"]["refused"] == tfr("no_weight_series").replace("{weight}", "gdp")
    assert full["labour_force_weighted"]["refused"] == (
        tfr("no_weight_series").replace("{weight}", "labour force"))

    approx_per = _frame(r'r\.denominator\s*\?\s*_govTf\("([^"]+)"')
    trade = _agg("NE.TRD.GNFS.ZS", _FULL, {"population": _POP})["strategies"]
    assert trade["population_weighted"]["method"] == (
        approx_per.replace("{weight}", "population").replace("{denominator}", "gdp"))
    approx_none = _frame(r':\s*_govTf\("([^"]+)", \{weight: w\}\);\s*\} else return r\.method')
    cpi = _agg("FP.CPI.TOTL.ZG", _FULL, {"population": _POP})["strategies"]
    assert cpi["population_weighted"]["method"] == approx_none.replace("{weight}", "population")

    total = _agg("SP.POP.TOTL", _FULL)["strategies"]["sum"]
    assert total["method"] == meth("sum")

    miss = _agg("NY.GDP.PCAP.CD", _FULL, {"population": {"fr": 1.0}})["strategies"]["population_weighted"]
    assert miss["refused"] == (tfr("missing_weight").replace("{n}", "2").replace("{weight}", "population")
                               .replace("{who}", "de, it"))
    zero = _agg("NY.GDP.PCAP.CD", _FULL, {"population": dict.fromkeys(_POP, 0.0)})["strategies"]
    assert zero["population_weighted"]["refused"] == tfr("zero_weight").replace("{weight}", "population")

    partial = _frame(r'_govTf\("(PARTIAL:[^"]+)"')
    part = _agg("NY.GDP.PCAP.CD", _FULL[:2] + [("it", None)], allow_incomplete=True)["strategies"]["mean"]
    assert part["method"] == meth("members") + " " + (
        partial.replace("{reported}", "2").replace("{members}", "3").replace("{missing}", "1"))


def test_the_engine_vocabulary_is_a_key_in_all_twelve():
    from src.api.governments import _CAVEAT
    from src.stats.aggregate import STRATEGIES
    from src.stats.indicators import indicator_aggregation

    body = _gov_body()
    frames = re.findall(r'(?:\bt|_govTf)\("([^"]*\s[^"]*)"', body)
    assert len(frames) >= 15, f"the frame walk found only {len(frames)} -- is it reading the renderer?"
    for key in frames:
        _keyed_everywhere(key)
    for _k, label, _w in STRATEGIES:
        _keyed_everywhere(label)
    for weight in ("population", "GDP", "labour force"):
        _keyed_everywhere(weight)
    _keyed_everywhere(indicator_aggregation("SI.POV.GINI")["no_aggregate"])
    _keyed_everywhere(_agg("SP.POP.TOTL", _FULL)["caveat"])
    _keyed_everywhere(_CAVEAT)
    assert_present(body, "const label = r.label ? t(r.label) : k;")
    assert_present(body, 'esc(agg.caveat ? t(agg.caveat) : "")')


def test_a_whole_series_refusal_is_drawn_once_above_the_cards():
    body = _gov_body()
    assert_present(body, 'const whole = new Set(["incomplete", "no_data", "no_aggregate"]);')
    assert_present(body, "sharedLine + override")
    assert_present(body, 't("Not computed: the reason is stated above the cards.")')
    _keyed_everywhere("Not computed: the reason is stated above the cards.")


def test_the_group_cards_follow_a_language_switch_from_cache():
    """Once the cards are drawn in the reader's language they must follow a switch:
    measured in Chromium, fr -> ar kept the French cards until the next selection."""
    boot = read_static("app-boot.js")
    listeners = "\n".join(event_listener_bodies(boot, "oo:langchange"))
    assert_present(listeners, "repaintGovGroupFromCache()")
    gov = read_static("app-gov-law.js")
    assert_absent(function_body(gov, "repaintGovGroupFromCache"), "api(")
    assert_present(function_body(gov, "renderGovGroup"), "_govGrpLast = {d, allowIncomplete};")


# --- Z5: the Quality gates criteria ------------------------------------------------ #


@pytest.fixture
def _empty_db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'q.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_every_criterion_has_a_readers_name():
    from src.analytics.source_audit import CRITERIA
    from src.api.source_management import _CRITERION_LABELS

    names = {c["name"] for c in CRITERIA}
    assert names == set(_CRITERION_LABELS), (
        f"criteria without a reader's name: {names - set(_CRITERION_LABELS)}; "
        f"names for criteria that no longer exist: {set(_CRITERION_LABELS) - names}"
    )


def test_every_criterion_sentence_the_payload_declares_is_a_key_in_all_twelve(_empty_db):
    """The criteria rendered their raw ids ("pathology_rate") as names and their English
    descriptions and floor notes under every language."""
    from src.api import source_management as sm

    payload = sm.qualification_config(db=_empty_db)
    strings: list[str] = []
    for x in payload["criteria"]:
        strings += [x["label"], x["desc"], *x["absolute_floor_note_parts"]]
    assert len(strings) >= 15, f"the criteria walk read only {len(strings)} strings"
    assert any(x["absolute_floor_note_parts"] for x in payload["criteria"]), "no floor note at all?"
    for s in strings:
        _keyed_everywhere(s)
    for x in payload["criteria"]:
        assert x["absolute_floor_note"] == (" ".join(x["absolute_floor_note_parts"]) or None), (
            "the joined note (for older pages) and its sentences must say the same thing"
        )


def test_the_panel_renders_the_name_the_description_and_the_floor_through_t():
    js = read_static("app-ai-tools.js")
    load = function_body(js, "loadQualificationGates")
    assert_present(load, "esc(x.label ? t(x.label) : x.name)")
    assert_present(load, "ooLabelText(x.name, t(x.desc || \"\"))")
    assert_present(load, 'ooLabelText(t("absolute floor"), x.absolute_floor)')
    assert_present(load, "x.absolute_floor_note_parts")
    assert_absent(load, '`${t("absolute floor")}: ${x.absolute_floor}`')


# --- Z7: orphan keys ----------------------------------------------------------------- #

_ORPHANS = (
    "Local AI is offline — start Ollama (and turn airplane mode off) for tentative translations.",
    "Stop the Wikipedia stream",
)


def test_the_orphan_keys_are_gone_and_nothing_renders_them():
    for code, d in _locales().items():
        for key in _ORPHANS:
            assert key not in d, f"{code}.json still carries the orphan key {key!r}"
    for path in list(_STATIC.glob("*.js")) + list(_STATIC.glob("*.html")):
        src = path.read_text(encoding="utf-8")
        for key in _ORPHANS:
            assert key not in src, f"{path.name} renders {key!r}, so it was not an orphan"


# --- Z8: a language picked in another tab -------------------------------------------- #


def test_the_main_app_follows_a_language_picked_in_another_tab():
    """The `storage` event fires only in the origin's OTHER tabs, so a language picked in a
    second window or on /tasks reached this tab's shared key and never its screen, until a
    reload. /tasks already carried this listener; the main app did not. (event_listener_
    bodies reads `document` listeners only; `storage` is dispatched on `window`.)"""
    core = strip_comments(read_static("app-core.js"))
    at = core.find('window.addEventListener("storage"')
    assert at != -1, "the main app has no storage listener"
    body = core[at:core.find("});", at) + 3]
    assert_present(body, 'e.key !== "oo.lang"')
    assert_present(body, "pickLang(e.newValue)")


# --- Z10: the task-manager page's dead header rule ------------------------------------ #


def test_the_task_manager_page_carries_no_dead_header_rule():
    """The header is the app's own sticky strip now (a comment on the page says so); three
    `.tm-head` rules styled an element nothing renders."""
    tm = read_static("taskmanager.html")
    assert not re.search(r"\.tm-head\b[^{}\n]*\{", tm), "a .tm-head rule is back"
    assert "tm-head" not in "".join(re.findall(r'class="([^"]*)"', tm)), (
        "an element carries .tm-head again -- then the rule is not dead; restore it")
