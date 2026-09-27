"""Row S of the 2026-09-27 re-walk, pinned: S-1/S-2, S-3, S-5, S-6, S-7, S-9, S-11, S-12.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each defect was reproduced in Chromium on the row's encrypted seed and checked there
after the fix. CI runs no browser, so the behavioural halves run as real code under node
(``tests/clickthrough_rewalk_b28_node_test.js``, fed the SERVER'S OWN payloads from here),
the layout half of S-1/S-2 is pinned by ``tests/quality_gates_repaint_node_test.js``, and
this file pins the server side:

* S-5 -- the memory floor's reason travels as a keyed frame, and its English is FILLED
  from that frame, so the two cannot drift; the status route forwards the frame;
* S-6 -- every merge refusal is a keyed frame with the file name as a data slot, and the
  route returns it beside the unchanged English ``detail``;
* S-9 -- the three server sentences the panel draws carry no ASCII ``--``;
* every new frame is keyed in all twelve locales with its holes intact.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.api.main import app  # noqa: E402
from src.catalog import qualification_merge as QM  # noqa: E402
from src.config import machine_floor as MF  # noqa: E402
from src.database.models import Base  # noqa: E402
from src.database.session import get_db  # noqa: E402
from src.ingest import clear_kill_switch  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"
_CODES = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")
_MERGE = "/api/diagnostics/source-qualification-merge"
_HOLE = re.compile(r"\{(\w+)\}")


def _locale(code: str) -> dict:
    return json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def _assert_keyed(frames, where: str) -> None:
    frames = list(frames)
    assert frames, f"no frames to check for {where}"
    for code in _CODES:
        d = _locale(code)
        for f in frames:
            assert f in d and d[f].strip(), f"{code}.json is missing {f!r} ({where})"
            assert set(_HOLE.findall(d[f])) == set(_HOLE.findall(f)), (
                f"{code}.json changed the holes of {f!r}: {d[f]!r}"
            )


def _fill_en(frame: str, values: dict) -> str:
    # The historical English: whole megabytes, ungrouped, except "a nominal 4,096 MB
    # machine" (tests/test_memory_budget.py pins that wording).
    def one(m):
        v = values[m.group(1)]
        if isinstance(v, dict):
            return _fill_en(v["i18n"], v.get("vars") or {})
        if isinstance(v, (int, float)):
            return f"{v:,.0f}" if m.group(1) == "nominal" else f"{v:.0f}"
        return str(v)

    return _HOLE.sub(one, frame)


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    app.dependency_overrides[get_db] = lambda: s
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        clear_kill_switch()


# --------------------------------------------------------------------------- #
# S-5 -- the floor's reason is a keyed frame
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("total, avail", [
    (3924.0, 800.0),      # the field's machine A: both halves under
    (3379.0, 1500.0),     # total only
    (16384.0, 300.0),     # available only
    (8192.0, 4096.0),     # above both
    (4093.8, 500.0),      # a nominal 4 GB machine, available under
])
def test_the_floor_reason_is_its_frame_filled_in_english(total, avail) -> None:
    """The English ``reason`` is MADE from the frame, so what a log line reads and what a
    translated surface says are one sentence. Checked by filling the frame independently."""
    v = MF.machine_floor(override=False, total_mb=total, available_mb=avail)
    assert v["reason_i18n"] in MF.REASON_FRAMES
    assert v["reason"] == _fill_en(v["reason_i18n"], v["reason_vars"])
    # Every nested clause is one of the keyed frames too, never free prose.
    for clause in v["reason_vars"].values():
        assert clause["i18n"] in MF.REASON_FRAMES, clause


def test_the_unmeasured_reason_is_a_frame_too(monkeypatch) -> None:
    monkeypatch.setattr(MF, "_mem_readings", lambda: (None, None))
    v = MF.machine_floor(override=False)
    assert v["reason_i18n"] in MF.REASON_FRAMES and v["reason_vars"] == {}
    assert v["reason"] == v["reason_i18n"]


def test_every_floor_reason_frame_is_keyed_in_all_twelve_locales() -> None:
    assert len(MF.REASON_FRAMES) >= 11, "the frame list shrank; the extractor stopped matching"
    _assert_keyed(MF.REASON_FRAMES, "machine_floor reason")


def test_the_status_route_forwards_the_reason_frame(monkeypatch, tmp_path) -> None:
    real = MF.machine_floor
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(MF, "machine_floor", lambda **k: real(override=False, total_mb=3924.0,
                                                                available_mb=800.0))
    with TestClient(app) as c:
        fl = c.get("/api/sources/qualify-bulk/status").json()["floor"]
    assert fl["declines"] is True
    assert fl["reason_i18n"] == "this machine has {ram} with {available} — {verdict}"
    assert fl["reason_vars"]["ram"]["vars"]["mb"] == 3924.0


def test_a_declined_job_carries_the_reason_frame_to_its_result_and_its_line(monkeypatch) -> None:
    """The job's own decline (the run the button used to start) writes the same clause."""
    import src.catalog.qualify_job as qj

    budget = MF.scan_budget(1000, override=False, total_mb=3924.0, available_mb=800.0)
    decline = {"enabled": True, "evaluated": 0, "skipped": "memory",
               **{k: budget[k] for k in ("available_mb", "need_mb", "reason", "reason_i18n",
                                         "reason_vars", "caveat", "override_env")}}
    monkeypatch.setattr(qj, "qualification_pass", lambda *a, **k: dict(decline))

    class _Ctx:
        stopping = False

        def __init__(self) -> None:
            self.progress: list[dict] = []

        def set_progress(self, **kw):
            self.progress.append(kw)

    from contextlib import contextmanager

    engine = create_engine("sqlite://", future=True, poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()

    @contextmanager
    def _scope():
        yield session

    ctx = _Ctx()
    out = qj.run_bulk_qualification(ctx, fetcher=object(), session_factory=_scope, batch_size=5)
    assert out["declined"]["reason_i18n"] == budget["reason_i18n"]
    assert out["paused_reason_vars"]["reason"] == {"i18n": budget["reason_i18n"],
                                                   "vars": budget["reason_vars"]}
    # The English line is unchanged: the reason is still the floor's own sentence.
    assert budget["reason"] in out["paused_reason"]
    session.close()


# --------------------------------------------------------------------------- #
# S-6 -- the merge refusals are keyed frames
# --------------------------------------------------------------------------- #
def test_every_merge_refusal_is_a_frame_with_the_file_as_data() -> None:
    cases = [
        (QM.rows_from_export_bytes, b'{"hello": "world"}', QM.REFUSE_NO_VERDICTS),
        (QM.rows_from_export_bytes, b"PK\x03\x04junk", QM.REFUSE_ZIP_AS_EXPORT),
        (QM.rows_from_export_bytes, b"\xff\xfe\x00bad", QM.REFUSE_NOT_TEXT),
        (QM.rows_from_export_bytes, b"{not: [valid", QM.REFUSE_NOT_JSON_OR_YAML),
        (QM.rows_from_export_bytes,
         QM.render({"a.example": {"domain": "a.example", "status": "qualified",
                                  "qualified_at": "2026-05-01", "criteria_version": "t"}}).encode(),
         QM.REFUSE_OVERLAY),
        (QM.rows_from_bundle_bytes, b"not a zip at all", QM.REFUSE_BAD_ZIP),
    ]
    for fn, data, frame in cases:
        with pytest.raises(QM.MergeInputError) as e:
            fn(data, "upload.json")
        assert e.value.i18n == frame, (frame, e.value.i18n)
        assert e.value.vars["file"] == "upload.json"
        assert str(e.value) == _HOLE.sub(lambda m: str(e.value.vars[m.group(1)]), frame)
        assert " -- " not in str(e.value), "an ASCII -- in a refusal the panel shows"


def test_every_raise_in_the_merge_core_uses_a_listed_frame() -> None:
    """Read as CODE: every ``raise MergeInputError(...)`` passes one of the module's frame
    constants, so a new refusal cannot ship as free English prose."""
    tree = ast.parse((_ROOT / "src/catalog/qualification_merge.py").read_text(encoding="utf-8"))
    used = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name) and node.exc.func.id == "MergeInputError"):
            arg = node.exc.args[0] if node.exc.args else None
            assert isinstance(arg, ast.Name) and arg.id.startswith("REFUSE_"), ast.dump(node)[:200]
            used.append(getattr(QM, arg.id))
    assert len(used) >= 10, f"the raise walk found {len(used)}; expected the ten refusals"
    assert set(used) <= set(QM.REFUSAL_FRAMES)


