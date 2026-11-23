"""Row 347: empty states never send the reader to a control that no longer exists.

Invariant #21 removed the "Index corpus" button (indexing follows ingest), but seven
empty states still told the reader to "index the corpus", and the map one pointed at a
repository script (scripts/build_city_gazetteer.py) nobody can run from the app. The
Insights trend one was also English-only: it was split across text nodes around the
term, so no locale key ever matched it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"
LOCALES = STATIC / "locales"

TREND_KEY = (
    "No indexed mentions of “{term}” yet. Articles are indexed on their own as they "
    "arrive: try another term, or look again after the next collection."
)
NEW_KEYS = [
    TREND_KEY,
    "No mentions over time yet. Articles are indexed on their own as they arrive.",
    "Nothing yet. Articles are indexed on their own as they arrive.",
    "No families yet. Articles are indexed on their own as they arrive.",
    "No entity families yet. Articles are indexed on their own as they arrive.",
    "The city list was not computed this time, so no city is drawn: that is not the "
    "same as no city being mentioned.",
    "No cities placed yet: no mention in this window comes from a source with a city the "
    "map can locate. Cities appear on their own as such articles are indexed.",
    "No data yet: no mention in this window comes from a source with a country or city. "
    "Rows appear on their own as such articles are indexed.",
]


def _js() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in STATIC.glob("*.js")}


def test_no_ui_string_tells_the_reader_to_index_the_corpus():
    dead = re.compile(r"index the corpus|build_city_gazetteer", re.I)
    hits = []
    for name, src in _js().items():
        for n, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if dead.search(line):
                hits.append(f"{name}:{n}")
    assert not hits, f"dead advice still rendered: {hits}"
    for f in LOCALES.glob("*.json"):
        assert not [k for k in json.loads(f.read_text(encoding="utf-8")) if dead.search(k)], f.name


def test_every_new_key_is_in_all_twelve_locales_and_used():
    files = sorted(LOCALES.glob("*.json"))
    assert len(files) == 12
    blob = "\n".join(_js().values())
    for key in NEW_KEYS:
        assert key in blob, f"key not rendered anywhere: {key[:50]}"
        for f in files:
            val = json.loads(f.read_text(encoding="utf-8")).get(key)
            assert val, f"{f.name} lacks {key[:50]}"
            if key == TREND_KEY:
                assert "{term}" in val, f"{f.name} drops the {{term}} placeholder"


def test_trend_message_is_one_keyed_sentence_with_the_term_as_data():
    src = (STATIC / "app-corpus.js").read_text(encoding="utf-8")
    i = src.index("Row 347: one keyed sentence")
    block = src[i : src.index("return;", i)]
    assert TREND_KEY in block, "the message must go through tf() with its locale key"
    assert '<span translate="no">${esc(term)}</span>' in block, "the term stays data"
    assert "data-i18n-dyn" in block, "the walker must not re-key a pre-translated sentence"
    # a language switch re-runs exploreTerm for this host, so the sentence follows it
    assert '["ins-trend", "exploreTerm", {repaint: true}]' in src


def test_a_skipped_city_list_is_not_drawn_as_an_empty_one():
    src = (STATIC / "app-map.js").read_text(encoding="utf-8")
    assert "function buildMapSvg(cities, citiesSkipped)" in src
    assert (
        'buildMapSvg(d.cities || [], !!(d.partial && (d.skipped || []).includes("cities")))' in src
    )
