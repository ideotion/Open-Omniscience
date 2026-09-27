"""Batch B15 of the 2026-09-27 delegated click-through, pinned: the data-surface leftovers
earlier batches found beside their own work. The export's completion panel after a resume
(W1), the dead folder-backup plan (W2), the statistics fetch's English tally (W4), the
revision anomalies' area cell (W5), the export dialog's error lines (W6), the import
report's name column at phone width (W7), the Governments names, caveats and notes in the
UI language and after a switch (W8/W15/W16), signed numbers isolated (W9), re-imports of an
already-merged folder skipped (W12), the attribution hover (W14), the Insights header
(W17) and the last three files off the browser's number locale (W18).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each lead was reproduced first. CI runs no browser, so the renderers run as real,
EXTRACTED code under node (``tests/clickthrough_b15_node_test.js``, and the batch's
additions to ``export_panel_node_test.js`` and ``import_conclusion_node_test.js``); the
backup identity, the anomaly rows and the aggregate payload run as the real Python.
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


def _keyed_everywhere(keys) -> None:
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
    assert not missing, "not keyed:\n" + "\n".join(missing[:40])


@pytest.mark.parametrize("suite", [
    "clickthrough_b15_node_test.js",
    "export_panel_node_test.js",
    "import_conclusion_node_test.js",
])
def test_the_behaviour_runs_as_real_code_under_node(suite):
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / suite)], capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- W12: a current backup has an identity, so a re-import takes the skip -------- #


def _v2_backup(tmp: Path, dest: Path, rows: int = 200) -> Path:
    import sqlite3

    from src.backup.stream_backup import CorpusSource, MemberFile, _no_freeze, write_stream_backup

    corpus = tmp / f"corpus-{dest.name}.db"
    con = sqlite3.connect(corpus)
    con.executescript("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT);")
    con.executemany("INSERT INTO articles(hash, content) VALUES(?,?)",
                    [(f"h{i:05d}", "x" * 500) for i in range(rows)])
    con.commit()
    con.close()
    side = tmp / f"settings-{dest.name}.json"
    side.write_text('{"k": 1}', encoding="utf-8")
    write_stream_backup(
        dest, "pw",
        corpus_source=CorpusSource(path=corpus, member_name="corpus.db", encrypted=False,
                                   freeze=_no_freeze),
        side_members=[MemberFile("app_settings.json", "state", side)],
        volume_size=65536,
    )
    return dest


def test_a_streamed_backup_folder_has_a_stable_identity(tmp_path):
    """The streaming writer (every export since 2026-07-09) records a digest per MEMBER and
    none at the top, so the identity read returned None for every current backup and the
    already-merged skip never fired: the walk re-imported two merged folders in full."""
    import shutil

    from src.backup.merge import artifact_source_digest
    from src.backup.volumes import load_manifest

    a = _v2_backup(tmp_path, tmp_path / "a")
    assert "plaintext_sha256" not in load_manifest(a), "the fixture is no longer the v2 shape"
    digest = artifact_source_digest(a)
    assert isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), digest
    # A copy of the same folder is the same artifact...
    shutil.copytree(a, tmp_path / "a-copy")
    assert artifact_source_digest(tmp_path / "a-copy") == digest
    # ...and a folder holding different bytes is not.
    b = _v2_backup(tmp_path, tmp_path / "b", rows=201)
    assert artifact_source_digest(b) not in (None, digest)


def test_a_partial_member_list_is_no_identity(tmp_path):
    """A skip on a degenerate key refuses imports it never performed: any member without a
    name or a well-formed digest makes the answer "cannot tell", never a guess."""
    from src.backup.merge import artifact_source_digest

    good = {"name": "corpus.db", "plaintext_sha256": "a" * 64}
    for members in ([], [good, {"name": "x"}], [good, {"name": "", "plaintext_sha256": "b" * 64}],
                    [good, {"name": "y", "plaintext_sha256": "B" * 64}], [good, "junk"], "junk"):
        d = tmp_path / "m"
        d.mkdir(exist_ok=True)
        (d / "volumes.json").write_text(
            json.dumps({"kind": "oo-volumes-2", "members": members}), encoding="utf-8")
        assert artifact_source_digest(d) is None, f"accepted {members!r}"


def test_the_restore_skips_a_folder_this_corpus_already_merged(tmp_path, monkeypatch):
    """The manager's own path: the identity it reads is the one a completed import
    recorded, so the second import of the same folder is answered from the manifest."""
    from src.backup import merge
    from src.backup.volume_job import VolumeBackupManager

    folder = _v2_backup(tmp_path, tmp_path / "exp")
    digest = merge.artifact_source_digest(folder) or "never-matches"
    monkeypatch.setenv("OO_RUN_JOURNAL", "0")
    monkeypatch.setattr(
        merge, "find_completed_import",
        lambda d: {"batch_id": 7, "imported_at": "2026-09-26"} if d == digest else None,
    )

    def _would_restore(*a, **k):
        raise RuntimeError("the restore ran again")

    monkeypatch.setattr("src.backup.artifact.read_volume_backup", _would_restore)
    monkeypatch.setattr("src.scheduler.runner.pause_for_exclusive_operation", lambda: False)
    monkeypatch.setattr("src.scheduler.runner.resume_after_exclusive_operation", lambda *a, **k: None)
    mgr = VolumeBackupManager()
    mgr._run_restore(folder, "pw", False, None, None)
    st = mgr.status()
    summary = st.get("summary") or {}
    assert summary.get("skipped") == "already-merged", st
    assert summary.get("source_digest") == digest
    assert summary.get("merged_as_batch") == 7


# --- W5: the revision anomalies carry the area's classification -------------------- #


def test_revision_anomalies_carry_the_area_classification():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base
    from src.stats import store
    from src.stats.sdmx import StatFigure

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        trail = [(1, 100.0), (2, 100.1), (3, 99.9), (4, 100.2), (5, 100.0), (6, 110.0)]
        figs = [
            StatFigure(agency="worldbank", series_id="NY.GDP.MKTP.CD", ref_area=area,
                       time_period="2019", value=v, unit=None, methodology_ref=None,
                       adjustment=None, base_year=None, extracted_at=f"2026-{m:02d}-01T00:00:00Z")
            for area in ("WLD", "FRA") for m, v in trail
        ]
        store.store_figures(s, figs)
        rows = {a["ref_area"]: a for a in store.revision_anomalies(s)["anomalies"]}
    finally:
        s.close()
        engine.dispose()
    assert set(rows) == {"WLD", "FRA"}, rows
    assert rows["WLD"].get("area_kind") == "aggregate", rows["WLD"]
    assert rows["WLD"].get("area_name") == "World", rows["WLD"]
    assert rows["FRA"].get("area_kind") == "country", rows["FRA"]


def test_the_anomalies_table_draws_the_shared_area_cell():
    body = strip_comments(function_body(read_static("app-map.js"), "loadRevisionAnomalies"))
    assert_present(body, "_statAreaLocal(d.anomalies)")
    assert_present(body, "ooAreaCell(a.ref_area, a.area_kind, a.area_name)")


# --- W8 / W15 / W16: the Governments vocabulary is keyed, and repaints ------------- #


@pytest.fixture
def _agg_client():
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.api.main import app
    from src.database.models import Base, StatFigure
    from src.database.session import get_db
    from src.ingest import clear_kill_switch

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(StatFigure(agency="worldbank", series_id="NY.GDP.MKTP.CD", ref_area="WLD",
                     time_period="2022", value=1.0e14, unit="", extracted_at="2026-08-01"))
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        clear_kill_switch()
        s.close()


def test_the_aggregate_caveat_arrives_in_parts_each_a_key(_agg_client):
    """The joined caveat is two fixed sentences glued into a string no locale holds."""
    from src.api import governments

    d = _agg_client.get("/api/governments/aggregate/WLD").json()
    assert d.get("caveats") == [governments._AGG_CAVEAT, governments._CAVEAT], d.get("caveats")
    assert d["caveat"] == " ".join(d["caveats"]), "the older shape must stay the joined text"
    _keyed_everywhere(d["caveats"])


def test_every_fixed_governments_sentence_and_name_is_a_key_in_all_twelve(_agg_client):
    from src.catalog import aggregates as aggs
    from src.catalog import blocs

    keys: set[str] = {a.name for a in aggs.place_aggregates()}
    for name in blocs.group_names():
        g = blocs.resolve_group(name)
        assert g is not None
        keys.add(g.label)
        if g.notes:
            keys.add(g.notes)
        if g.unpopulated_reason:
            keys.add(g.unpopulated_reason)
    keys.add(_agg_client.get("/api/governments/groups").json()["caveat"])
    keys.add(_agg_client.get("/api/governments/aggregates").json()["caveat"])
    _keyed_everywhere(sorted(keys))


def test_the_governments_views_repaint_from_cache_on_a_language_switch():
    """Every caveat, note and name is t()'d at render, so one drawn in French is no longer
    an English key the DOM walker can find: a switch left it French (booted in fr,
    switched to ar)."""
    boot = read_static("app-boot.js")
    listeners = "\n".join(event_listener_bodies(boot, "oo:langchange"))
    for fn in ("repaintGovViewsFromCache", "repaintInsightsStatusFromCache"):
        assert_present(listeners, f"{fn}()", why="the ONE oo:langchange listener must call it")
    gov = read_static("app-gov-law.js")
    body = function_body(gov, "repaintGovViewsFromCache")
    assert_absent(body, "api(", why="a language switch must never refetch")
    for painter in ("_govCountryHtml(", "_govCompareHtml(", "_govAggHtml(", "_govPaintAggNote()",
                    "_govPaintAggregateOptions()", "_govPaintGroupNote()", "_govPaintGroupOptions()",
                    "_govMapCaveatText("):
        assert_present(body, painter)
    assert_absent(function_body(read_static("app-insights.js"), "repaintInsightsStatusFromCache"), "api(")
    # The group picker's labels, the lens hints and the map caveat go through the translator.
    assert_present(function_body(gov, "_govPaintGroupOptions"), "_govT(g.label)")
    assert_present(function_body(gov, "_govPaintAggregateOptions"), "_govT(a.name)")
    assert_present(function_body(gov, "_govPaintAggNote"), "_govT(_govAggs.caveat)")
    assert_present(function_body(gov, "_govPaintGroupNote"), "_govT(_govGroups.caveat)")
    assert_present(function_body(gov, "_govMapCaveatText"), "t(data.caveat)")


# --- W4: the statistics fetch reads in the UI language ----------------------------- #


def test_the_statistics_fetch_tally_and_failure_are_keyed_frames():
    body = strip_comments(function_body(read_static("app-map.js"), "fetchStatFigure"))
    frame = "{fetched} fetched · {stored} stored · {duplicate} already had this vintage · {gaps} published gaps"
    assert_present(body, f'_govTf("{frame}"')
    assert_present(body, '_failMsg("Fetch failed: {error}", e)')
    assert_present(body, 't("Enter an indicator or dataset id first.")')
    assert_present(body, 't("Fetching…")')
    assert_absent(body, "note err", why="the error colour, never the floating toast box")
    assert_absent(body, "Fetched <b>", why="the English tally is the defect")
    # The caveat every fetch answers with is a caveat: it ships in all twelve (it was
    # drawn as the server's English under a translated tally).
    assert_present(body, "esc(t(d.caveat))")
    from src.api.stats import FETCH_CAVEAT

    _keyed_everywhere([frame, "Fetch failed: {error}", FETCH_CAVEAT])


# --- W6 / W14 / W1: the export dialog ---------------------------------------------- #


def test_the_export_dialog_draws_errors_in_the_error_colour_not_the_toast_box():
    """`.note` is the floating toast style (padding, shadow, a 360 px cap, a slide-in), so
    an error line inside the dialog rendered as a detached box."""
    backup = read_static("app-backup.js")
    for fn in ("_uxRenderExportPanel", "_uxRun", "_uxFinishExport", "_uxResume"):
        body = strip_comments(function_body(backup, fn))
        assert_absent(body, "note err", why=f"{fn} must use color:var(--err)")
    panel = function_body(backup, "_uxRenderExportPanel")
    assert_present(panel, 'tf("The attribution query failed: {detail}", { detail: facts.attribution_error })')
    _keyed_everywhere(["The attribution query failed: {detail}"])


def test_the_resumed_export_ends_on_the_same_completion_panel():
    """A resumed export ended on a bare "Backup complete" line: no Included line, no
    summary file, no facts panel. Both paths now end through one function."""
    backup = strip_comments(read_static("app-backup.js"))
    assert_present(function_body(backup, "_uxRun"), "await _uxFinishExport(prog, dest, t);")
    assert_present(function_body(backup, "_uxResume"), "await _uxFinishExport(")
    fin = function_body(backup, "_uxFinishExport")
    for needle in ("/api/backup/export-summary", "_uxRenderExportPanel(", "_uxExportIncluded"):
        assert_present(fin, needle)


def test_the_dead_folder_backup_plan_is_gone():
    backup = strip_comments(read_static("app-backup.js"))
    assert "function folderBackupPlan(" not in backup
    assert 'id="fb-plan"' not in read_static("index.html")


# --- W7 / W9: the import report at phone width, signed numbers isolated ------------ #


def test_the_per_item_table_stacks_its_cells_at_phone_width():
    """At 375 px the fixed-width number columns left the name column a few characters wide
    (measured in en and ar); under 600 px each row's cells stack instead."""
    css = read_static("app.css")
    at = css.find(".ux-peritem, .ux-peritem tbody")
    assert at != -1, "the phone-width rule for the per-item table is gone"
    media = css.rfind("@media", 0, at)
    assert "max-width:600px" in css[media:at].replace(" ", "")
    rules = css[at:css.find("\n    }", at)]  # up to the media block's own close
    assert_present(rules, "width:auto !important", why="the inline column widths must give way")
    assert_present(function_body(read_static("app-backup.js"), "_uxPerItemView"), 'class="ux-peritem"')


def test_signed_numbers_are_isolated_in_rtl():
    """A leading "+" or "-" is a weak bidi character: on an Arabic page it moved to the
    far end of the number ("2 400+")."""
    m = strip_comments(read_static("app-map.js"))
    assert "_ltrIsolate((v >= 0 ? \"+\" : \"\") + fmtNum(v, 2))" in m
    assert "_ltrIsolate((row.sentiment >= 0 ? \"+\" : \"\") + fmtNum(row.sentiment, 2))" in m


# --- W17 / W18: the Insights header and the browser's number locale ---------------- #


def test_the_insights_header_is_keyed_frames_around_fmt_num_counters():
    ins = strip_comments(read_static("app-insights.js"))
    frame = function_body(ins, "_insStatusFrame")
    for key in ("{indexed}/{total} articles indexed", "{keywords} keywords ({entities} entities)",
                "{mentions} mentions"):
        assert_present(frame, key)
    assert_present(function_body(ins, "_insRemainingHtml"), "{n} to index")
    _keyed_everywhere(["{indexed}/{total} articles indexed", "{keywords} keywords ({entities} entities)",
                       "{mentions} mentions", "{n} to index"])
    tween = function_body(read_static("app-backup.js"), "animateCount")
    assert_absent(tween, "toLocaleString", why="the tween drew the browser's grouping")
    assert_present(tween, "fmtNum(")


def test_the_keyword_growth_head_uses_the_locale_separator():
    head = strip_comments(function_body(read_static("app-diagnostics.js"), "viewKeywordGrowth"))
    assert_present(head, 'ooLabelHtml(esc(t("Keywords"))')
    assert_absent(head, 't("Keywords"))}: <b>', why="a welded colon is wrong in fr/zh/ar")
    assert_absent(head, "toLocaleString", why="the browser's grouping, not the ruled one")