def test_every_merge_refusal_frame_is_keyed_in_all_twelve_locales() -> None:
    assert len(QM.REFUSAL_FRAMES) >= 13, "the core's ten refusals and the route's three"
    _assert_keyed(QM.REFUSAL_FRAMES, "merge refusals")


def test_the_route_refuses_only_with_the_cores_frames() -> None:
    """Read as CODE: the route's every ``refuse(...)`` passes a listed frame or the core
    exception's own, never free prose."""
    tree = ast.parse((_ROOT / "src/api/diagnostics/qualification_merge.py")
                     .read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "refuse"]
    assert len(calls) == 4, f"expected the route's four refusals, found {len(calls)}"
    for c in calls:
        arg = c.args[0]
        ok = (isinstance(arg, ast.Name) and arg.id.startswith("REFUSE_")) or (
            isinstance(arg, ast.Attribute) and arg.attr == "i18n")
        assert ok, ast.dump(c)[:200]
    raises = [n for n in ast.walk(tree) if isinstance(n, ast.Raise)]
    assert not raises, "a refusal raised as an HTTPException carries no frame"


def test_the_route_returns_the_frame_beside_the_unchanged_english_detail(client) -> None:
    r = client.post(_MERGE, files=[("files", ("not-an-export.json", b'{"hello": "world"}',
                                              "application/json"))],
                    data={"include_this_instance": "false"})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"] == ("not-an-export.json: no 'verdicts' list — is this a "
                              "source-qualification export?")
    assert body["detail_i18n"] == QM.REFUSE_NO_VERDICTS
    assert body["detail_vars"] == {"file": "not-an-export.json"}
    r = client.post(_MERGE, data={"include_this_instance": "false"})
    assert r.status_code == 400 and r.json()["detail_i18n"].startswith("Nothing to merge")


