"""The manifest's ``machine`` block: the build, the libraries, the memory tier and what was set (R119).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT MUST NOT REGRESS, one test each:

1. The record is in the manifest of EVERY build, including one whose members were declined or
   failed, and it is taken BEFORE the members run (a header is the machine as the build found it).
2. It names the switches that are set and never a value: the passphrase's own variable is one of
   them, and neither it nor any other value reaches the record.
3. Every reading is its own: one that cannot be taken says so with its reason and the others stand;
   a build never fails for want of the header.
4. It repeats nothing another member carries (the plan's redundancy rule): no hardware block, no
   transport, nothing the manifest's ``run.hardware`` holds.
5. It stays inside the budget the plan states for it (20 KB).
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from src.api.diagnostics import bundle as B
from src.monitoring import machine_record as MR

SECRET = "pass-phrase \"with' quotes \\ and é"


@pytest.fixture(autouse=True)
def _no_gate(monkeypatch):
    monkeypatch.setattr(B, "ram_declined_reason", lambda *a, **k: None)


def _build(members, **kw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        B._write_all_diagnostics_zip(members, z, **kw)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        return json.loads(z.read("manifest.json")), set(z.namelist())


def test_the_record_has_its_sections_and_reads_the_libraries():
    block = MR.machine_block()
    assert block["version"] == MR.MACHINE_RECORD_VERSION
    for key in ("taken_at", "build", "process", "versions", "memory", "allocator", "environment"):
        assert key in block, key
    versions = block["versions"]
    assert versions["python"].count(".") >= 1
    assert versions["sqlite"].count(".") >= 1
    # the other three are a string or a stated reason, never an empty value
    for lib in ("sqlcipher", "duckdb", "libc"):
        value = versions[lib]
        assert (isinstance(value, str) and value) or (isinstance(value, dict) and value.get("unavailable")), lib
    # the tier the process was resolved to, beside the one the machine gives now
    assert {"resolved", "now", "tier_differs"} <= set(block["memory"])
    assert block["build"]["code"] is not None
    assert block["process"]["pid"] > 0


def test_the_record_is_in_the_manifest_even_when_a_member_is_declined_or_fails(monkeypatch):
    def boom():
        raise RuntimeError("a member that fails")

    monkeypatch.setattr(B, "ram_declined_reason", lambda name, **k: "declined for the test" if name == "no.json" else None)
    manifest, names = _build([("ok.json", lambda: {"a": 1}), ("no.json", lambda: {"b": 2}), ("bad.json", boom)])
    assert "machine" in manifest
    assert manifest["machine"]["version"] == MR.MACHINE_RECORD_VERSION
    assert "no.json.declined.txt" in names and "bad.json.error.txt" in names


def test_the_record_is_taken_before_the_members_run(monkeypatch):
    order = []
    real = MR.machine_block

    def taken():
        order.append("record")
        return real()

    monkeypatch.setattr(MR, "machine_block", taken)
    _build([("a.json", lambda: order.append("member") or {"x": 1})])
    assert order[0] == "record", "the header is the machine as the build FOUND it"


def test_only_the_names_of_the_switches_are_read_never_a_value(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", SECRET)
    monkeypatch.setenv("OO_SOMETHING_ELSE", "a value that must not appear")
    monkeypatch.setenv("NOT_OURS", "not listed")
    block = MR.machine_block()
    env = block["environment"]
    assert "OO_DB_PASSPHRASE" in env["set_names"] and "OO_SOMETHING_ELSE" in env["set_names"]
    assert "NOT_OURS" not in env["set_names"]
    assert env["set_names"] == sorted(env["set_names"])
    text = json.dumps(block, ensure_ascii=False)
    assert "a value that must not appear" not in text
    for form in (SECRET, SECRET.replace("'", "''"), json.dumps(SECRET), repr(SECRET)):
        assert form not in text and form[1:-1] not in text
    manifest, _ = _build([("a.json", lambda: {"x": 1})])
    assert SECRET not in json.dumps(manifest, ensure_ascii=False)


def test_a_reading_that_cannot_be_taken_says_so_and_the_others_stand(monkeypatch):
    import src.config.memory_budget as budget

    def broken():
        raise OSError("the secret path /home/x must not be named")

    monkeypatch.setattr(budget, "reading_vs_now", broken)
    block = MR.machine_block()
    assert block["memory"]["reading_vs_now"] == {"unavailable": "OSError"}, "the type, never the text"
    assert isinstance(block["memory"]["available_now_mb"], float)
    assert block["versions"]["sqlite"] and block["allocator"]
    assert "/home/x" not in json.dumps(block)


def test_a_failure_of_the_whole_record_costs_the_build_nothing(monkeypatch):
    def explode(*a, **k):
        raise ValueError("everything is broken")

    monkeypatch.setattr(MR, "_build", explode)
    block = MR.machine_block()
    assert block == {"version": MR.MACHINE_RECORD_VERSION, "unavailable": "ValueError"}
    # and through the build's own wrapper, an import that fails is a reason as well
    monkeypatch.setattr(MR, "machine_block", explode)
    assert B._machine_record_block() == {"unavailable": "ValueError"}
    manifest, _ = _build([("a.json", lambda: {"x": 1})])
    assert manifest["machine"] == {"unavailable": "ValueError"}


def test_the_record_repeats_nothing_another_member_carries():
    block = MR.machine_block()
    flat = json.dumps(block)
    for held_elsewhere in ("cpu_model", "cpu_physical_cores", "swap_total_bytes", "disk_free_bytes", "transport"):
        assert held_elsewhere not in flat.replace(block["not_here"], ""), held_elsewhere
    assert "wiki-lane-history.json" in block["not_here"] and "run.hardware" in block["not_here"]


def test_the_record_stays_inside_its_budget(monkeypatch):
    for i in range(300):
        monkeypatch.setenv(f"OO_SWITCH_{i:03d}_WITH_A_FAIRLY_LONG_NAME", "v")
    assert len(json.dumps(MR.machine_block(), ensure_ascii=False).encode()) < 20 * 1024
