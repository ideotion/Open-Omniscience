"""Batch B30 of the 2026-09-27 delegated re-walk, pinned: surfaces left in the previous
language after a live switch (L-3), the Minerals supply board (L-4), the statistics level
map's note and aggregate hovers (L-5), the World map's Stories dates and chrome (L-6), the
Governments law panels (L-7 / U-9), the calendar directory (U-3) and the bulletin list's
Open (M-12).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each was reproduced first, in Chromium. CI runs no browser, so the renderers run as real,
EXTRACTED code under node (``tests/clickthrough_b30_node_test.js``); what is a contract --
a key every locale must hold, a listener that must call a repaint, a closed vocabulary
that must have a label for every code it can hold -- is read from the source here. The
i18n gate cannot see a key that only arrives over the wire or through a variable (a
server caveat, a stored code's label), so those are listed here by name.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    event_listener_bodies,
    function_body,
    function_source,
    object_literal,
    python_function_source,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(keys, *, translated: bool = True) -> None:
    missing: list[str] = []
    for code, d in _locales().items():
        for key in keys:
            if key not in d:
                missing.append(f"{code}: {key!r}")
                continue
            want = sorted(re.findall(r"\{(\w+)\}", key))
            assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, (
                f"{code}.json changes the placeholders of {key!r}: {d[key]!r}"
            )
            if translated and code not in ("en", "de", "fr", "pt", "es", "id"):
                # Latin-script locales may legitimately keep a word ("Religion",
                # "production"); a non-Latin one never can.
                assert d[key] != key, f"{code}.json leaves {key!r} in English"
    assert not missing, "not keyed:\n" + "\n".join(missing[:40])


def _js_object_values(js: str, name: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+):\s*\"([^\"]+)\"", object_literal(js, name)))


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b30_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- L-3 / U-3: every surface localised at render repaints on a switch ------------- #


def test_the_one_langchange_listener_repaints_each_surface_the_rewalk_found_stale():
    boot = strip_comments(read_static("app-boot.js"))
    bodies = event_listener_bodies(boot, "oo:langchange")
    joined = "\n".join(bodies)
    for fn in ("_agFillCountryOptions", "repaintInsMapFromCache", "repaintOoMapDetailFromCache",
               "repaintStatAgenciesFromCache", "repaintFeedDirFromCache",
               "repaintGovViewsFromCache"):
        assert fn + "()" in joined, f"{fn} is not called from app-boot's oo:langchange listener"
    gov = function_body(read_static("app-gov-law.js"), "repaintGovViewsFromCache")
    assert_present(gov, "_govRepaintCountryPickers()",
                   why="the Governments country pickers kept English names after a switch (L-3)")


def test_the_repaints_never_fetch():
    agenda, maps, gov = read_static("app-agenda.js"), read_static("app-map.js"), read_static("app-gov-law.js")
    for js, fn in ((agenda, "_agFillCountryOptions"), (agenda, "repaintFeedDirFromCache"),
                   (maps, "repaintInsMapFromCache"), (maps, "repaintOoMapDetailFromCache"),
                   (maps, "repaintStatAgenciesFromCache"), (maps, "_insMapTables"),
                   (maps, "_renderStatAgencies"), (gov, "_govRepaintCountryPickers")):
        assert_absent(strip_comments(function_body(js, fn)), "api(",
                      why=f"{fn} runs on every language switch and must redraw from what it holds")


# --- L-4: the Minerals supply board ----------------------------------------------- #


def test_the_store_caveats_name_no_python_token_and_are_keyed():
    from src.stats import store

    # The two caveats a table PRINTS: the figures table and the Minerals supply board.
    # (map_by_area's caveat travels with the API payload; the map prints ooviz.js's.)
    src = python_function_source(Path(store.__file__).read_text(encoding="utf-8"),
                                 "list_figures", "minerals_supply_summary")
    caveats = re.findall(r'"caveat": \(\s*((?:"[^"]*"\s*)+)\)', src)
    texts = ["".join(re.findall(r'"([^"]*)"', c)) for c in caveats]
    assert len(texts) == 2, texts
    for t in texts:
        assert "None" not in t, f"a caveat names a Python token the reader never sees (L-4): {t!r}"
        assert "A missing value (—) is a published gap" in t, t
    _keyed_everywhere(texts)
    _keyed_everywhere(["No USGS supply figures stored yet — run the USGS MCS fetch (operator step)."])


def test_the_minerals_board_reads_every_word_through_t():
    body = strip_comments(function_body(read_static("app-markets.js"), "loadMineralsSupply"))
    assert_present(body, "t(d.caveat)")
    assert_present(body, "t(d.reason)")
    assert_present(body, "t(r.unit)")
    assert_present(body, 't(cap(m.replace(/_/g, " ")))')
    assert_absent(body, 'esc(d.caveat || "")')
    assert_absent(body, 'esc(r.unit || "")')


def test_every_supply_measure_the_parser_can_store_has_a_key():
    from src.stats.usgs import _SUPPLY_MEASURES

    labels = sorted({m.replace("_", " ").capitalize() for m in _SUPPLY_MEASURES.values()})
    assert labels == ["Mine production", "Net import reliance", "Production", "Reserves"], labels
    _keyed_everywhere(labels)
    _keyed_everywhere(["Rare earths", "percent", "metric tons", "metric tons REO"])


# --- L-5: the statistics level map ------------------------------------------------ #


def test_the_level_map_sentences_are_translated_where_they_are_written():
    viz = read_static("ooviz.js")
    body = strip_comments(function_source(viz, "choroplethData"))
    for s in re.findall(r'"(A level[^"]*|Coloured by comparable[^"]*)"', body):
        assert_present(body, f'_t("{s}")', why="an English sentence printed under a translated table (L-5)")
        _keyed_everywhere([s])
    assert_present(body, "root.OOI18N")
    assert_absent(body, "window.OOI18N", why="ooviz.js also runs under node, where there is no window")


def test_an_aggregate_name_goes_through_t_in_the_one_shared_cell():
    body = strip_comments(function_body(read_static("app-core.js"), "ooAreaCell"))
    assert_present(body, "t(name)", why="the level map hovered 'High income — agrégat publié' (L-5)")


# --- L-6: the World map's Stories ------------------------------------------------- #


def test_signal_dates_go_through_intl_and_the_chrome_is_keyed():
    maps = read_static("app-map.js")
    for fn in ("fmtDate", "fmtYear"):
        body = strip_comments(function_body(maps, fn))
        assert_present(body, "_tmapFmt(")
        assert_absent(body, "MON[", why="an English month array read 'Aug 17, 2027' on a French page (L-6)")
    fmt = strip_comments(function_body(maps, "_tmapFmt"))
    assert_present(fmt, "Intl.DateTimeFormat")
    assert_present(fmt, "setUTCFullYear", why="Date.UTC alone renumbers a year below 100 into the 1900s")
    detail = strip_comments(function_body(maps, "_ooMapSignalDetail"))
    for key in ("≈ country", "city", "Official / reference source ↗",
                "— co-occurrence, not a connection or cause. You judge."):
        assert_present(detail, f't("{key}")')
    _keyed_everywhere(["≈ country", "Official / reference source ↗",
                       "— co-occurrence, not a connection or cause. You judge."])


# --- L-7 / U-9: the law panels ---------------------------------------------------- #


def test_the_law_panels_key_their_words():
    gov = read_static("app-gov-law.js")
    changes = strip_comments(function_body(gov, "loadLawChanges"))
    assert_present(changes, "_lawBytes(ch.delta_bytes)")
    assert_present(changes, "_lawFlagReason")
    assert_present(changes, 't("open reader")')
    assert_absent(changes, " bytes</span>")
    docs = strip_comments(function_body(gov, "loadLawDocs"))
    assert_present(docs, 'tr("reader")')
    assert_present(docs, 'tr("official ↗")')
    assert_present(docs, '_govTf("({n} flagged)"')
    assert_present(docs, "_lawCodeLabel(_LAW_CATEGORY_LABEL, x.category)")
    assert_absent(docs, "<td>${esc(x.category)}</td>")
    assert_absent(docs, "flagged)`")
    _keyed_everywhere(["{delta} bytes", "open reader", "reader", "official ↗", "({n} flagged)"])


def test_every_law_code_the_app_can_store_has_a_keyed_label():
    gov = read_static("app-gov-law.js")
    flags = _js_object_values(gov, "_LAW_FLAG_LABEL")
    cats = _js_object_values(gov, "_LAW_CATEGORY_LABEL")
    # The law tracker flags on size alone (src/law/track.py calls flag_revision with a
    # byte delta and nothing else), so these are the two reasons it can write.
    assert set(flags) == {"large_removal", "large_addition"}
    catalog = yaml.safe_load((_ROOT / "configs" / "legal_sources.yml").read_text(encoding="utf-8"))
    # The categories live on the catalogue's DOCUMENTS (src/law/catalog.py seeds a
    # LawDocument from each, defaulting to "legislation"); its "sources" rows carry none,
    # so reading them made this guard compare {"legislation"} with itself.
    docs = catalog["documents"]
    assert docs and all(isinstance(r, dict) for r in docs), "legal_sources.yml has no documents"
    stored = {r.get("category", "legislation") for r in docs} | {"legislation"}
    assert "ip" in stored, "the catalogue read found no 'ip' document: the guard is reading the wrong list"
    assert stored <= set(cats), f"a catalogue category has no label: {stored - set(cats)}"
    _keyed_everywhere(sorted(set(flags.values()) | set(cats.values())))


# --- U-3: the calendar directory -------------------------------------------------- #


def test_the_directory_status_is_keyed_frames_and_every_kind_has_a_label():
    agenda = read_static("app-agenda.js")
    body = strip_comments(function_body(agenda, "renderFeedDir"))
    assert_present(body, '_bulTf("{feeds} feeds · {folders} folders · {checked} checked"')
    assert_present(body, '_bulTf("{n} not checked yet"')
    assert_absent(body, "feeds · ${", why="the status was one English literal (U-3)")
    assert_absent(body, "esc(f.kind)")
    kinds = _js_object_values(agenda, "_FEED_KIND_LABEL")
    feeds = yaml.safe_load((_ROOT / "configs" / "calendar_feeds.yml").read_text(encoding="utf-8"))
    stored = set(re.findall(r"^\s*kind:\s*(\S+)", (_ROOT / "configs" / "calendar_feeds.yml")
                            .read_text(encoding="utf-8"), re.M)) | {"other"}
    assert feeds, "calendar_feeds.yml did not parse"
    assert stored <= set(kinds), f"a calendar kind has no label: {stored - set(kinds)}"
    _keyed_everywhere(sorted(set(kinds.values())))
    _keyed_everywhere(["{feeds} feeds · {folders} folders · {checked} checked",
                       "{n} not checked yet", "{n} imported", "+{n} — type to filter",
                       "Movable / no fixed date"])


def test_every_family_name_the_directory_loads_reaches_the_reader_translated():
    """The rows read "Afghanistan — public holidays" in every locale (U-3, review round
    2). A holidays family is drawn from its parts -- the country's CLDR name in a keyed
    frame -- so it needs a real country code and the catalogue's standard name shape; any
    other family goes through its own key. Read through the LOADER, so a family the
    dead-host filter drops (src/events/feeds.py) is not asked for a key it never shows."""
    from src.events.feeds import load_families

    agenda = read_static("app-agenda.js")
    row = strip_comments(function_body(agenda, "renderFeedDir"))
    assert_present(row, "esc(_feedFamName(f))")
    assert_absent(row, "esc(f.name)", why="the family name was printed as the catalogue's English (U-3)")
    assert_present(strip_comments(function_body(agenda, "_feedFamName")),
                   '_bulTf("{country} — public holidays", {country: cn})')
    assert_absent(strip_comments(agenda), "a.name.localeCompare",
                  why="a translated list sorted by its English names runs in English order")
    assert_present(strip_comments(function_body(agenda, "_feedDirFiltered")), "cmp(a, b, byName)")
    fams = load_families()
    assert fams, "the calendar directory loaded no family"
    holidays = [f for f in fams if f.get("kind") == "holidays"]
    # YAML 1.1 reads a bare NO as False, which left Norway with no country at all.
    no_code = [f["key"] for f in holidays if not isinstance(f.get("country"), str)]
    assert not no_code, f"a holidays family has no country code: {no_code}"
    odd = [f["name"] for f in holidays if not f["name"].endswith(" — public holidays")]
    assert not odd, f"a holidays family's name is not in the shape the frame draws: {odd}"
    others = sorted({f["name"] for f in fams if f.get("kind") != "holidays"})
    assert others, "expected at least one non-holidays family to check"
    _keyed_everywhere(["{country} — public holidays", *others])


def test_the_new_labels_are_not_bare_lowercase_words_the_walker_would_find_in_data():
    """LESSONS 2026-09-16: the DOM walker translates ANY text node equal to a key, so a
    bare lowercase "science" or "reserves" key would also translate a corpus keyword
    spelled that way on a surface that does not opt out. This batch's labels are
    capitalised or multi-word for that reason; this pins that none slipped back."""
    agenda, gov = read_static("app-agenda.js"), read_static("app-gov-law.js")
    labels = (set(_js_object_values(agenda, "_FEED_KIND_LABEL").values())
              | set(_js_object_values(gov, "_LAW_CATEGORY_LABEL").values()))
    for w in ("science", "space", "community", "religion", "holidays", "production",
              "reserves", "legislation", "rare earths"):
        assert w not in labels
    en = _locales()["en"]
    base_new = ("science", "space", "community", "religion", "holidays", "production",
                "reserves", "legislation", "rare earths", "net import reliance")
    assert not [w for w in base_new if w in en], "a bare lowercase data-word became a key"


# --- M-12: the bulletin list's Open ----------------------------------------------- #


def test_every_edition_url_takes_its_language_from_one_helper():
    agenda = strip_comments(read_static("app-agenda.js"))
    assert_present(function_body(agenda, "bulletinOpenFile"), "_bulLang()",
                   why="Open rendered an English document on a French page (M-12)")
    assert_present(function_body(agenda, "_bulQuery"), "_bulLang()")
    assert_absent(function_body(agenda, "bulletinOpenFile"), "render?fmt=html`")