# --------------------------------------------------------------------------- #
# S-9 -- the server sentences the panel draws use the typographic dash
# --------------------------------------------------------------------------- #
def _prose(path: str, func: str, keys: tuple[str, ...]) -> dict[str, str]:
    tree = ast.parse((_ROOT / path).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    for k, v in zip(sub.keys, sub.values, strict=False):
                        if isinstance(k, ast.Constant) and k.value in keys:
                            out[k.value] = ast.literal_eval(v)
    return out


def _audit_prose() -> dict[str, str]:
    return _prose("src/catalog/qualification.py", "admission_audit", ("caveat", "coverage_note"))


def test_the_panels_server_sentences_carry_no_ascii_double_dash() -> None:
    audit = _audit_prose()
    merge = _prose("src/api/diagnostics/qualification_merge.py", "source_qualification_merge",
                   ("note", "conflicts_note"))
    found = {**audit, **{"merge " + k: v for k, v in merge.items()}}
    assert len(found) == 4, f"the prose walk found {sorted(found)}"
    for label, text in found.items():
        assert " -- " not in text, f"{label} still carries an ASCII --: {text!r}"
    _assert_keyed(found.values(), "the panel's server prose")


# --------------------------------------------------------------------------- #
# The client's new frames, x12
# --------------------------------------------------------------------------- #
def test_the_panels_new_frames_are_keyed_in_all_twelve_locales() -> None:
    frames = [
        "{n} of {total} collecting sources are not accounted for here.",
        "{n} candidate awaiting qualification.",
        "{n} candidates awaiting qualification.",
        "Adopted {n} verdict; {admitted} source started being collected.",
        "Adopted {n} verdict; {admitted} sources started being collected.",
        "Adopted {n} verdicts; {admitted} source started being collected.",
        "Adopted {n} verdicts; {admitted} sources started being collected.",
        "Put back {n} source; {undone} admission undone.",
        "Put back {n} source; {undone} admissions undone.",
        "Put back {n} sources; {undone} admission undone.",
        "Put back {n} sources; {undone} admissions undone.",
    ]
    ui = (_ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    for f in frames:
        assert f'"{f}"' in ui, f"the renderer no longer asks for {f!r}"
    _assert_keyed(frames, "the Quality gates panel")
    # The count's full stop is the locale's own, so a following sentence reads as one.
    for code in _CODES:
        v = _locale(code)["{n} of {total} collecting sources are not accounted for here."]
        assert v.rstrip()[-1] in ".。।", f"{code}: the gap line has no full stop: {v!r}"


# --------------------------------------------------------------------------- #
# The behavioural half, fed the server's own payloads
# --------------------------------------------------------------------------- #
def test_the_b28_node_suite_passes_on_the_servers_own_payloads() -> None:
    floor = MF.machine_floor(override=False, total_mb=3924.0, available_mb=800.0)
    with pytest.raises(QM.MergeInputError) as e:
        QM.rows_from_export_bytes(b'{"hello": "world"}', "not-an-export.json")
    refusal = QM.refusal_payload(e.value.i18n, **e.value.vars)
    payloads = {
        "floor": {k: floor[k] for k in ("declines", "below", "overridden", "reason",
                                        "reason_i18n", "reason_vars", "override_env")},
        "refusal": refusal,
        "audit": _audit_prose(),
    }
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_rewalk_b28_node_test.js")],
        capture_output=True, text=True, check=False,
        env={"PATH": __import__("os").environ.get("PATH", ""), "B28_PAYLOADS": json.dumps(payloads)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout
