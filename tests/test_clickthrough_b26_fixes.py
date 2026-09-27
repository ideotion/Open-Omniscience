"""Batch B26 of the 2026-09-27 re-walk, pinned: the export and its folder picker (rows J),
and two Settings → Advanced surfaces plus the first-launch data-location step (rows H, U).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

J-1  a reload between the corpus phase and the large-data copy left the copy unstarted,
     and the reopened dialog read "Backup complete" + "Verified" over a folder without the
     LLM models the operator ticked. The export now RECORDS what it was asked for in its
     dated folder (``oo-export-request.json``), the facts compare it with the folder, and
     the panel, the heading and ``BACKUP_SUMMARY.md`` say what is missing -- with a button
     that copies it into the same folder. (Making the export one server-side job is the
     fuller fix and is deferred.)
J-2  the shared folder picker drew the path and a dated folder name right to left in Arabic.
J-3  Arabic named parity and the corpus two ways on the export surface and pointed the
     completion arrow back at its label; Chinese got welded ASCII brackets.
J-4  at 375 px the picker clipped folder names, hiding the ``_2`` that tells exports apart.
H-2  the topic-discovery disclosure line and toasts were English in every locale.
U-2  the at-rest encryption lines did not repaint on a live language switch.
U-4  the first-launch data-location path was bidi-reordered in Arabic.

The renderers run as REAL, extracted code under node (``tests/clickthrough_b26_node_test.js``);
the request record, the facts and the summary file run as the real Python.
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
)

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"


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


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b26_node_test.js")],
        capture_output=True, text=True, check=False, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "clickthrough b26 node suite" in proc.stdout


# --- J-1: the export records what it was asked for, and the folder answers ------------ #


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_the_allocation_records_the_request_in_the_new_folder(client, tmp_path):
    from src.backup.export_folder import REQUEST_NAME

    r = client.post(
        "/api/backup/export-folder",
        json={"parent": str(tmp_path), "corpus": True,
              "categories": ["models", "hf_models", "not-a-category"], "inside": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["request_recorded"] is True
    d = Path(r.json()["dir"])
    rec = json.loads((d / REQUEST_NAME).read_text(encoding="utf-8"))
    assert rec["corpus"] is True and rec["inside"] is False
    # A value no member exports is dropped: the record can only name real members.
    assert rec["categories"] == ["models", "hf_models"]
    assert sorted(p.name for p in d.iterdir()) == [REQUEST_NAME], "a temp file was left behind"


def test_an_allocation_without_a_request_records_nothing(client, tmp_path):
    """The older caller shape still gets a pristine folder -- and an UNKNOWN request,
    which the facts must never turn into "nothing was asked for"."""
    from src.backup.export_summary import export_facts

    r = client.post("/api/backup/export-folder", json={"parent": str(tmp_path)})
    d = Path(r.json()["dir"])
    assert list(d.iterdir()) == [] and r.json()["request_recorded"] is False
    f = export_facts(d)
    assert f["requested"] is None
    assert f["missing"] == {"known": False, "corpus": False, "categories": []}


def _fake_volume_set(d: Path) -> None:
    (d / "volumes.json").write_text(
        json.dumps({"kind": "oo-volumes-2", "volumes": [{"name": "v1.ooenc", "bytes": 10}]}),
        encoding="utf-8",
    )


def test_a_corpus_without_its_requested_copy_is_incomplete_in_the_facts_and_the_file(tmp_path):
    from src.backup.export_folder import allocate_export_folder, write_export_request
    from src.backup.export_summary import export_facts, render_summary_markdown

    d = allocate_export_folder(tmp_path)
    write_export_request(d, corpus=True, categories=["models", "hf_models"])
    _fake_volume_set(d)  # the corpus phase finished; the copy never started
    f = export_facts(d)
    assert f["missing"] == {"known": True, "corpus": False, "categories": ["models", "hf_models"]}
    md = render_summary_markdown(f)
    assert "INCOMPLETE — large-data files" in md and "`models`, `hf_models`" in md
    # The old file read "Files copied: none." -- true, and silent about what was asked.
    assert "- **Files copied:** none." not in md
    assert "the large-data copy this export asked for did not complete" in md


def test_the_copy_finishing_clears_it_and_inside_members_are_never_owed(tmp_path):
    from src.backup.export_folder import allocate_export_folder, write_export_request
    from src.backup.export_summary import export_facts, render_summary_markdown
    from src.backup.folder_backup import MANIFEST_NAME

    done = allocate_export_folder(tmp_path)
    write_export_request(done, corpus=True, categories=["osm_regions"])
    _fake_volume_set(done)
    # oo-folder-backup.json is written only at the end of a COMPLETE copy.
    (done / MANIFEST_NAME).write_text(json.dumps({"categories": {"osm_regions": []}}), encoding="utf-8")
    f = export_facts(done)
    assert f["missing"] == {"known": True, "corpus": False, "categories": []}
    assert "INCOMPLETE" not in render_summary_markdown(f)

    inside = allocate_export_folder(tmp_path)
    write_export_request(inside, corpus=True, categories=["models"], inside=True)
    _fake_volume_set(inside)
    assert export_facts(inside)["missing"]["categories"] == [], (
        "members carried INSIDE the artifact owe no separate copy"
    )


def test_a_missing_corpus_is_named_too(tmp_path):
    from src.backup.export_folder import allocate_export_folder, write_export_request
    from src.backup.export_summary import export_facts, render_summary_markdown

    d = allocate_export_folder(tmp_path)
    write_export_request(d, corpus=True, categories=[])
    f = export_facts(d)
    assert f["missing"]["corpus"] is True
    assert "INCOMPLETE — the corpus" in render_summary_markdown(f)


def test_the_page_sends_the_request_and_can_finish_the_copy():
    app = read_static("app.js")
    run = function_body(app, "_uxRun")
    assert_present(run, "parent, corpus: wantCorpus, categories: blobs, inside }",
                   why="the allocation must carry what the export was asked for")
    finish = function_body(app, "_uxCompleteExport")
    assert_present(finish, '"/api/backup/folder/start"')
    assert_present(finish, "(facts.missing || {}).categories",
                   why="the copy must take its categories from the folder's facts, not the checklist")
    assert_absent(finish, "_uxMemberBoxes", why="the checklist's ticks may have changed since")
    for fn in ("_uxShowLastCompletedExportSummary", "_uxFinishExport"):
        assert_present(function_body(app, fn), 't("Backup incomplete →")')


# --- J-2 / J-4: the shared folder picker ---------------------------------------------- #


def test_the_picker_isolates_the_path_and_names_and_lets_rows_wrap():
    nav = function_body(read_static("app-map.js"), "_fpNav")
    assert_present(nav, '$("fp-path").innerHTML = `<bdi dir="ltr">${esc(d.path)}</bdi>`')
    assert_present(nav, '📁 <bdi dir="ltr">${esc(e.name)}</bdi>')
    assert_present(nav, "overflow-wrap:anywhere")
    assert_absent(nav, '$("fp-path").textContent = d.path', why="the J-2 path line is back")


# --- J-3: one Arabic term per concept; the arrow; the brackets ------------------------ #


def test_arabic_names_parity_and_the_corpus_one_way_on_the_export_surface():
    ar = _locales()["ar"]
    parity_keys = [
        "Writing parity…", "Back up (volumes + parity)", "Large encrypted backup (volumes + parity)",
        "(volumes only — parity needs the analysis features)", "Backing up (volumes + parity)",
        "Backing up corpus (encrypted volumes + parity)…", "Parity (corruption recovery)",
        "Verify + repair (from parity) + reassemble the volume set, then merge ADDITIVELY into "
        "your corpus — nothing is replaced or deleted.",
    ]
    for k in parity_keys:
        assert "تكافؤ" in ar[k] and "تماثل" not in ar[k], f"ar {k!r}: {ar[k]!r}"
    intro = ar[
        "One place to back up everything, at any database size. Pick a destination folder or "
        "drive, choose what to include, and it streams into that folder — the encrypted corpus "
        "as volumes + parity, the large public blobs (models / maps / dumps) copied as-is. No "
        "size limit. (The older single-file backup below is being replaced by this.)"
    ]
    assert "المجموعة المشفّرة كوحدات + تكافؤ" in intro and "المتن" not in intro, intro
    assert ar["Corpus"] == "المجموعة"
    # The review round: the export's own passphrase toast, and the import dialog beside it
    # (the same file, the same surface), still said المتن -- and one line said أجزاء for
    # the volumes the rest of the dialog calls وحدات.
    corpus_keys = [
        "Enter a passphrase for the encrypted corpus.",
        "Restore corpus backup",
        "Enter the passphrase to restore the corpus.",
        "Check the backup's manifest signature and every volume + parity checksum without "
        "restoring anything — the live corpus is untouched.",
        "Restore merges this backup into your corpus (additive — nothing is replaced). Continue?",
        "Stops the import now. Before a backup's atomic swap this is a complete abort — your "
        "corpus is untouched. After it, that backup has already merged and this stops the "
        "remaining work (the re-index resumes later from where it left off); it is not an undo.",
        "Stop this import? Any backup that has not yet been swapped in is abandoned completely — "
        "your corpus is untouched. A backup already merged stays merged (there is no undo); only "
        "the remaining work stops, and its re-index resumes later.",
    ]
    for k in corpus_keys:
        assert "متن" not in ar[k] and "أجزاء" not in ar[k], f"ar {k!r}: {ar[k]!r}"
        assert "مجموع" in ar[k], f"ar {k!r} does not name the corpus as the dialog does: {ar[k]!r}"
    # The label sits on the right in RTL and the path on its left: the arrow points left.
    for k in ("Backup complete →", "Backup incomplete →"):
        assert ar[k].endswith("←") and "→" not in ar[k], ar[k]


def test_the_export_s_brackets_are_keyed_frames():
    app = read_static("app.js")
    reopen = function_body(app, "_uxShowLastCompletedExportSummary")
    assert_absent(reopen, '(${esc(t("last completed export"))})', why="welded ASCII brackets (J-3)")
    assert_present(reopen, 'tfb("({text})", { text: t("last completed export") })')
    paint = function_body(app, "_uxPaintInventory")
    assert paint.count('tf("({text})"') == 2, "both checklist count brackets must be keyed frames"
    assert_absent(paint, '<span class="muted">(${')
    # The import checklist and the restore's progress line had the same welded brackets.
    scan = function_body(app, "_uxImScan")
    assert_present(scan, 'esc(tfs("({text})", { text: "\\u0001" }))')
    assert scan.count("${paren(") == 4 and scan.count('" " + paren(') == 1, "five checklist brackets"
    assert_absent(scan, '<span class="muted">(', why="welded ASCII brackets on the import checklist (J-3)")
    assert_absent(scan, "parts.push(`wiki", why="an English category word welded to a raw count")
    assert_present(scan, "f.legacy_backup.map(x => ltr(x.name))")
    assert_present(scan, "f.source_csv.map(ltr)")
    view = function_body(app, "_uxProgressView")
    assert view.count('tf("({text})"') == 2, "the merge and re-index brackets must be keyed frames"
    assert_absent(view, '<span class="muted">(', why="welded ASCII brackets on the restore progress (J-3)")
    loc = _locales()
    assert loc["zh"]["({text})"] == "（{text}）" and loc["ja"]["({text})"] == "（{text}）"


# --- H-2: the topic-discovery disclosure ---------------------------------------------- #

_H2_KEYS = (
    "Enabled: topic-discovery queries will be sent to DuckDuckGo.",
    "Disabled (the default): no topic query leaves this machine.",
    "External topic discovery enabled.",
    "External topic discovery disabled.",
)


def test_the_discovery_disclosure_and_toasts_are_keyed_x12_and_repaint():
    _keyed_everywhere(_H2_KEYS)
    for code, d in _locales().items():
        if code != "en":
            for k in _H2_KEYS:
                assert d[k] != k, f"{code} leaves a consent string in English: {k!r}"
    app = read_static("app.js")
    save = function_body(app, "saveDiscoveryExternal")
    assert_present(save, 't("External topic discovery enabled.")')
    assert_present(save, 't("External topic discovery disabled.")')
    assert_present(function_body(app, "_paintDiscoveryResult"),
                   't("Enabled: topic-discovery queries will be sent to DuckDuckGo.")')
    html = read_static("index.html")
    assert re.search(r'<div id="discovery-external-result"[^>]*\bdata-i18n-dyn\b', html), (
        "a t()-rendered line in a walker-owned node is cached as the English (H-2)"
    )
    boot = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert any("_paintDiscoveryResult()" in b for b in boot), f"{len(boot)} listener(s), none repaints it"


# --- U-2: the at-rest lines ------------------------------------------------------------ #


def test_the_at_rest_lines_repaint_from_cache_on_a_language_switch():
    app = read_static("app.js")
    load = function_body(app, "loadAtRestState")
    assert_present(load, "_renderAtRest()")
    assert_absent(load, "box.innerHTML", why="the render must be the cache-only function the switch calls")
    assert_absent(function_body(app, "_renderAtRest"), "api(", why="a language switch must not fetch")
    html = read_static("index.html")
    assert re.search(r'<div id="atrest-state"[^>]*\bdata-i18n-dyn\b', html), (
        "the walker would cache 'المجموعة: ' as the English and never let it go (U-2)"
    )
    boot = event_listener_bodies(read_static("app-boot.js"), "oo:langchange")
    assert any("_renderAtRest()" in b for b in boot), f"{len(boot)} listener(s), none repaints at-rest"


# --- U-4: the first-launch data-location path ------------------------------------------ #


def test_the_data_location_paths_are_ltr_isolates():
    html = read_static("unlock.html")
    rule = re.search(r"\.path \{([^}]*)\}", html)
    assert rule, "the .path rule moved"
    assert "direction:ltr" in rule.group(1) and "unicode-bidi:isolate" in rule.group(1), rule.group(1)
    assert '<span id="dl-default-path" class="path">' in html
    assert re.search(r'<input type="text" id="dl-path" dir="ltr"', html), "the typed path is reordered in RTL"
    restart = html[html.index("function dlRestartRequired("):html.index("function dlWarningText(")]
    assert 'p2path.className = "path"' in restart and 'p2.className = "path"' not in restart, (
        "a block-level .path would flip the whole paragraph's alignment"
    )
    check = html[html.index("async function dlCheck("):html.index("async function dlContinue(")]
    assert 'sp.className = "path"' in check, "the checked path is glued into the Arabic sentence"
