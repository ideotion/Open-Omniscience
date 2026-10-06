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


def test_an_unreadable_repair_record_reaches_the_merge_report(client, monkeypatch) -> None:
    """The warning used to stop at the YAML file: the merge fed this instance in as verdict rows
    only, so the rows an unreadable repair run withdrew counted as measured corroboration with
    nothing said. It now travels in the report's inputs, for this instance and for an uploaded
    export JSON that carries it."""
    import src.catalog.qualification_integrity as qi

    ok = client.post(ENDPOINT, data={"include_this_instance": "true"}).json()
    assert "repair_record_unreadable" not in ok["report"]["inputs"][0]

    monkeypatch.setattr(qi, "repaired_rows", lambda: ({}, ["2026-09-30T00:00:00+00:00"]))
    flagged = json.dumps({
        "verdicts": [_row("other.example", "qualified")],
        "basis": {"repair_record_unreadable": True, "repair_runs_unreadable": ["2026-10-01T00:00:00+00:00"]},
    }).encode("utf-8")
    r = client.post(
        ENDPOINT, files=[("files", ("other.json", flagged, "application/json"))],
        data={"include_this_instance": "true"})
    assert r.status_code == 200, r.text
    by_route = {i["route"]: i for i in r.json()["report"]["inputs"]}
    assert by_route["measured here"]["repair_record_unreadable"] is True
    assert by_route["measured here"]["repair_runs_unreadable"] == ["2026-09-30T00:00:00+00:00"]
    assert by_route["export json"]["repair_runs_unreadable"] == ["2026-10-01T00:00:00+00:00"]
    # nothing is refused or changed: the merge still runs, the warning is beside it
    assert r.json()["merged_verdicts"] == 2


def test_the_warning_survives_the_bundle_route_and_the_panels_own_yaml_export(client, monkeypatch) -> None:
    """Export on each instance, then Merge: the Export button saves YAML, and a bundle is the other
    road. Both used to lose the flag (the YAML carried it as a comment a parser drops). Both inputs
    are the app's own output, fetched from the real export route."""
    import src.catalog.qualification_integrity as qi

    export_route = "/api/diagnostics/source-qualification-export"
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({}, ["2026-10-01T00:00:00+00:00"]))
    member = client.get(export_route)  # the JSON member a bundle carries
    assert member.status_code == 200, member.text
    r = client.post(ENDPOINT, files=[("files", (
        "bundle.zip", _bundle({BUNDLE_MEMBER: member.content}), "application/zip"))],
        data={"include_this_instance": "false"})
    assert r.status_code == 200, r.text
    entry = r.json()["report"]["inputs"][0]
    assert entry["route"] == "all-diagnostics bundle"
    assert entry["repair_runs_unreadable"] == ["2026-10-01T00:00:00+00:00"]

    # this instance's own YAML export with an unreadable record, uploaded back
    yml = client.get(export_route + "?fmt=yaml")
    assert yml.status_code == 200, yml.text
    r = client.post(ENDPOINT, files=[("files", ("export.yml", yml.content, "text/yaml"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 200, r.text
    entry = r.json()["report"]["inputs"][0]
    assert entry["route"] == "export json" and entry["repair_runs_unreadable"] == ["2026-10-01T00:00:00+00:00"]
    # and a readable record adds nothing to either
    monkeypatch.setattr(qi, "repaired_rows", lambda: ({}, []))
    assert b"repair_record_unreadable" not in client.get(export_route + "?fmt=yaml").content
    assert client.get(export_route).json()["basis"]["repair_record_unreadable"] is False


def test_the_merge_panel_shows_the_unreadable_repair_record_warning() -> None:
    """The panel must write the warning from the report's inputs, in a translated string."""
    js = (ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    assert "repair_record_unreadable" in js
    key = "The record of the boot repair could not be read in full for: {names}."
    assert key in js
    for lang in ("en", "fr", "ar", "zh"):
        loc = json.loads((ROOT / f"src/static/locales/{lang}.json").read_text(encoding="utf-8"))
        assert any(k.startswith(key) for k in loc), lang


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


def test_a_yaml_upload_with_an_impossible_date_is_a_400_not_a_500(client) -> None:
    """The YAML reader recognises 2026-13-45 as a date and the calendar refuses it with a
    ValueError, which used to escape the reader as a 500 on an upload anybody can make."""
    body = b"verdicts:\n  - domain: a.example\n    status: qualified\n    basis: measured\n    qualified_at: 2026-13-45\n"
    r = client.post(ENDPOINT, files=[("files", ("export.yml", body, "text/yaml"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400, r.text
    assert "cannot be read" in r.json()["detail"]
    # fixed words, never the library's message: a YAML tag's ValueError carries the upload's text
    body = b"verdicts: !!int secretPASSPHRASE\n"
    r = client.post(ENDPOINT, files=[("files", ("export.yml", body, "text/yaml"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400, r.text
    assert "secretPASSPHRASE" not in r.text


def test_an_upload_nested_too_deeply_is_a_400_not_a_500(client) -> None:
    """A hundred thousand opening brackets raised RecursionError out of the JSON reader."""
    for name, body in (("deep.json", b"[" * 100_000), ("deep-object.json", b'{"a":' * 100_000)):
        r = client.post(ENDPOINT, files=[("files", (name, body, "application/json"))],
                        data={"include_this_instance": "false"})
        assert r.status_code == 400, (name, r.text)
        assert "nested too deeply" in r.json()["detail"]
    # the same inside a bundle's export member
    r = client.post(ENDPOINT, files=[("files", (
        "deep.zip", _bundle({BUNDLE_MEMBER: b"[" * 100_000}), "application/zip"))],
        data={"include_this_instance": "false"})
    assert r.status_code == 400, r.text
    assert "nested too deeply" in r.json()["detail"]
    # the YAML stage has its own handler: this is not JSON, so it is the one that refuses
    r = client.post(ENDPOINT, files=[("files", ("deep.yml", b"- " * 100_000 + b"x", "text/yaml"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400, r.text
    assert "nested too deeply" in r.json()["detail"]


def test_other_malformed_uploads_are_a_400_not_a_500(client) -> None:
    """Found by the read of the 500s fix: the same family, other exception types. An integer past
    Python's digit limit (a ValueError, not a JSONDecodeError), a bundle member that is not UTF-8, a
    zip whose directory is damaged, and rows that are not mappings (skipped, not a crash)."""
    def post(name, body, kind):
        return client.post(ENDPOINT, files=[("files", (name, body, kind))],
                           data={"include_this_instance": "false"})

    big = b'{"verdicts": [], "n": ' + b"9" * 5000 + b"}"
    r = post("big.json", big, "application/json")
    assert r.status_code == 400 and "too long to read" in r.json()["detail"], r.text
    r = post("big.zip", _bundle({BUNDLE_MEMBER: big}), "application/zip")
    assert r.status_code == 400 and "too long to read" in r.json()["detail"], r.text
    r = post("latin.zip", _bundle({BUNDLE_MEMBER: b'{"verdicts": "\xff\xfe"}'}), "application/zip")
    assert r.status_code == 400 and "not readable text" in r.json()["detail"], r.text
    # damaged zip directories: every single-byte flip is refused, never a 500
    good = _bundle({BUNDLE_MEMBER: json.dumps({"verdicts": [_row("a.example", "qualified")]}).encode()})
    for i in range(len(good)):
        damaged = bytearray(good)
        damaged[i] ^= 0xFF
        r = post("d.zip", bytes(damaged), "application/zip")
        assert r.status_code in (200, 400), (i, r.status_code, r.text[:200])
    # a local header that names the member differently from the directory: the library's message
    # prints that name, which is the upload's own text and must not come back in the refusal
    renamed = bytearray(good)
    renamed[30:30 + len(BUNDLE_MEMBER)] = b"secretPASSPHRASE".ljust(len(BUNDLE_MEMBER), b"x")
    r = post("renamed.zip", bytes(renamed), "application/zip")
    assert r.status_code == 400 and "secretPASSPHRASE" not in r.text, r.text
    rows = {"verdicts": [3, "x", None, _row("a.example", "qualified")]}
    r = post("rows.json", json.dumps(rows).encode(), "application/json")
    assert r.status_code == 200, r.text


def test_a_bundle_with_a_corrupt_compressed_stream_is_a_400_not_a_500(client) -> None:
    """The archive's headers are intact and the compressed bytes are not: zlib.error escaped the
    reader (only BadZipFile was caught)."""
    buf = io.BytesIO()
    rows = [_row(f"d{i}.example", "qualified") for i in range(2000)]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(BUNDLE_MEMBER, json.dumps({"verdicts": rows}))
    damaged = bytearray(buf.getvalue())
    start = 30 + len(BUNDLE_MEMBER)  # the local header, then the compressed stream
    for i in range(start + 4, start + 40):
        damaged[i] ^= 0xFF
    r = client.post(ENDPOINT, files=[("files", ("damaged.zip", bytes(damaged), "application/zip"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400, r.text
    assert "not a readable zip archive" in r.json()["detail"]


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
