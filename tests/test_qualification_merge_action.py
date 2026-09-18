"""B5: the export + merge run, as a diagnostics ACTION rather than an operator script.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The register artifact (2026-09-15) asks to "automate the script run within the
diagnostics". What makes that safe rather than merely convenient is that the endpoint and
`scripts/merge_source_qualification.py` run ONE core: the four refusals that decide what
may ship to every fresh install are not a thing this project wants two copies of. The
first test below pins that structurally, because a copy would pass every behavioural test
in this file on the day it was written.

The rest is the boundary the endpoint adds and the script never had -- uploads. The
script reads paths an operator typed; the endpoint reads bytes anybody can POST, so the
refusals have to arrive as 400s carrying the core's own words (a caller reading one
explanation in the app and a different one on the command line for the same file is how
tooling stops being trusted), and the ceilings have to exist at all.

AND IT MUST NOT WRITE. `configs/source_qualification.yml` ships to every install; the
brief's S2 says it stays operator-generated. An endpoint that wrote it would be the app
editing what it ships, so "nothing was written" is asserted against the real file.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.api.main import app  # noqa: E402
from src.catalog.qualification import STATUS_QUALIFIED  # noqa: E402
from src.catalog.qualification_merge import BUNDLE_MEMBER  # noqa: E402
from src.database.models import Base, Source, SourceQualificationAttempt  # noqa: E402
from src.database.session import get_db  # noqa: E402
from src.ingest import clear_kill_switch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "/api/diagnostics/source-qualification-merge"
NOW = datetime(2026, 9, 18, tzinfo=UTC)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    # One app-provided source this instance MEASURED, so `include_this_instance` has
    # something real to contribute rather than an empty list that would pass vacuously.
    src = Source(name="mine", domain="mine.example", tags="news,via:curated",
                 enabled=True, status=STATUS_QUALIFIED,
                 qualified_at=NOW.replace(tzinfo=None), qualification_criteria_version="t")
    s.add(src)
    s.commit()
    s.add(SourceQualificationAttempt(
        source_id=src.id, attempted_at=NOW.replace(tzinfo=None),
        verdict=STATUS_QUALIFIED, criteria_version="t"))
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        clear_kill_switch()


def _export(*rows: dict) -> bytes:
    return json.dumps({"verdicts": list(rows)}).encode("utf-8")


def _row(domain: str, status: str, *, basis: str = "measured", at: str = "2026-05-01") -> dict:
    return {"domain": domain, "status": status, "qualified_at": at,
            "criteria_version": "t", "basis": basis}


def _bundle(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# One implementation
# --------------------------------------------------------------------------- #
def test_the_endpoint_and_the_script_run_the_same_merge_core() -> None:
    """Structural, because behaviour cannot see a copy on the day it is made.

    Both sides are read from source: the script must IMPORT the core rather than define
    `merge`/`render` itself, and the endpoint must import the same module.
    """
    script = (ROOT / "scripts/merge_source_qualification.py").read_text(encoding="utf-8")
    assert "from src.catalog.qualification_merge import" in script
    assert "\ndef merge(" not in script, "the script re-defines the merge instead of importing it"
    assert "\ndef render(" not in script, "the script re-defines the rendering"

    endpoint = (ROOT / "src/api/diagnostics/qualification_merge.py").read_text(encoding="utf-8")
    assert "from src.catalog.qualification_merge import" in endpoint


def test_the_core_never_raises_systemexit() -> None:
    """A core that exits the process on a bad input is fine on a command line and tears
    down a web worker on an upload. The conversion happens in the script, where it belongs;
    this pins that it did not travel with the code.

    Read as CODE, not as text. A substring search over a module that DOCUMENTS this very
    decision fails on its own docstring -- which is what the first cut of this test did,
    and is the difference between checking a claim and checking a spelling.
    """
    import ast

    core = ast.parse((ROOT / "src/catalog/qualification_merge.py").read_text(encoding="utf-8"))
    raised = {
        node.exc.func.id
        for node in ast.walk(core)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
    }
    # Positive control: the core really does refuse things, so an empty set would mean the
    # walk stopped matching rather than that the module is clean.
    assert raised, "the raise extractor found nothing; the core refuses several inputs"
    assert "SystemExit" not in raised, f"the core exits the process: {sorted(raised)}"
    assert "MergeInputError" in raised


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #
def test_a_single_instance_gets_a_merged_overlay_with_no_uploads_at_all(client) -> None:
    """THE POINT OF B5. Before this, producing the file meant exporting by hand and then
    running a script; the operator's own verdicts are now one request away."""
    r = client.post(ENDPOINT, data={"include_this_instance": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged_verdicts"] == 1
    assert "mine.example" in body["overlay_yaml"]
    inputs = body["report"]["inputs"]
    assert [i["route"] for i in inputs] == ["measured here"]
    assert inputs[0]["verdicts"] == 1


def test_an_uploaded_export_merges_beside_this_instances_own_verdicts(client) -> None:
    r = client.post(
        ENDPOINT,
        files=[("files", ("other.json", _export(_row("other.example", "qualified")),
                          "application/json"))],
        data={"include_this_instance": "true"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged_verdicts"] == 2
    assert {i["route"] for i in body["report"]["inputs"]} == {"export json", "measured here"}


def test_an_all_diagnostics_bundle_is_read_by_member_name(client) -> None:
    """The bundle already carries the export, so a maintainer who collected bundles for
    some other reason does not have to go back and re-export."""
    data = _bundle({
        "manifest.json": b"{}",
        BUNDLE_MEMBER: _export(_row("bundled.example", "disqualified")),
    })
    r = client.post(ENDPOINT, files=[("files", ("oo-all.zip", data, "application/zip"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["merged_verdicts"] == 1
    assert body["report"]["inputs"][0]["route"] == "all-diagnostics bundle"


def test_a_disagreement_is_reported_and_left_alone(client) -> None:
    """The refusal that matters most: picking a winner automatically would ship a verdict
    no human ever looked at, to every install, silently."""
    r = client.post(
        ENDPOINT,
        files=[
            ("files", ("a.json", _export(_row("split.example", "qualified")), "application/json")),
            ("files", ("b.json", _export(_row("split.example", "disqualified")), "application/json")),
        ],
        data={"include_this_instance": "false"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    conflicts = body["report"]["conflicts"]
    assert [c["domain"] for c in conflicts] == ["split.example"]
    assert conflicts[0]["resolution"] == "left as-is (needs review)"
    assert "split.example" not in body["overlay_yaml"], (
        "a domain nobody has adjudicated must not reach the shipped file"
    )
    assert body["conflicts_note"].strip()


def test_an_inherited_verdict_is_not_counted_as_a_second_opinion(client) -> None:
    """One measurement seen twice is not two. Driven as a real DISAGREEMENT between a
    measured row and an inherited one: the measured verdict is the only opinion, so there
    is no conflict to report and its verdict is the one that lands."""
    r = client.post(
        ENDPOINT,
        files=[
            ("files", ("m.json", _export(_row("echo.example", "disqualified")),
                       "application/json")),
            ("files", ("i.json", _export(_row("echo.example", "qualified", basis="inherited")),
                       "application/json")),
        ],
        data={"include_this_instance": "false"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report"]["conflicts"] == []
    assert "status: disqualified" in body["overlay_yaml"]


# --------------------------------------------------------------------------- #
# The refusals
# --------------------------------------------------------------------------- #
def test_it_writes_nothing_to_the_shipped_overlay(client) -> None:
    """`configs/source_qualification.yml` ships to every install. The brief keeps it
    operator-generated, so the endpoint hands the text back and the operator commits it."""
    from src.catalog.qualification_overlay import DEFAULT_OVERLAY_PATH

    before = (
        DEFAULT_OVERLAY_PATH.read_bytes() if DEFAULT_OVERLAY_PATH.exists() else None
    )
    r = client.post(ENDPOINT, data={"include_this_instance": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["written"] is False
    after = DEFAULT_OVERLAY_PATH.read_bytes() if DEFAULT_OVERLAY_PATH.exists() else None
    assert after == before, "the endpoint edited the file the app ships"


def test_a_file_that_is_not_an_export_is_refused_with_the_cores_own_words(client) -> None:
    r = client.post(ENDPOINT,
                    files=[("files", ("notes.json", b'{"hello": 1}', "application/json"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400
    assert "verdicts" in r.json()["detail"], r.text


def test_a_zip_without_the_member_is_refused_by_name(client) -> None:
    """NEGATIVE SPACE: the failure that would hurt is merging NOTHING and calling it a
    success -- the operator would ship an overlay believing an instance contributed."""
    data = _bundle({"manifest.json": b"{}", "network.json": b"{}"})
    r = client.post(ENDPOINT, files=[("files", ("wrong.zip", data, "application/zip"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400
    assert BUNDLE_MEMBER in r.json()["detail"]


def test_a_bundle_whose_export_member_failed_reports_that_instead(client) -> None:
    """The instance is fine; its export run was not, and the remedy differs."""
    data = _bundle({BUNDLE_MEMBER + ".error.txt": b"OperationalError: database is locked"})
    r = client.post(ENDPOINT, files=[("files", ("failed.zip", data, "application/zip"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "database is locked" in detail and "re-run the export" in detail


def test_no_inputs_at_all_is_refused_rather_than_writing_an_empty_overlay(client) -> None:
    """Reachable only here: on the command line argparse refuses it, and an endpoint has
    no argparse. An empty merged file would replace every shipped verdict with nothing."""
    r = client.post(ENDPOINT, data={"include_this_instance": "false"})
    assert r.status_code == 400
    assert "Nothing to merge" in r.json()["detail"]


def test_more_uploads_than_the_run_reads_is_refused_naming_the_limit(client) -> None:
    """A ceiling an operator cannot see is a ceiling they will hit without understanding.
    Driven at the real limit rather than at a patched one."""
    from src.api.diagnostics.qualification_merge import _MAX_MERGE_UPLOADS

    files = [
        ("files", (f"e{i}.json", _export(_row(f"d{i}.example", "qualified")), "application/json"))
        for i in range(_MAX_MERGE_UPLOADS + 1)
    ]
    r = client.post(ENDPOINT, files=files, data={"include_this_instance": "false"})
    assert r.status_code == 400
    assert str(_MAX_MERGE_UPLOADS) in r.json()["detail"]
