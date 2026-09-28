"""Row S of the 2026-09-26 delegated click-through, pinned: S1, S2, S3, S5, S8.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each defect was reproduced in Chromium first and checked there after
(``docs/audit/delegated-clickthrough-2026-09-26/`` holds the row). CI runs no browser, so
the behavioural halves run as real code under node
(``tests/quality_gates_repaint_node_test.js``: the merge refusal reaching the screen, the
undo repainting the whole panel, the audit stamps), and this file pins the rest:

* S1 -- Merge accepts the YAML its own Export button saves, and refuses an OVERLAY (a
  merged or shipped file) by name rather than counting its rows as fresh measurements;
* S3 -- a live language switch re-reads the Quality gates panel, and only once opened;
* S5 -- the retired-hatch sentence names a path that exists, in every locale;
* S8 -- the audit's stamps arrive whole-second and zone-stated.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.api.main import app  # noqa: E402
from src.catalog.qualification import (  # noqa: E402
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    admission_audit,
    evaluate_and_stamp,
    undo_admission,
)
from src.catalog.qualification_merge import (  # noqa: E402
    MergeInputError,
    render,
    rows_from_export_bytes,
)
from src.database.models import (  # noqa: E402
    Base,
    Source,
    SourceAdmissionEvent,
    SourceQualificationAttempt,
)
from src.database.session import get_db  # noqa: E402
from src.ingest import clear_kill_switch  # noqa: E402
from tests.js_source_helper import app_js, event_listener_bodies, strip_comments  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"
_MERGE = "/api/diagnostics/source-qualification-merge"
_EXPORT = "/api/diagnostics/source-qualification-export?fmt=yaml"
_NOW = datetime(2026, 9, 18, tzinfo=UTC)


def test_quality_gates_repaint_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "quality_gates_repaint_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --------------------------------------------------------------------------- #
# S1 -- the panel's own loop: Export, then Merge
# --------------------------------------------------------------------------- #
@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    # One app-provided source this instance MEASURED, so the export has a real row.
    src = Source(name="mine", domain="mine.example", tags="news,via:curated",
                 enabled=True, status=STATUS_QUALIFIED,
                 qualified_at=_NOW.replace(tzinfo=None), qualification_criteria_version="t")
    s.add(src)
    s.commit()
    s.add(SourceQualificationAttempt(
        source_id=src.id, attempted_at=_NOW.replace(tzinfo=None),
        verdict=STATUS_QUALIFIED, criteria_version="t"))
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        clear_kill_switch()


def test_merge_accepts_the_yaml_the_export_button_saves(client) -> None:
    """THE REGRESSION. The panel's Export saves ``fmt=yaml``; Merge refused that exact file
    as "not valid JSON", so the loop the panel offers could not be run inside it."""
    exported = client.get(_EXPORT)
    assert exported.status_code == 200, exported.text
    assert "mine.example" in exported.text and "basis: measured" in exported.text
    r = client.post(_MERGE, files=[("files", ("source_qualification.yml",
                                              exported.content, "text/yaml"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged_verdicts"] == 1
    assert "mine.example" in body["overlay_yaml"]
    assert body["report"]["inputs"][0]["verdicts"] == 1


def test_the_yaml_route_carries_the_same_rows_as_the_json_route(client) -> None:
    """The route in must not change the answer."""
    as_json = client.get("/api/diagnostics/source-qualification-export").json()["verdicts"]
    as_yaml = rows_from_export_bytes(client.get(_EXPORT).content, "export.yml")
    assert as_yaml == as_json


def test_a_merged_overlay_is_refused_rather_than_counted_as_measurements() -> None:
    """NEGATIVE SPACE. A merged file and an export share the name
    ``source_qualification.yml``, and the merged one carries no ``basis`` -- which the merge
    reads as ``measured``. Accepting it would count a previous merge's verdicts as fresh
    measurements: the echo the merge exists to refuse."""
    overlay = render({"a.example": {"domain": "a.example", "status": "qualified",
                                    "qualified_at": "2026-05-01", "criteria_version": "t"}})
    with pytest.raises(MergeInputError) as e:
        rows_from_export_bytes(overlay.encode("utf-8"), "source_qualification.yml")
    assert "overlay" in str(e.value) and "basis" in str(e.value)


def test_text_that_is_neither_json_nor_yaml_is_still_refused_by_name() -> None:
    with pytest.raises(MergeInputError) as e:
        rows_from_export_bytes(b"{not: [valid", "junk.yml")
    assert "not valid JSON" in str(e.value) and "YAML" in str(e.value)


def test_the_merge_picker_offers_the_file_export_saves() -> None:
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<input[^>]*id="qual-ov-files"[^>]*>', html)
    assert m, "the merge picker is gone"
    accept = re.search(r'accept="([^"]*)"', m.group(0))
    assert accept and ".yml" in accept.group(1).split(","), (
        "Export saves .yml; a picker that hides it makes the operator pick 'All files'"
    )


# --------------------------------------------------------------------------- #
# S3 -- a live language switch repaints the panel, and fetches for nobody
# --------------------------------------------------------------------------- #
def test_a_language_switch_rereads_the_quality_gates_panel_only_once_opened() -> None:
    handlers = [strip_comments(h) for h in event_listener_bodies(app_js(), "oo:langchange")]
    hits = [h for h in handlers if "loadQualificationGates()" in h]
    assert hits, (
        "no oo:langchange listener re-reads the Quality gates panel, so its composed lines "
        f"stay in the old locale ({len(handlers)} listener(s) found)"
    )
    h = hits[0]
    guard = h.find('data-adv="qualification"')
    assert guard != -1 and 'advLoaded === "1"' in h, (
        "the re-read must be guarded on the section having been opened -- a switch must "
        "never fetch for a fold nobody expanded"
    )
    assert guard < h.find("loadQualificationGates()"), "the guard must come before the call"
    assert "loadQualifyBulk()" in h, "the backlog line is a composed frame too"
    assert "_renderOverlayMerge()" in h, "the last merge report is a composed frame too"


# --------------------------------------------------------------------------- #
# S5 -- the retired-hatch disclosure points somewhere real
# --------------------------------------------------------------------------- #
def _retired_sentence() -> str:
    from src.scheduler.settings import _RETIRED_KEYS

    return _RETIRED_KEYS["scrape_unqualified"]


def test_the_retired_disclosure_names_the_real_path() -> None:
    """``#set-subtabs`` has no Sources subtab; the audit lives under Advanced → Quality
    gates. Each crumb is checked against the page itself, so a later move reddens here."""
    sentence = _retired_sentence()
    m = re.search(r"Settings > ([^,]+?), where", sentence)
    assert m, sentence
    crumbs = [c.strip() for c in m.group(1).split(">")]
    assert crumbs == ["Advanced", "Quality gates", "Admission audit"], crumbs
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'data-tab="advanced"[^>]*>\s*Advanced\s*<', html), "no Advanced subtab"
    sec = html.split('data-adv="qualification"', 1)
    assert len(sec) == 2, "no Quality gates section"
    body = sec[1].split("</details>", 1)[0]
    assert '<span class="adv-sec-t">Quality gates</span>' in body
    assert "<h3" in body and ">Admission audit</h3>" in body, "the audit is not in that section"


def test_every_locale_names_the_path_with_its_own_labels() -> None:
    """The translation must say what the reader's UI says, crumb by crumb -- a path in
    English words, or in the old words, points at nothing in that locale."""
    sentence = _retired_sentence()
    files = sorted(_LOCALES.glob("*.json"))
    assert len(files) == 12
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        val = d.get(sentence)
        assert val, f"{p.name} has no key for the retired sentence"
        for crumb in ("Advanced", "Quality gates", "Admission audit"):
            assert d[crumb] in val, f"{p.name}: {crumb!r} ({d[crumb]!r}) missing from {val!r}"


# --------------------------------------------------------------------------- #
# S8 -- the audit's stamps
# --------------------------------------------------------------------------- #
def test_audit_stamps_are_whole_seconds_and_state_their_zone(tmp_path) -> None:
    """An undo stamps the live clock, microseconds and all; a zone-less stamp is parsed
    by a browser as LOCAL time. Both halves are measured on a real undo."""
    engine = create_engine(f"sqlite:///{tmp_path / 'adm.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)
    src = Source(name="u", domain="u.example", status=STATUS_UNQUALIFIED, enabled=False)
    s.add(src)
    s.commit()
    at = datetime(2026, 9, 18, 9, 0, 0, 123456)
    evaluate_and_stamp(s, [src], {}, now=at)
    s.commit()
    (ev,) = s.query(SourceAdmissionEvent).all()
    undo_admission(s, ev.id, now=at + timedelta(hours=1, microseconds=65432))
    (row,) = admission_audit(s, limit=5)["events"]
    assert row["occurred_at"] == "2026-09-18T09:00:00+00:00", row
    assert row["undone_at"] == "2026-09-18T10:00:00+00:00", row
