"""Batch B18 of the 2026-09-27 delegated click-through, pinned: the data-surface tail B15
found beside its own work. The dead folder-backup plan (R1), labels that welded an English
colon (R2), the toast box used as an error line (R3) and its physical border (R4), the
Governments catalogue in the reader's language (R5), the minerals aggregate name (R6),
the statistics tables' count lines and headers (R7, R8), the import's per-item counts and
duration (R9), the export panel's counts (R10), the already-merged skip that could not
say when (R11), the world map's method line (R12), an order-dependent test (R13), and the
welded counts found on the way (R14).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced first, in Chromium where it was visible. CI runs no browser, so
the renderers run as real, EXTRACTED code under node (``tests/clickthrough_b18_node_test.js``
and the batch's additions to the export, import, diagnostics and tracked-changes suites);
what is a contract -- a key every locale must hold, a listener that must call a repaint --
is read from the source here. The i18n gate cannot see a key that only arrives over the
wire or through a variable, so those are listed here by name.
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
_LOCALES = _ROOT / "src" / "static" / "locales"
_B18_FILES = ("app-backup.js", "app-map.js", "app-diagnostics.js", "app-gov-law.js", "app-markets.js")


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(keys, *, translated: bool = False) -> None:
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
            if translated and code != "en":
                assert d[key] != key, f"{code}.json leaves {key!r} in English"
    assert not missing, "not keyed:\n" + "\n".join(missing[:40])


@pytest.mark.parametrize("suite", [
    "clickthrough_b18_node_test.js",
    "export_panel_node_test.js",
    "import_conclusion_node_test.js",
    "gate_fields_node_test.js",
    "wiki_tracked_changes_node_test.js",
])
def test_the_behaviour_runs_as_real_code_under_node(suite):
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / suite)], capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- R1: the dead folder-backup plan is gone ------------------------------------- #


def test_the_dead_folder_backup_plan_is_gone():
    """They drew into ``#fb-*`` elements no page carries, polled with a ``_fbPoll`` this
    file never declared, and reported errors through the toast box. Nothing called them."""
    src = strip_comments(read_static("app-backup.js"))
    for fn in ("folderBackupStart", "folderRestoreStart", "folderBackupAction",
               "_fbStartPoll", "_fbRefresh"):
        assert f"function {fn}(" not in src, f"{fn} is back"
    for name in ("index.html", "taskmanager.html"):
        assert 'id="fb-' not in read_static(name), f"{name} grew an #fb-* surface: re-check R1"


# --- R2: a label's colon belongs to the reader's language ------------------------- #


def test_no_b18_file_welds_a_colon_after_a_translated_label():
    """B14's welded-colon test reads the template form (``${t("X")}:``); this batch also
    found the concatenated one (``t("X") + ": "``), which reads the same on screen."""
    forms = (re.compile(r't\("([^"]+)"\)\)?\}:[\s<]'),
             re.compile(r't\("([^"]+)"\)\)?\s*\+\s*["\'`]\s*:'))
    found = []
    for name in _B18_FILES:
        src = strip_comments(read_static(name))
        for rx in forms:
            found += [(name, m.group(1)) for m in rx.finditer(src)]
    assert not found, f"a label welds its own colon: {found}"


def test_b14s_colon_test_reads_the_three_files_r2_names():
    from tests import test_clickthrough_b14_fixes as b14

    for name in ("app-backup.js", "app-map.js", "app-diagnostics.js"):
        assert name in b14._Z3_FILES, f"B14's welded-colon test does not read {name}"


# --- R3 / R4: the toast box is not an error line, and its stripe is logical -------- #


def test_the_map_panels_and_the_export_verdict_do_not_borrow_the_toast_box():
    src = strip_comments(read_static("app-map.js"))
    assert "note err" not in src, "an app-map panel still draws its error in the toast box"
    for fn in ("ingestStatSources", "dumpSearchTitles", "dumpReadPage", "dumpFtsSearch"):
        assert 'class="note' not in function_body(src, fn), f"{fn} still uses the toast box"
    body = function_body(read_static("app-backup.js"), "_uxRenderExportPanel")
    assert_absent(body, 'class="note')
    assert_present(body, 'color:var(--err)')


def test_the_note_stripe_is_on_the_inline_start_side():
    css = read_static("app.css")
    for kind in ("ok", "err", "warn"):
        m = re.search(r"\.note\." + kind + r"\s*\{([^}]*)\}", css)
        assert m, f".note.{kind} is gone"
        assert "border-inline-start" in m.group(1), f".note.{kind}: {m.group(1)}"
        assert "border-left" not in m.group(1), f".note.{kind} draws on the physical left"


# --- R5: the Governments catalogue in the reader's language ----------------------- #


def _catalogue():
    from src.stats.indicators import INDICATOR_CATALOG

    return INDICATOR_CATALOG


def test_every_catalogue_name_note_and_category_is_a_key():
    cat = _catalogue()
    assert len(cat) == 36, "the catalogue changed size: key the new names too"
    _keyed_everywhere([i["label"] for i in cat], translated=True)
    _keyed_everywhere([i["note"] for i in cat if i.get("note")], translated=True)
    js = read_static("app-gov-law.js")
    m = re.search(r"const _GOV_CAT_LABEL = \{(.*?)\};", js, re.S)
    assert m, "_GOV_CAT_LABEL is gone"
    table = {k.strip(): v for k, v in re.findall(r'"?([a-z &]+)"?\s*:\s*"([^"]+)"', m.group(1))}
    cats = {i["category"] for i in cat}
    assert cats <= set(table), f"a category with no label: {sorted(cats - set(table))}"
    _keyed_everywhere(sorted(set(table.values())), translated=True)


def test_every_catalogue_name_is_drawn_through_the_translator():
    js = strip_comments(read_static("app-gov-law.js"))
    for raw in ("esc(ind.label)", "esc(i.label)", "esc(ind.note)", "label: meta.label",
                "meta.label + ", "esc(c)}</h3>", "text-transform:capitalize"):
        assert raw not in js, f"a catalogue string is drawn raw: {raw}"
    assert_present(function_body(js, "_govIndLabel"), "_govT(s)")


def test_a_language_switch_relabels_the_pickers_and_redraws_the_map():
    body = function_body(read_static("app-gov-law.js"), "repaintGovViewsFromCache")
    assert_present(body, '_govPaintIndOptions($("gov-grp-ind"))')
    assert_present(body, '_govPaintIndOptions($("gov-map-ind"))')
    assert_present(body, "_govMapDraw(host, _govMapLast.meta, _govMapLast.data)")


# --- R6: the minerals aggregate name ------------------------------------------------ #


def test_the_minerals_area_name_goes_through_the_translator():
    body = function_body(read_static("app-markets.js"), "loadMineralsSupply")
    assert_present(body, "ooAreaCell(r.ref_area, r.area_kind, r.area_name ? t(r.area_name) : r.area_name)")


# --- R7 / R8: the statistics tables --------------------------------------------------- #


_STAT_HEADERS = ("Agency", "Series", "Area", "Period", "Value", "Unit", "SA/NSA", "Base yr",
                 "From → to", "Change in value", "Robust z", "Priors", "Revised at")


def test_the_statistics_frames_and_headers_are_keys():
    _keyed_everywhere([
        "Showing {shown} of {total} · latest vintage",
        "Flagged: {n} · robust z ≥ {z} · prior revisions ≥ {k}",
        "Could not load figures: {error}",
        "Could not check revision anomalies: {error}",
    ], translated=True)
    # Drawn through t(k) by a helper, so the gate cannot see them.
    _keyed_everywhere(_STAT_HEADERS)
    js = strip_comments(read_static("app-map.js"))
    for fn in ("loadStatFigures", "loadRevisionAnomalies"):
        body = function_body(js, fn)
        assert "<th>" not in body, f"{fn} draws a header outside the translator"
        assert "toLocaleString" not in body


def test_a_language_switch_redraws_the_statistics_tables_from_their_cache():
    boot = read_static("app-boot.js")
    listeners = [b for b in event_listener_bodies(boot, "oo:langchange")
                 if "repaintStatTablesFromCache" in b]
    assert len(listeners) == 1, "the stats repaint is not in app-boot's oo:langchange listener"
    body = function_body(read_static("app-map.js"), "repaintStatTablesFromCache")
    assert_present(body, "loadStatFigures(true)")
    assert_present(body, "loadRevisionAnomalies(true)")


# --- R9 / R10 / R11 / R14: counts as one keyed frame per number --------------------- #


_ONE_MANY = [
    ("{n} article imported", "{n} articles imported"),
    ("{n} duplicate", "{n} duplicates"),
    ("{n} conflict (your version kept)", "{n} conflicts (your version kept)"),
    ("{n} file restored", "{n} files restored"),
    ("{n} file skipped", "{n} files skipped"),
    ("{n} newsletter stored", "{n} newsletters stored"),
    ("{n} newsletter already present", "{n} newsletters already present"),
    ("{n} volume", "{n} volumes"),
    ("{n} file", "{n} files"),
    ("{n} source", "{n} sources"),
    ("{n} article", "{n} articles"),
    ("{n} mention", "{n} mentions"),
    ("{n} node", "{n} nodes"),
    ("{n} way", "{n} ways"),
    ("{n} country boundary", "{n} country boundaries"),
    ("{n} index line scanned", "{n} index lines scanned"),
    ("{n} page", "{n} pages"),
]


def test_every_count_has_its_one_and_its_many_frame():
    _keyed_everywhere([k for pair in _ONE_MANY for k in pair])
    _keyed_everywhere(["{n} s", "{n} ms", "{m} min {s} s", "{h} h {m} min"])


def test_the_per_item_row_never_welds_a_count_to_a_word():
    body = strip_comments(function_body(read_static("app-backup.js"), "_uxPerItemView"))
    for welded in ('+ t("imported")', '" " + t(', 't("imported")', 't("duplicates")'):
        assert welded not in body, f"a welded count is back: {welded}"


def test_an_already_merged_skip_carries_what_the_server_knows():
    """R11: the batch and the date, or the fact that it merged earlier in this very run."""
    _keyed_everywhere([
        "Already merged as batch {batch} on {date} — nothing new to import.",
        "Already merged earlier in this run, not yet saved — nothing new to import.",
        "Already merged — nothing new to import.",
        "nothing imported",   # inside a ternary in t(): invisible to the gate
    ], translated=True)
    js = read_static("app-backup.js")
    assert_present(function_body(js, "_uxMergedLine"), "fmtDateTime(m.at)")
    assert_present(function_body(js, "_uxImTickQueue"), "open_group: !!sm.in_open_checkpoint_group")


def test_the_queue_forwards_which_of_the_two_skips_it_was(tmp_path, monkeypatch):
    """The restore says whether the artifact was in the corpus or only in this run's
    unsaved working copy; the queue dropped that, so the row could not say which."""
    from src.backup.import_queue import ImportQueueManager

    class _Mgr:
        def start_restore(self, path, passphrase, **kw):
            pass

        def status(self):
            return {"state": "done", "summary": {
                "skipped": "already-merged", "source_digest": "d",
                "merged_as_batch": None, "merged_at": None, "in_open_checkpoint_group": True}}

        def cancel(self):
            pass

    monkeypatch.setattr("src.backup.volume_job.get_volume_manager", lambda: _Mgr())
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    q = ImportQueueManager(state_path=tmp_path / "q.json")
    out = q._run_corpus({"id": "1", "kind": "corpus", "path": "/a/1"}, hold=False)
    assert out["skipped"] == "already-merged"
    assert out["in_open_checkpoint_group"] is True


# --- R12: the world map's method line -------------------------------------------------- #


def test_the_world_maps_method_sentence_is_a_key_and_follows_a_switch():
    src = (_ROOT / "src" / "api" / "insights.py").read_text(encoding="utf-8")
    m = re.search(r'data\["method"\] = \(\s*((?:"[^"]*"\s*)+)\)', src)
    assert m, "the map-coverage method sentence moved"
    sentence = "".join(re.findall(r'"([^"]*)"', m.group(1)))
    _keyed_everywhere([sentence], translated=True)
    js = read_static("app-map.js")
    assert_present(function_body(js, "_renderOoMapDim"), "method: _ooMapPayload.method ? t(_ooMapPayload.method)")
    boot = read_static("app-boot.js")
    assert any("_renderOoMapDim()" in b for b in event_listener_bodies(boot, "oo:langchange"))


# --- R13: the reindex test brings its own Source row ------------------------------------ #


def test_the_reindex_test_never_points_at_a_source_it_did_not_create():
    """Foreign keys are ON on the shared live database, so ``source_id=1`` held only when
    an earlier test in the run happened to create a first Source."""
    src = (_ROOT / "tests" / "test_reindex_on_import.py").read_text(encoding="utf-8")
    assert "def _live_source(" in src
    # The live tests write through a session_scope `s`; the in-memory ones use `db`.
    calls = re.findall(r"_article\(s, [^\n]*", src)
    assert calls, "the live tests no longer create articles?"
    for c in calls:
        assert c.rstrip().endswith("src.id)"), f"a live article without its own source: {c}"


# --- R14: the rest of the welded counts, by file --------------------------------------- #


def test_the_r14_frames_are_keys():
    _keyed_everywhere([
        "Retry finished — new points: {n} · still failing: {k}",
        "Loading… {done} of {total}",
        "Loaded country data: {n} figure.",
        "Loaded country data: {n} figures.",
        "Showing {n} of {total} tracked revisions",
        "{n} per hour at concurrency {c} (configured {k})",
        "{count} with no country — counted, not mapped.",
    ], translated=True)


def test_no_b18_file_formats_a_user_read_date_with_the_browser_locale():
    for name in _B18_FILES:
        src = strip_comments(read_static(name))
        assert ".toLocaleString()" not in src, f"{name} formats with the browser's locale"


def test_the_import_queue_rows_write_durations_and_plurals_through_keys():
    """Found by the after-walk: the queue rows printed "3m 5s", English shorthand in
    every locale with its unit read first beside Arabic text, and the scan checklist
    welded an English "s" onto the TRANSLATED legacy-backup label."""
    js = read_static("app-backup.js")
    dur = strip_comments(function_body(js, "_uxImDur"))
    for frame in ('TF("{n} s"', 'TF("{m} min {s} s"', 'TF("{h} h {m} min"'):
        assert_present(dur, frame)
    assert "_uxDurIso(" in dur, "the queue row's duration is not isolated"
    assert "}s`" not in dur and "}m `" not in dur, "an English unit is welded again"
    code = strip_comments(js)
    assert '${n > 1 ? "s" : ""}' not in code, "an English plural s is welded onto a key"
    assert_present(code, 'n === 1 ? t("Restore legacy backup file") : t("Restore legacy backup files")')
    _keyed_everywhere(["Restore legacy backup files"], translated=True)
