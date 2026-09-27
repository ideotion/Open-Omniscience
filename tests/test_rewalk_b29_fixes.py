"""Fix batch B29 of the 2026-09-27 delegated re-walk, pinned: sources, collection, Living
sources and the search palette.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Collection targets line is keyed and redraws on a switch (O-2, S-4); the Sources pager
and the World-coverage "thin" tile are keyed frames (L-8, L-9); an open Country filter
stays inside a phone's viewport (L-10); the collection-speed knob's hover follows a switch
(T-1); both places that write the Wikipedia lane's hosts isolate each host (P-1, P-3,
U-5); the palette's two rows for one page say what each opens (P-6); a switch or a click
on a tracked page keeps the diffs the reader opened (O-3, O-6); French writes "lane" one
way, guarded by a glossary rule (O-4); and composed zh lines take the locale's own
separator (O-5).

Each lead was reproduced first, in Chromium against a seeded encrypted state. CI runs no
browser, so the behaviour runs as real, EXTRACTED code under node
(``tests/rewalk_b29_node_test.js``); what is a contract between two files -- a listener
and the painter it calls, a frame and its twelve keys, a CSS rule and the media query it
lives in -- is pinned here from the shipped sources.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import event_listener_bodies, function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(*keys: str) -> None:
    locs = _locales()
    for key in keys:
        want = sorted(re.findall(r"\{(\w+)\}", key))
        for code, d in locs.items():
            assert key in d, f"{code}.json has no key {key!r}"
            assert d[key].strip(), f"{code}.json has an empty value for {key!r}"
            assert sorted(re.findall(r"\{(\w+)\}", d[key])) == want, (
                f"{code}.json changes the placeholders of {key!r}: {d[key]!r}"
            )
            # Indonesian keeps several short labels identical to English by choice; every
            # other locale must actually translate a sentence-sized key.
            if code not in ("en", "id") and len(key) > 12 and not key.startswith("{"):
                assert d[key] != key, f"{code}.json leaves {key!r} in English"


def _langchange_bodies() -> list[str]:
    bodies = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert bodies, "no oo:langchange listener found"
    return [strip_comments(b) for b in bodies]


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "rewalk_b29_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- O-2 / S-4: the targets line ------------------------------------------------------ #

def test_the_targets_line_is_keyed_and_has_no_english_literal_left():
    _keyed_everywhere(
        "{n} source targeted",
        "{n} sources targeted",
        "{targeted} of {total} enabled · this run will process up to {n}",
        "By type",
        "By language",
        "Unknown language",
    )
    body = strip_comments(function_body(read_static("app-sources.js"), "_renderSchedTargets"))
    assert 'tf("{targeted} of {total} enabled · this run will process up to {n}"' in body
    # The welded shapes the line was built from, each an English fragment beside a number.
    for welded in ("} sources targeted</span>", "of ${t.total_enabled} enabled", "by language: ${", "by type: ${"):
        assert welded not in body, welded


def test_a_switch_redraws_the_targets_line_and_the_knob_from_what_they_hold():
    bodies = _langchange_bodies()
    assert any("_renderSchedTargets()" in b for b in bodies), (
        f"{len(bodies)} listener(s), none redraws the targets line"
    )
    assert any("_paintRateMode(_rateMode)" in b for b in bodies), (
        f"{len(bodies)} listener(s), none repaints the collection-speed knob (T-1)"
    )
    render = strip_comments(function_body(read_static("app-sources.js"), "_renderSchedTargets"))
    assert "api(" not in render, "the redraw fetches"


def test_the_knob_is_repainted_once_the_locale_is_in():
    """The boot paint can land before the locale file; it would stay English (T-1)."""
    body = strip_comments(function_body(read_static("app-sources.js"), "loadRateMode"))
    assert "OOI18N.ready" in body and "_paintRateMode(_rateMode)" in body


# --- L-8 / L-9: the pager and the thin tile -------------------------------------------- #

def test_the_pager_and_the_thin_tile_are_keyed_frames():
    _keyed_everywhere("Page {n} of {total}", "thin (<{n})", "Coverage unavailable: {error}")
    src = strip_comments(read_static("app-sources.js"))
    assert "`page ${" not in src, "the pager is an English literal again"
    assert "thin (&lt;${" not in src, "the thin tile is interpolated again"


# --- L-10: the Country list at 375 px --------------------------------------------------- #

def _phone_block(css: str, marker: str) -> str:
    """The @media (max-width:600px) block that holds ``marker``."""
    at = css.index(marker)
    start = css.rindex("@media (max-width:600px)", 0, at)
    depth, i = 0, css.index("{", start)
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[start : j + 1]
    raise AssertionError("unbalanced media block")


def test_an_open_filter_list_spans_the_filter_row_on_a_phone():
    css = read_static("app.css")
    block = _phone_block(css, ".src-filter-row .msel .msel-list")
    assert re.search(r"\.src-filter-row \{ position:relative; \}", block), "the row is not the containing block"
    assert re.search(r"\.src-filter-row \.msel \{ position:static; \}", block)
    found = re.search(r"\.src-filter-row \.msel \.msel-list \{([^}]*)\}", block)
    assert found, "the open list has no phone rule"
    rule = found.group(1)
    assert "left:0" in rule and "right:0" in rule and "min-width:0" in rule, rule
    assert re.search(r"\.src-filter-row \.msel-opt \{ white-space:normal; \}", block)


# --- P-1 / P-3 / U-5: the host line ----------------------------------------------------- #

def test_both_places_that_write_the_wikipedia_hosts_isolate_each_host():
    wiz = function_body(read_static("app-sources.js"), "_wizPaintHosts")
    bubble = function_body(read_static("app-core.js"), "_laneHostTitle")
    for name, body in (("_wizPaintHosts", wiz), ("_laneHostTitle", bubble)):
        code = strip_comments(body)
        assert re.search(r'"(\\u2066|⁦)" \+ h \+ "(\\u2069|⁩)"', code), (
            f"{name} writes the hosts without a left-to-right isolate"
        )


# --- P-6: the palette's Wikipedia rows -------------------------------------------------- #

def test_the_palette_rows_say_what_they_open():
    _keyed_everywhere("Local copy", "Tracked changes")
    body = strip_comments(function_body(read_static("app-shell.js"), "_omniItems"))
    assert 't("Local copy")' in body and 't("Tracked changes")' in body
    assert "openWikiTC(it.page_id" in body, "the tracked row does not open the tracked changes"


# --- O-3 / O-6: open diffs survive -------------------------------------------------------- #

def test_a_switch_redraws_living_sources_from_cache_and_never_re_reads_it():
    bodies = _langchange_bodies()
    living = [b for b in bodies if "repaintLivingFromCache()" in b]
    assert living, f"{len(bodies)} listener(s), none repaints Living sources from cache"
    for b in bodies:
        assert "showLivingView(" not in b, "a switch re-reads Living sources and collapses its open diffs"
        assert "loadWikiTC()" not in b, "a switch re-reads the tracked page's history"
    assert any("repaintWikiTCFromCache()" in b for b in bodies)
    for name, src in (("repaintLivingFromCache", "app-living.js"), ("repaintWikiTCFromCache", "app-map.js")):
        assert "api(" not in strip_comments(function_body(read_static(src), name)), f"{name} fetches"


def test_a_tracked_page_click_on_the_wiki_panel_does_not_reselect_it():
    body = strip_comments(function_body(read_static("app-map.js"), "openWikiTC"))
    assert "if (opened && !showing) _livingSubtabs.select(\"wiki\")" in body


# --- O-4: one French term for "lane" ---------------------------------------------------- #

def test_french_writes_lane_one_way():
    import scripts.i18n_report as rep

    assert rep.glossary_violations() == []
    fr = _locales()["fr"]
    assert fr["Lane"] == "Voie", "the Storage header reads 'FILE' again"
    lane_keys = [k for k in fr if k != "_meta" and re.search(r"\blanes?\b", k, re.I)]
    assert len(lane_keys) >= 30, "the lane keys went missing, so the guard below guards nothing"


def test_the_glossary_guard_catches_a_second_term(tmp_path, monkeypatch):
    """A mutant, so the guard is known to bite: one lane value back to 'file'."""
    import scripts.i18n_report as rep

    fr = json.loads((_LOCALES / "fr.json").read_text(encoding="utf-8"))
    fr["Lane"] = "File"
    fr["The lane's settings could not be read."] = "Les paramètres n'ont pas pu être lus."
    (tmp_path / "fr.json").write_text(json.dumps(fr, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rep, "_LOCALES", tmp_path)
    bad = {(r["key"], r["why"]) for r in rep.glossary_violations()}
    assert ("Lane", "uses the term this locale ruled out") in bad
    assert ("The lane's settings could not be read.", "lacks the chosen term") in bad
    assert len(bad) == 2
    assert rep.main(["--glossary"]) == 1


# --- O-5: the reader's own separator ------------------------------------------------------ #

# Every shape that welds a Latin space or colon onto a translated label or sentence. The
# first round's guard matched only 't("Failed:") + " "' and 't("Could not load") + ": "',
# so it could not see the twenty-odd other welds in the same files (the reviewer's O-5
# finding); these four cover the concatenated and the template-literal forms.
_WELDS = {
    "a colon label, then a space": re.compile(r't\("[^"]*[:\uff1a]"\)\s*\+\s*" "'),
    "a colon label, then a space (template)": re.compile(r'\$\{(?:esc\()?t\("[^"]*[:\uff1a]"\)\)?\} '),
    "a label, then a welded colon": re.compile(
        r'(?:t\("[^"]*"\)|esc\(t\("[^"]*"\)\))\s*\+\s*": "|\$\{(?:esc\()?t\("[^"]*"\)\)?\}:[ <]'),
    "a sentence, then a space and more": re.compile(
        r'\$\{(?:esc\()?t\("[^"]*[.\u3002]"\)\)?\} \$\{|t\("[^"]*[.\u3002]"\)\s*\+\s*" "\s*\+\s*(?:t\(|esc\(t\()'),
}
# The files this batch swept whole. app-shell.js's one weld is B24's (N-5), app-boot.js's
# two sit in B24's range, and app-map.js's in B20's and B30's -- handed to them, not
# silently left out.
_SWEPT = ("app-core.js", "app-settings.js", "app-living.js", "app-sources.js")

_O5_LABELS = (
    "Failed", "Last run failed", "This machine, read at boot", "This machine, read just now",
    "Could not prepare the installer", "Error", "Could not determine the default model",
    "Download failed", "Model info unavailable", "Active model set", "Could not set the active model",
    "Remove failed", "Compaction failed", "Pull failed", "Storage could not be read", "Not saved",
    "Top country", "Another job is writing to the database", "Import failed", "Licence",
    "floor", "First cited by", "Discovery",
)
_O5_FRAMES = (
    "Your budgets can still take {room}; the drive has {free} free. That is more than the drive has free.",
    "Done. {stored} labelled · {none} unclear · {total} scanned",
    "Last run: {stored} labelled · {none} unclear · {total} scanned",
    "Compacted. Space freed: {freed} · {secs} s",
    "{n} imported newsletters removed. Re-import the cleaned files to replace them.",
    "Anonymisation: {redacted} recipient echoes redacted, {stripped} tracker tokens stripped, "
    "{flagged} tracker wrappers flagged.",
    "AI check: {checked} checked — {articles} read as articles, {junk} as navigation soup, "
    "{unreadable} unreadable — a proposal only; nothing about this source was changed.",
)


def _welds(src: str) -> list[str]:
    return [f"{what}: {m.group(0)!r}" for what, rx in _WELDS.items() for m in rx.finditer(src)]


def test_no_welded_label_or_sentence_is_left_in_the_files_this_batch_swept():
    _keyed_everywhere(*_O5_LABELS, *_O5_FRAMES)
    for name in _SWEPT:
        left = _welds(strip_comments(read_static(name)))
        assert not left, f"{name} still welds a separator onto translated text: {left}"


def test_the_weld_scan_bites():
    """A mutant per shape, so the guard above is known to see each one."""
    for mutant in ('t("Download failed:") + " " + e.message',
                   '`${esc(t("Import failed:"))} ${esc(e.message)}`',
                   '`${t("AI check")}: ${n}`',
                   '`<strong>${esc(t("Discovery"))}:</strong> `',
                   '`${t("Done.")} ${n} labelled`'):
        assert _welds(mutant), f"the scan misses {mutant}"
    assert not _welds('ooLabelText(t("Download failed"), e.message)')


def test_the_composed_zh_and_ja_lines_put_no_latin_space_after_full_width_marks():
    locs = _locales()
    for code in ("zh", "ja"):
        for key in _O5_FRAMES:
            val = locs[code][key]
            assert not re.search(r"[\u3002\uff1a\uff0c] ", val), f"{code} {key!r}: {val!r}"
    zh = locs["zh"]
    joined = zh["Your budgets can still take {room}; the drive has {free} free. That is more than the drive has free."]
    assert "\u3002 " not in joined and "\u3002\u8fd9" in joined, joined


def test_the_swept_sites_call_the_frames():
    settings = strip_comments(read_static("app-settings.js"))
    poll = strip_comments(function_body(read_static("app-settings.js"), "pollLangDetect"))
    assert 'tf("Done. {stored} labelled' in poll and 'tf("Last run: {stored} labelled' in poll
    assert 'tf("Compacted. Space freed: {freed}' in settings
    assert settings.count("esc(_nlAnonLine(tl))") == 2, "both newsletter paths share the one keyed tally"
    assert "{n} imported newsletters removed. Re-import" in settings
    core = strip_comments(function_body(read_static("app-core.js"), "arbitrate"))
    assert 'ooLabelText(t("Another job is writing to the database"), busy)' in core
