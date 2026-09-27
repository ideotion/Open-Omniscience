"""The 2026-09-26 click-through's leftovers (batch B13, Y1-Y12), pinned.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced in Chromium first and checked there after. CI runs no browser,
so these tests pin the mechanism each fix relies on; the behavioural halves run as real
code under node:

* ``tests/import_conclusion_node_test.js`` -- Y1 (the result block at 375 px), Y4 (the
  awaiting-indexing figure is the server's backlog) and a per-item Y9 error;
* ``tests/import_stages_node_test.js`` -- Y3 (the re-index counts) and Y7 (the "Last
  import" line reads only finished runs);
* ``tests/import_tail_phase_node_test.js`` -- Y2/Y9 (a queue row's error line).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import (
    app_js,
    assert_absent,
    assert_present,
    event_listener_bodies,
    function_body,
    function_source,
    read_static,
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _keyed_everywhere(*keys: str) -> None:
    for loc, data in _locales().items():
        for k in keys:
            assert data.get(k), f"{loc}.json has no value for {k[:60]!r}"
            for slot in re.findall(r"\{\w+\}", k):
                assert slot in data[k], f"{loc}.json dropped {slot} from {k[:60]!r}"


# --- Y2: the import dialog's inline lines are not the toast box ---------------- #


def test_the_dialogs_notes_are_caveat_lines_not_toasts():
    html = read_static("index.html")
    for note_id in ("ux-imp-checkpoint", "ux-imp-trust-note"):
        tag = re.search(r'<[^>]*id="' + note_id + r'"[^>]*>', html)
        assert tag, f"#{note_id} is gone -- re-point this test"
        assert 'class="card-caveat"' in tag.group(0), tag.group(0)
        assert 'class="note' not in tag.group(0), tag.group(0)


def test_the_dialogs_error_spans_are_not_toasts():
    js = app_js()
    for name in ("_uxImLastLineHtml", "_uxImHistoryHtml", "loadImportHistory",
                 "_uxImVerify", "_uxImRun", "_uxImRenderQueue"):
        assert_absent(function_body(js, name), 'class="note', why=name)
    assert_present(function_body(js, "_uxImRenderQueue"), "color:var(--err)")


# --- Y5 / Y6: the finished run reaches the other surfaces and every language --- #


def test_a_finished_run_refreshes_the_last_line_and_an_open_history():
    body = function_body(app_js(), "_uxImTickQueue")
    assert_present(body, "_uxImLastLine();")
    assert_present(body, 'const h = document.getElementById("imp-history");')
    assert_present(body, "if (h && h.innerHTML.trim()) loadImportHistory();")
    # the result block keeps what it was drawn from, for a language switch to redraw
    assert_present(body, "_uxImSummaryArgs = {")


def test_a_language_switch_redraws_the_whole_run_and_its_result():
    hits = [b for b in event_listener_bodies(app_js(), "oo:langchange") if "_uxImCheckpointNote" in b]
    assert len(hits) == 1, f"{len(hits)} import-dialog language listener(s) found"
    body = hits[0]
    assert_present(body, "_uxImRenderQueue(_uxImLastStatus);")
    assert_present(body, "_renderImportSummary(sh, _uxImSummaryArgs.summaries, _uxImSummaryArgs.run);")


# --- Y8: the ungrouped view names the order the list is really in ------------- #


def test_the_ungrouped_label_follows_the_sort():
    body = function_body(app_js(), "_anGroupByLangControl")
    assert_present(body, 'byDate ? t("Interleave by date") : t("Interleave languages")')
    assert_present(body, 'sb.value === "date"')
    assert_present(body, "!_anKwSort")
    _keyed_everywhere("Interleave languages", "Interleave by date")


# --- Y9: sizes through the one writer, server sentences through keyed frames --- #


def test_hardware_and_memory_sizes_go_through_the_one_writer():
    js = app_js()
    chips = function_body(js, "_hwChips")
    assert_absent(chips, '" GB"')
    assert chips.count("_sizeText(") == 2
    models = function_body(js, "loadLlmModels")
    assert_absent(models, "GB RAM detected`")
    assert_absent(models, '+ " GB"')
    assert_present(models, 'tf("{size} RAM detected"')
    forensics = function_body(js, "_renderSessionForensics")
    assert_absent(forensics, '" MB RSS"')
    assert_absent(forensics, '" MB "')
    assert_present(forensics, '_tf("{size} available"')
    erase = function_body(js, "secureErase")
    assert_absent(erase, "MiB")
    plan = function_body(js, "folderBackupPlan")
    assert_absent(plan, "needed_human")
    assert_absent(plan, "free_human")
    vitals = function_body(js, "_renderVitals")
    assert_present(vitals, 't9("Memory")')
    assert_present(vitals, 't9("Scraping ↓")')
    assert_present(vitals, 'tf("total {size}"')
    assert_absent(vitals, "· total ${")
    _keyed_everywhere("{size} RAM detected", "{size} available", "Scraping ↓", "total {size}", "Memory")


_SPACE_FRAME = (
    "{what}: not enough free space — needs about {needed}, only {free} free at {path}. "
    "Free up space or choose another location, or use the large-data/volume backup for a big corpus."
)
_FOLDER_FRAME = "Not enough free space at {path}: needs {needed}, only {free} free."


def test_the_free_space_frames_are_keyed_everywhere():
    _keyed_everywhere(_SPACE_FRAME, _FOLDER_FRAME, "Backup", "Restore", "Volume backup",
                      "Unpacking the backup to restore it")
    # ...and every `what` the server passes has a name here (a new one would read raw).
    import ast

    used = set()
    for p in (_ROOT / "src" / "backup").glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "preflight_free_space":
                for kw in node.keywords:
                    if kw.arg == "what" and isinstance(kw.value, ast.Constant):
                        used.add(kw.value.value)
    assert used, "no preflight_free_space(what=...) call found -- re-point this test"
    table = app_js()[app_js().index("const _OO_SPACE_WHAT = {"):app_js().index("const _OO_SIZE_RE")]
    for what in used:
        assert f'"{what}":' in table, f"what={what!r} has no keyed name in _OO_SPACE_WHAT"


def _run_server_text(messages: list[str]) -> list[str]:
    js = app_js()
    consts = js[js.index("const _OO_SPACE_WHAT = {"):js.index("function ooServerText(")]
    prog = "\n".join([
        "const window = {};",
        function_source(js, "_sizeText"),
        consts,
        function_source(js, "ooServerText"),
        "process.stdout.write(JSON.stringify(" + json.dumps(messages) + ".map(ooServerText)));",
    ])
    proc = subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_page_reads_the_servers_real_free_space_sentences(tmp_path):
    from src.backup.artifact import BackupSpaceError, preflight_free_space
    from src.backup.folder_backup import human_bytes

    with pytest.raises(BackupSpaceError) as err:
        preflight_free_space(tmp_path, 10**15, what="restore")
    artifact_msg = "Restore failed: " + str(err.value)
    # The folder backup's check is inline; its sentence is rebuilt from the SAME template,
    # and the template is pinned in its source so the two cannot drift apart unseen.
    fb = (_ROOT / "src" / "backup" / "folder_backup.py").read_text(encoding="utf-8")
    assert 'f"Not enough free space at {destp}: needs {human_bytes(need)}, "' in fb
    assert 'f"only {human_bytes(free)} free."' in fb
    folder_msg = f"Not enough free space at {tmp_path}: needs {human_bytes(13 * 1024**3)}, only {human_bytes(4 * 1024**3)} free."

    a, f, other = _run_server_text([artifact_msg, folder_msg, "volume 3 failed its checksum"])
    assert a.startswith("Restore failed: Restore: not enough free space — needs about "), a
    assert "Not enough free space for the" not in a
    assert f.startswith("Not enough free space at ⁨"), f
    assert "⁨13.0 GB⁩" in f and "⁨4.0 GB⁩" in f, f
    assert other == "volume 3 failed its checksum", "an unknown sentence comes back unchanged"


# --- Y10: statistics areas and the non-ISO picker note ------------------------- #


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_stored_figures_and_triangulation_carry_the_area_classification(db):
    from src.stats import store
    from src.stats.sdmx import StatFigure

    def fig(area):
        return StatFigure(agency="worldbank", series_id="SP.POP.TOTL", ref_area=area, time_period="2023",
                          value=1.0, unit="", methodology_ref=None, adjustment=None, base_year=None,
                          extracted_at="2026-09-26T00:00:00Z")

    store.store_figures(db, [fig("WLD"), fig("FRA"), fig("XKX")])
    db.commit()
    by_area = {f["ref_area"]: f for f in store.list_figures(db, series_id="SP.POP.TOTL")["figures"]}
    assert by_area["WLD"]["area_kind"] == "aggregate" and by_area["WLD"]["area_name"] == "World"
    assert by_area["FRA"]["area_kind"] == "country" and by_area["FRA"]["area_name"] is None
    cells = {c["ref_area"]: c for c in store.triangulate(db, series_id="SP.POP.TOTL")["cells"]}
    assert cells["WLD"]["area_kind"] == "aggregate" and cells["XKX"]["area_kind"] == "country"


def test_the_statistics_tables_draw_areas_through_the_shared_cell():
    js = app_js()
    assert_present(function_body(js, "loadStatFigures"), "ooAreaCell(f.ref_area, f.area_kind, f.area_name)")
    assert_absent(function_body(js, "loadStatFigures"), "<td>${esc(f.ref_area)}</td>")
    assert_present(function_body(js, "triangulateStatSeries"), "ooAreaCell(c.ref_area, c.area_kind, c.area_name)")
    assert_absent(function_body(js, "triangulateStatSeries"), "<td>${esc(c.ref_area)}</td>")


def test_a_non_iso_pick_is_disclosed_beside_the_pickers_caveats():
    js = app_js()
    note = function_body(js, "_govNonIsoNote")
    assert_present(note, 'ooCountryKind(c) !== "non-iso"')
    assert_present(note, "ooCountryTitle(c)")
    assert_present(function_body(js, "loadGovCountry"), "_govNonIsoNote([iso])")
    assert_present(function_body(js, "renderGovCompare"), "_govNonIsoNote([a, b])")


# --- Y11: the season hover names its own computation, in keyed frames ---------- #


def test_the_seasons_carry_their_own_chapter_27_method():
    from src.api.events import astronomy as astronomy_endpoint
    from src.events import astronomy

    method = astronomy.seasons_for_year(2026)["method"]
    assert "ch. 27" in method and "lunar" not in method and "planetary" not in method, method
    out = astronomy_endpoint(year=2026)
    assert out["seasons_method"] == method
    assert out["seasons_accuracy"] == astronomy._ACCURACY
    assert "ch. 49" in out["method"], "the top-level method stays the moon's"
    _keyed_everywhere(method)


def test_the_agenda_hovers_use_keyed_frames_and_the_seasons_method():
    ag = read_static("app-agenda.js")
    assert_present(function_body(ag, "_astroNote"), 'tfn("{method}; {accuracy}"')
    assert_present(function_body(ag, "_astroTitle"), 'tfn("{event} {time} UTC — {note}"')
    assert_absent(ag, '" UTC — "')
    assert_absent(ag, 'tr(x.method || "") + "; "')
    assert_present(ag, "method: d.seasons_method || \"\"")
    assert_present(function_body(ag, "_seasonLabel"), 'june_solstice: "June solstice"')
    _keyed_everywhere("{method}; {accuracy}", "{event} {time} UTC — {note}",
                      "March equinox", "June solstice", "September equinox", "December solstice")
    assert "؛" in _locales()["ar"]["{method}; {accuracy}"], "Arabic writes its own semicolon"


# --- Y12: one word for "corpus" in Bengali ------------------------------------- #


def test_bengali_uses_one_word_for_corpus():
    bn = _locales()["bn"]
    assert bn["corpus"] == bn["Corpus"] == "কর্পাস"
    assert not [k for k, v in bn.items() if isinstance(v, str) and "করপাস" in v]
    for k in ("The corpus as a sky.", "Merge it into your corpus and save",
              "Your corpus stays on this machine — no cloud, no telemetry; fetching follows your Network mode."):
        assert "কর্পাস" in bn[k] and "সংগ্রহ" not in bn[k], (k, bn[k])
