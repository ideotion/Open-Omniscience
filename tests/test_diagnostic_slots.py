"""The zip's members: the slot table, an area per member, the slim debug bundle, the merged members (R119).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT MUST NOT REGRESS, one group of tests each:

1. THE SLOT TABLE is well formed, and a slot is exactly one of three things: a member of this build
   (its module is here and its function exists), an absence the manifest NAMES (its module is not in
   this build yet), or an ERROR (its module is here and its function is not: a typo or a rename can
   never read as "not built yet"). A producer that states its own budget as a default agrees with the
   table, and the budgets add to the stated total.
2. EVERY MEMBER HAS AN AREA, and the area table names no member that is not written.
3. THE MANIFEST says per slot member what it was asked to keep, and ``over_budget`` only for one that
   wrote more; and it names the slots not built.
4. NO TWO MEMBERS CARRY THE SAME SUBTREE (300 bytes or more): the guard that found the duplicates of
   the old archive (storage in session-forensics and in the storage members, the rolling log's counts
   in two places, a bundle that embedded eight members). It is checked against a real run of the
   record members, and against a synthetic duplicate so it cannot pass by looking at nothing.
5. THE SLIM DEBUG BUNDLE names the members it does not repeat, does not build them (the work is not
   paid twice), keeps ``collect_perf`` to its newest ticks, and is slim only when asked explicitly.
6. THE SESSION FORENSICS member names the blocks that stand alone, and the route is whole.
7. ``ai.json`` carries the four last-run summaries that used to be members of their own: its ``jobs``
   are what those four routes return.
8. THE VITALS HISTORY names the member that carries the minutes before a kill, and that member exists.
"""

from __future__ import annotations

import base64
import io
import json
import random
import zipfile
from collections import defaultdict
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import diagnostics as d
from src.api import diagnostics_plan as plan
from src.api import diagnostics_slots as slots
from src.api import diagnostics_volumes as dv
from src.api.diagnostics import bundle as b
from src.database.models import Base, Source


# ---------------------------------------------------------------------------------------------------
#  Fixtures and small producers the tests point a slot at
# ---------------------------------------------------------------------------------------------------
@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'store.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _no_gate(monkeypatch):
    monkeypatch.setattr(b, "ram_declined_reason", lambda *a, **k: None)


def lean_member(max_bytes: int) -> dict:
    """A producer that keeps well inside what it was asked to."""
    return {"rows": [1, 2, 3], "asked": max_bytes}


def fat_member(max_bytes: int) -> dict:
    """A producer that writes about twice what it was asked to."""
    return {"blob": "x" * (2 * max_bytes), "asked": max_bytes}


SECRET = "correct horse battery staple 42"


def leaky_member(max_bytes: int) -> dict:
    """A producer that catches its own failure and returns the engine's words, which quote the key statement: the shape
    two producers had (cut raw, never scrubbed) before the slot wrapper put a net under every answer."""
    return {
        "error": f"RuntimeError: near '{SECRET}': syntax error [SQL: PRAGMA key = '{SECRET}']",
        "rows": [{"note": f"tail {SECRET}"}, 3],
        "asked": max_bytes,
    }


class _LeafQuotingTheSecret:
    """An object a producer left in its answer, whose own text quotes a held secret (as an ORM object or an exception does)."""

    def __str__(self) -> str:
        return f"leaf: {SECRET}"

    __repr__ = __str__


def leafy_member(max_bytes: int) -> dict:
    """A producer whose answer holds leaves JSON cannot: a datetime, a set, an object whose text is the secret."""
    from datetime import datetime

    return {"when": datetime(2026, 10, 13, 1, 2, 3), "set": {3}, "leaf": _LeafQuotingTheSecret(), "n": 1, "tail": [1, "x"]}


def giant_member(max_bytes: int) -> dict:
    """A producer far over what it was asked to keep: about 9 MB of records that do not compress."""
    rnd = random.Random(17)
    return {
        "asked": max_bytes,
        "records": [{"i": i, "v": base64.b64encode(rnd.randbytes(225)).decode()} for i in range(30_000)],
    }


def _slot(name, target, budget, area="memory"):
    return slots.Slot(name, target, "test", budget, area)


def _build(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        results = b._write_all_diagnostics_zip(members, z)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        return json.loads(z.read("manifest.json")), set(z.namelist()), results


def _member_names():
    return [name for name, _fn in d._all_diagnostics_members(None)]


# ---------------------------------------------------------------------------------------------------
#  1. The slot table
# ---------------------------------------------------------------------------------------------------
def test_the_table_is_well_formed():
    names = [s.name for s in slots.SLOTS]
    assert len(set(names)) == len(names), "two slots write the same file"
    assert len({s.target for s in slots.SLOTS}) == len(slots.SLOTS), "two slots call one producer"
    for s in slots.SLOTS:
        assert s.name.endswith(".json") and "/" not in s.name, s.name
        assert ":" in s.target and s.owner, s
        assert isinstance(s.budget_bytes, int) and s.budget_bytes > 0, s
        assert s.area in plan.AREAS, s
    assert sum(s.budget_bytes for s in slots.SLOTS) <= slots.TOTAL_BUDGET_BYTES
    # a name is in ONE place: the slot's own area or the plan's table, never both
    assert not set(names) & set(plan.MEMBER_AREAS)


def test_every_slot_is_a_member_of_this_build_or_named_absent_and_never_both():
    present = {name for name, _fn in slots.members()}
    absent = {row["file"] for row in slots.not_in_build()}
    assert not present & absent
    assert present | absent == {s.name for s in slots.SLOTS}
    assert all(row["state"] == "not-in-build" and row["target"] and row["owner"] for row in slots.not_in_build())
    # the five built producers are in this build, and are members of the real list: a misspelled module path reads
    # as "not in build", so the built slots are NAMED here and the one absent slot is the one not written yet
    for built in ("vitals.json", "runs.json", "pressure-light.json", "boots.json", "database-damage.json"):
        assert built in present and built in _member_names()
    assert absent == {"keyword-pipeline.json"}, "a slot built since: add it to the tuple above and drop it from this set"


def test_a_slot_whose_module_is_here_has_the_function_it_names():
    import inspect

    for s in slots.SLOTS:
        if not slots.module_in_build(s):
            continue
        fn = slots.resolve(s)  # raises when the module is here and the function is not
        params = inspect.signature(fn).parameters
        assert "max_bytes" in params, f"{s.target} does not take the budget it is given"
        default = params["max_bytes"].default
        if default is not inspect.Parameter.empty:
            assert default == s.budget_bytes, (
                f"{s.name}: the producer's own default ({default}) and the table ({s.budget_bytes}) "
                "must be one number"
            )


def test_a_function_missing_from_a_module_that_is_here_is_an_error_never_an_absence(monkeypatch):
    typo = _slot("typo.json", "src.api.diagnostics_plan:no_such_function", 1000)
    assert slots.module_in_build(typo)
    with pytest.raises(AttributeError, match="no callable no_such_function"):
        slots.resolve(typo)
    monkeypatch.setattr(slots, "SLOTS", (typo,))
    assert slots.not_in_build() == [] and [n for n, _ in slots.members()] == ["typo.json"]
    manifest, names, results = _build(slots.members())
    assert "typo.json.error.txt" in names and "typo.json" not in names
    assert results[0]["outcome"] == "error"
    assert "no callable no_such_function" in results[0]["error"]


def test_a_module_that_is_not_here_writes_no_file_and_the_manifest_names_it(monkeypatch):
    gone = _slot("gone.json", "src.no_such_module_for_the_test:diagnostics_member", 1000)
    here = _slot("lean.json", "tests.test_diagnostic_slots:lean_member", 1000)
    monkeypatch.setattr(slots, "SLOTS", (gone, here))
    assert not slots.module_in_build(gone)
    manifest, names, _results = _build(slots.members())
    assert "gone.json" not in names and not any(n.startswith("gone.json") for n in names)
    assert manifest["slots"]["not_in_build"] == [
        {"file": "gone.json", "owner": "test", "target": gone.target, "state": "not-in-build"}
    ]
    assert "lean.json" in names


# ---------------------------------------------------------------------------------------------------
#  2. An area per member
# ---------------------------------------------------------------------------------------------------
def test_every_member_has_an_area_and_the_table_names_no_member_that_is_not_written():
    names = _member_names()
    for name in names:
        assert slots.area_of(name) in plan.AREAS, f"{name} has no area (add it to diagnostics_plan.MEMBER_AREAS)"
    stale = set(plan.MEMBER_AREAS) - set(names)
    assert not stale, f"areas for members that are not written: {sorted(stale)}"
    assert set(plan.MEMBER_AREAS.values()) <= set(plan.AREAS)


def test_a_member_without_an_area_reads_as_unclassified_in_the_manifest():
    assert slots.area_of("never-heard-of.json") == plan.UNCLASSIFIED_AREA
    _manifest, _names, results = _build([("never-heard-of.json", lambda: {"a": 1})])
    assert results[0]["area"] == plan.UNCLASSIFIED_AREA


# ---------------------------------------------------------------------------------------------------
#  3. What the manifest says about a slot member
# ---------------------------------------------------------------------------------------------------
def test_the_manifest_says_what_a_slot_was_asked_and_names_one_that_wrote_more(monkeypatch):
    lean = _slot("lean.json", "tests.test_diagnostic_slots:lean_member", 5000)
    fat = _slot("fat.json", "tests.test_diagnostic_slots:fat_member", 2000, area="storage")
    monkeypatch.setattr(slots, "SLOTS", (lean, fat))
    _manifest, _names, results = _build(slots.members())
    by = {r["file"]: r for r in results}
    assert by["lean.json"]["budget_bytes"] == 5000 and "over_budget" not in by["lean.json"]
    assert by["lean.json"]["area"] == "memory"
    assert by["fat.json"]["budget_bytes"] == 2000 and by["fat.json"]["over_budget"] is True
    assert by["fat.json"]["bytes"] > 2000 and by["fat.json"]["area"] == "storage"
    # the producer's answer is NOT cut by the wrapper (a cut that is not its own breaks its structure)
    assert by["fat.json"]["ok"] is True
    # a member that is not a slot carries no budget
    _m, _n, plain = _build([("plain.json", lambda: {"a": 1})])
    assert "budget_bytes" not in plain[0] and "over_budget" not in plain[0]


def test_a_secret_a_producer_wrote_into_its_answer_does_not_reach_the_archive(monkeypatch):
    """The net under every slot: the passphrase the process holds is taken out of the answer's strings, wherever it sits
    (an error line, a list inside a dict), and the structure and numbers of the answer are kept."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    slot = _slot("leaky.json", "tests.test_diagnostic_slots:leaky_member", 5000)
    monkeypatch.setattr(slots, "SLOTS", (slot,))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        b._write_all_diagnostics_zip(slots.members(), z)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        everything = b"".join(z.read(n) for n in z.namelist()).decode("utf-8", "replace")
        member = json.loads(z.read("leaky.json"))
    assert SECRET not in everything and SECRET.replace(" ", "\\u0020") not in everything
    assert member["rows"][1] == 3 and member["asked"] == 5000 and "RuntimeError" in member["error"]
    assert "redacted" in member["error"].lower()


def test_a_leaf_json_cannot_hold_is_the_stated_marker_and_never_its_text(monkeypatch):
    """The net round-trips the answer through the member encoder BEFORE it scrubs: ``scrubbed_value`` alone would write
    ``str(leaf)`` (a memory address for an object, an unmarked string for a datetime), which the encoder's own rule forbids.
    The object's text, which quotes the held secret, is not carried at all."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)
    out = slots.thunk(_slot("leafy.json", "tests.test_diagnostic_slots:leafy_member", 5000))()
    text = json.dumps(out)
    assert SECRET not in text and "0x" not in text and "leaf:" not in text
    for key, kind in (("when", "datetime"), ("set", "set"), ("leaf", "_LeafQuotingTheSecret")):
        assert out[key][b._UNSERIALISABLE] is True and out[key]["type"] == kind, key
    assert out["n"] == 1 and out["tail"] == [1, "x"]


def test_a_failing_selftest_s_own_words_do_not_carry_a_held_passphrase_into_the_archive(monkeypatch):
    """``selftests.json`` is not a slot, and a failing self-test writes its whole answer (the ``recursive-loop`` row quotes the
    exception's text): the answer goes through the same net, and the verdict and the counts are read from what is written."""
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", SECRET)

    def failing():
        return {
            "summary": {"total": 2, "passed": 1, "failed": 1},
            "rows": [{"gate": "g", "error": f"RuntimeError: near '{SECRET}': syntax error [SQL: PRAGMA key = '{SECRET}']"}],
        }

    loop: list = []
    loop.append(loop)
    calls = [
        ("failing", failing),
        ("good", lambda: {"passed": True, "total": 2, "failed_count": 0}),
        ("cyclic", lambda: {"summary": {"total": 1, "passed": 0, "failed": 1}, "again": loop}),
    ]
    monkeypatch.setattr(b, "_selftest_calls", lambda: calls)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        b._write_all_diagnostics_zip([("selftests.json", b._selftests_member)], z)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        everything = b"".join(z.read(n) for n in z.namelist()).decode("utf-8", "replace")
        member = json.loads(z.read("selftests.json"))
    assert SECRET not in everything and SECRET.replace(" ", "\\u0020") not in everything
    bad = member["tests"]["failing"]
    assert bad["verdict"] == "fail" and (bad["total"], bad["failed"]) == (2, 1), "the counts survive the scrub"
    assert "RuntimeError" in bad["output"]["rows"][0]["error"] and "redacted" in bad["output"]["rows"][0]["error"].lower()
    assert "output" not in member["tests"]["good"]
    # an answer the encoder cannot read at all (a cycle) is an `error` with the class named, and none of it is written
    assert member["tests"]["cyclic"]["verdict"] == "error" and "output" not in member["tests"]["cyclic"]
    assert member["summary"]["error"] == 1 and member["summary"]["fail"] == 1 and member["summary"]["all_pass"] is False


def test_the_built_slot_producers_hold_the_numbers_the_table_states():
    """vitals and runs are held to their budget by their own code; the pressure tail is measured: the
    16 snapshots it can hold (8 per session, two sessions) fit with room, with none dropped."""
    from src.monitoring import session_hwm as hwm

    for name in ("vitals.json", "runs.json"):
        value = dict(slots.members())[name]()
        assert len(json.dumps(value, default=str).encode()) <= slots.budget_of(name), name
    # the other two built producers answer within the number the table states (a young install writes a small part of it; the
    # damage budget and the boots budget at full retention have their own tests), and the table's boots number IS the producer's
    from src.monitoring import boots

    assert slots.budget_of("boots.json") == boots.DEFAULT_MAX_BYTES
    for name in ("boots.json", "database-damage.json"):
        value = dict(slots.members())[name]()
        assert len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) <= slots.budget_of(name), name
    readings = {"avail_mb": 900.0, "total_mb": 3900.0, "rss_mb": 800.0, "swap_used_mb": 100.0}
    ring = [hwm._light_snapshot(readings, f"t{i}", None) for i in range(hwm._LIGHT_KEEP)]
    state = {"pressure_light": ring, "pressure_light_taken": len(ring), "started_at": "2026-10-06T00:00:00",
             "session_id": "the-previous-session"}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(hwm, "current", lambda: state)
        mp.setattr(hwm, "previous", lambda: state)
        # the previous session's marks are copied only under the ledger's id for that session
        mp.setattr("src.monitoring.session_history.previous_session_id", lambda: "the-previous-session")
        out = hwm.diagnostics_member(max_bytes=slots.budget_of("pressure-light.json"))
    assert len(out["this_session"]["snapshots"]) == len(out["previous_session"]["snapshots"]) == hwm._LIGHT_KEEP
    assert out["this_session"]["dropped_oldest_to_fit"] == out["previous_session"]["dropped_oldest_to_fit"] == 0
    assert len(json.dumps(out, default=str).encode()) <= slots.budget_of("pressure-light.json")


# ---------------------------------------------------------------------------------------------------
#  4. No two members carry the same subtree
# ---------------------------------------------------------------------------------------------------
def identical_subtrees(members: dict, min_bytes: int = 300) -> list[tuple[int, list[tuple[str, str]]]]:
    """Every object or list of ``min_bytes`` or more that appears, byte for byte, in more than one
    member, largest first, with where. Two copies inside ONE member are not this guard's business."""
    seen: dict[str, list[tuple[str, str]]] = defaultdict(list)

    def walk(node, member, path):
        if isinstance(node, (dict, list)) and node:
            text = json.dumps(node, sort_keys=True, default=str)
            if len(text) >= min_bytes:
                seen[text].append((member, "/".join(path)))
            for k, v in (node.items() if isinstance(node, dict) else enumerate(node)):
                walk(v, member, [*path, str(k)])

    for name, value in members.items():
        walk(value, name, [])
    out = [(len(t), locs) for t, locs in seen.items() if len({m for m, _ in locs}) > 1]
    return sorted(out, key=lambda row: -row[0])


def test_the_guard_finds_a_duplicate_and_ignores_two_copies_inside_one_member():
    body = {"rows": [{"n": i, "text": "y" * 20} for i in range(20)]}
    found = identical_subtrees({"a.json": {"x": body}, "b.json": {"deeper": {"y": body}}})
    assert found and {m for m, _ in found[0][1]} == {"a.json", "b.json"}
    assert identical_subtrees({"a.json": {"x": body, "y": body}}) == []
    assert identical_subtrees({"a.json": {"x": {"small": 1}}, "b.json": {"x": {"small": 1}}}) == []


def _record_one_damage_incident(tmp_path):
    """One incident in the damage registry (the autouse fixture of conftest resets it after the test)."""
    import sqlite3

    from src.database import damage

    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    damage.registry.note(
        damage.FILE_CORPUS, sqlite3.DatabaseError("database disk image is malformed"), statement="SELECT a FROM articles"
    )


@pytest.mark.parametrize("incident", [False, True], ids=["young install", "one recorded damage incident"])
def test_no_two_record_members_of_the_archive_carry_the_same_300_bytes(db, tmp_path, incident):
    """Run for real (the archive's own records, not the scans). The old archive
    failed this in four places: the storage footprint and the persistence check (session-forensics and
    the storage reads), the rolling log's counts (the debug bundle and frontend-errors), and the eight
    sections the debug bundle embedded of members that stand alone. The second case is the one a young
    install hides: the storage guard's state carries the damage record, which ``database-damage.json`` is
    in its own right (found at 454 to 598 bytes, four times, in the debug bundle and the storage member)."""
    if incident:
        _record_one_damage_incident(tmp_path)
    ran: dict[str, object] = {}
    failed: dict[str, str] = {}
    for name, fn in d._all_diagnostics_members(db):
        if plan.is_scan(name) or name == "selftests.json":  # a function of the build, embedded nowhere
            continue
        try:
            value = fn()
            ran[name] = value if isinstance(value, (dict, list)) else b._section_value(value)
        except Exception as exc:  # noqa: BLE001 - say which one, below
            failed[name] = type(exc).__name__
    assert len(ran) >= 30, (sorted(ran), failed)
    found = identical_subtrees(ran)
    assert not found, [(n, locs[:3]) for n, locs in found[:5]]


def test_the_storage_guard_s_copy_of_the_damage_record_keeps_the_headline_and_names_the_member(db, tmp_path):
    _record_one_damage_incident(tmp_path)
    from src.scheduler.storage_guard import storage_guard

    full = json.loads(json.dumps(storage_guard.state(detail=True), default=str))
    record = full["database_damage"]
    assert record["incidents"], "the fixture records an incident"
    named = b._damage_named_not_copied(full)
    assert named is not full and full["database_damage"] is record, "a copy: the guard's own state is not touched"
    pointer = named["database_damage"]
    assert pointer["see"] == "database-damage.json" and pointer["slim"] is True
    for key in ("enabled", "latched", "recorded_only", "incident_count"):  # named here, not read from the code under test
        assert pointer[key] == record[key], key
    assert "incidents" not in pointer and "notes" not in pointer and "last_incident" not in pointer
    assert {k: v for k, v in named.items() if k != "database_damage"} == {k: v for k, v in full.items() if k != "database_damage"}


def test_the_pointer_is_written_only_where_the_member_is_and_only_for_the_shape_it_knows(db, tmp_path, monkeypatch):
    guard = {"a": 1, "database_damage": {"incidents": [1], "latched": ["corpus"]}}
    monkeypatch.setattr(slots, "in_build", lambda name: False)
    assert b._damage_named_not_copied(guard) is guard, "without the member in the build the record stays where it is"
    monkeypatch.undo()
    for other in (None, [], {"a": 1}, {"database_damage": "text"}):
        assert b._damage_named_not_copied(other) is other


def test_the_archive_s_storage_member_and_slim_scheduler_name_the_damage_member_and_the_routes_stay_whole(db, tmp_path):
    _record_one_damage_incident(tmp_path)
    storage = dict(d._all_diagnostics_members(db))["storage.json"]()
    guard = storage["sections"]["storage-composition"]["data"]["storage_guard"]
    assert guard["database_damage"]["see"] == "database-damage.json", sorted(guard)
    assert "incidents" not in guard["database_damage"]
    slim = _bundle(db, True)["scheduler"]["status"]["storage_guard"]["database_damage"]
    assert slim["see"] == "database-damage.json" and "incidents" not in slim and "notes" not in slim
    whole = _bundle(db, False)["scheduler"]["status"]["storage_guard"]["database_damage"]
    assert "see" not in whole and whole["last_incident"] and whole["notes"], "the route on its own is whole"


def test_the_damage_budget_holds_a_full_record_twice_over(tmp_path):
    """The budget of ``database-damage.json`` was a first estimate; it is now held to a measurement: the record at its
    full retention (``INCIDENTS_KEEP`` incidents of distinct shapes, no table lists) was 16,187 bytes when it was measured."""
    import sqlite3

    from src.database import damage

    damage.registry._reset_for_tests(path_fn=lambda: tmp_path / "database-damage.json")
    for n in range(damage.INCIDENTS_KEEP + 5):
        damage.registry.note(
            damage.FILE_CORPUS, sqlite3.DatabaseError("database disk image is malformed"),
            statement=f"SELECT a FROM t{n} WHERE b IN (SELECT c FROM u{n})",
        )
    budget = slots.budget_of("database-damage.json")
    whole = damage.diagnostics_member(10**9)
    size = len(json.dumps(whole, separators=(",", ":"), default=str))
    assert len(whole["incidents"]) == damage.INCIDENTS_KEEP and whole["dropped_oldest_to_fit"] == 0
    assert size * 2 <= budget, (size, budget)
    # at its budget the full record still fits, so nothing is dropped from it
    fitted = damage.diagnostics_member(budget)
    assert fitted["dropped_oldest_to_fit"] == 0 and len(fitted["incidents"]) == damage.INCIDENTS_KEEP


# ---------------------------------------------------------------------------------------------------
#  5. The slim debug bundle
# ---------------------------------------------------------------------------------------------------
def _bundle(db, slim):
    resp = d.debug_bundle(db=db, slim=slim)
    return json.loads(bytes(resp.body))["data"]


def test_the_slim_bundle_names_the_members_it_does_not_repeat_and_does_not_build_them(db, monkeypatch):
    from src.monitoring import errorlog
    from src.monitoring import preflight as _preflight

    calls = {"summary": 0, "network": 0}
    real_summary, real_results = errorlog.summary, _preflight.recent_results

    def _count_summary():
        calls["summary"] += 1
        return real_summary()

    def _count_results(*a, **k):
        calls["network"] += 1
        return real_results(*a, **k)

    monkeypatch.setattr(errorlog, "summary", _count_summary)
    monkeypatch.setattr(_preflight, "recent_results", _count_results)
    slim = _bundle(db, True)
    assert calls == {"summary": 0, "network": 0}, "a section named as a pointer must not be built"
    whole = _bundle(db, False)
    assert calls["summary"] >= 1 and calls["network"] >= 1

    members = set(_member_names())
    assert set(d._DEBUG_BUNDLE_STANDS_ALONE) == set(slim["slim"]["pointers"])
    for key, member in d._DEBUG_BUNDLE_STANDS_ALONE.items():
        assert member in members, f"{key} points at {member}, which is not written"
        assert slim[key]["see"] == member and slim[key]["slim"] is True, key
        assert not (isinstance(whole[key], dict) and whole[key].get("slim") is True), key
        # every section it names is one the whole bundle builds, so the table cannot name a ghost
        assert key in whole, key
    assert slim["storage_composition"]["section"] == "sections.storage-composition"
    assert slim["error_log"] == {"see": "frontend-errors.json", "slim": True, "section": "summary"}
    # what is NOT a member of its own stays whole
    for kept in ("runtime", "corpus", "scheduler", "errors", "keyword_write_cost"):
        assert not (isinstance(slim[kept], dict) and slim[kept].get("slim") is True), kept
    assert "slim" not in whole


def test_the_slim_bundle_keeps_collect_perf_to_its_newest_ticks(db, monkeypatch):
    import src.monitoring.collect_perf as cp

    asked = []
    monkeypatch.setattr(cp, "recent_samples", lambda limit=200: asked.append(limit) or [])
    _bundle(db, True)
    _bundle(db, False)
    assert d._DEBUG_BUNDLE_SLIM_PERF_TICKS == 20
    assert asked == [20, 200], "the slim bundle asks for 20 ticks, the whole bundle for the log's own default"


def test_only_an_explicit_true_slims_the_bundle(db):
    """A ``Query`` default called directly is a truthy sentinel OBJECT: it must give the whole bundle."""
    from fastapi import Query

    whole = json.loads(bytes(d.debug_bundle(db=db, slim=Query(False)).body))["data"]
    assert "slim" not in whole and "see" not in json.dumps(whole["network"])[:40]
    # and the archive's member passes True explicitly
    src = __import__("inspect").getsource(d._all_diagnostics_members)
    assert "debug_bundle(db=db, slim=True)" in src


# ---------------------------------------------------------------------------------------------------
#  6. Session forensics in the zip
# ---------------------------------------------------------------------------------------------------
def test_session_forensics_names_the_blocks_that_stand_alone_and_the_route_is_whole(db, monkeypatch):
    import src.monitoring.forensics as fx

    ring = [{"at": "t1", "why": "near"}, {"at": "t2", "why": "near"}, {"at": "t3", "why": "near"}]
    real = fx.session_forensics

    def _with_ring():
        out = dict(real())
        out["previous_session_peaks"] = {"pressure_light": ring, "pressure_light_taken": 3, "other": 1}
        return out

    monkeypatch.setattr(fx, "session_forensics", _with_ring)
    whole = d.session_forensics_report(download=False)
    member = d._session_forensics_member()
    assert isinstance(whole["storage_footprint"], dict) and "see" not in whole["storage_footprint"]
    assert whole["previous_session_peaks"]["pressure_light"] == ring
    assert member["storage_footprint"]["see"] == "storage.json"
    assert member["data_dir_persistence"]["see"] == "storage.json"
    peaks = member["previous_session_peaks"]
    assert peaks["pressure_light"] == {
        "see": "pressure-light.json", "section": "previous_session.snapshots", "snapshots_here_before": 3,
    }
    assert peaks["other"] == 1, "the rest of the block stays"
    assert member["slim"]["on"] is True and set(member["slim"]["pointers"]) >= {
        "storage_footprint", "data_dir_persistence", "previous_session_peaks.pressure_light",
    }
    # the members it names are written, and storage.json carries the sections it names
    names = _member_names()
    assert "storage.json" in names and "pressure-light.json" in names
    storage = d._storage_member(db)
    for key, (target, section) in d._FORENSICS_POINTERS.items():
        assert target in names, key
        node = storage
        for part in section.split("."):
            assert isinstance(node, dict) and part in node, f"{key}: storage.json has no {section}"
            node = node[part]


# ---------------------------------------------------------------------------------------------------
#  7. ai.json carries the four last-run summaries
# ---------------------------------------------------------------------------------------------------
def test_ai_json_jobs_are_what_the_four_dropped_members_returned(monkeypatch):
    """The four ``*/last`` routes call the same four reporters ``ai.json``'s ``jobs`` read, so a
    member of each would have been the same bytes written twice. With the reporters made distinct,
    each route returns exactly what its entry under ``jobs`` holds."""
    import src.ai_layer.perception_extract_job as pe
    import src.ai_layer.perception_job as pj
    import src.ai_layer.source_tags_job as st
    import src.ai_layer.triage_job as tj
    from src.monitoring.ai_diagnostics import ai_diagnostics_report

    wired = [
        (tj, "last_keyword_triage_report", "keyword_triage", d.keyword_triage_last),
        (st, "last_source_tags_report", "source_tags", d.source_tags_last),
        (pj, "last_perception_eval_live_report", "perception_eval_live", d.perception_eval_live_last),
        (pe, "last_perception_extract_report", "perception_extract", d.perception_extract_last),
    ]
    for module, fn_name, _key, _route in wired:
        monkeypatch.setattr(module, fn_name, lambda n=fn_name: {"marker": n})
    jobs = ai_diagnostics_report()["jobs"]
    for _module, fn_name, key, route in wired:
        assert jobs[key] == {"marker": fn_name}, key
        assert json.loads(bytes(route().body)) == {"marker": fn_name}, key
    # and the map says so: those four routes are carried by ai.json
    for route_path in ("/keyword-triage/last", "/source-tags/last", "/perception-eval-live/last",
                       "/perception-extract/last"):
        assert d._DIAG_COVERAGE_MAP[route_path] == "ai.json"


# ---------------------------------------------------------------------------------------------------
#  8. The tail of the vitals history
# ---------------------------------------------------------------------------------------------------
def test_vitals_names_the_member_that_carries_the_minutes_before_a_kill():
    from src.monitoring import vitals_history as vh

    named = vh._TAIL_IN_PRESSURE_LIGHT["member"]
    assert named in {s.name for s in slots.SLOTS} and named in _member_names()
    # What a FRESH process reads, not this one: the suite resets the module's state between tests, which
    # would hide a default that went back to ``None`` (and a real start never resets it).
    import pathlib
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parent.parent
    fresh = subprocess.run(
        [sys.executable, "-c", "import src.monitoring.vitals_history as v; print((v.TAIL_IN or {}).get('member'))"],
        cwd=root, capture_output=True, text=True, timeout=120, check=True,
    )
    assert fresh.stdout.strip() == named


# ---------------------------------------------------------------------------------------------------
#  Merged members: a section that fails does not hide the others, and a merged member says so
# ---------------------------------------------------------------------------------------------------
def test_a_merged_member_with_a_failing_section_is_incomplete_and_says_which():
    def boom():
        raise RuntimeError("the second read fell over")

    out = b._merged_member(
        {"first": lambda: {"a": 1}, "second": boom, "third": lambda: [1, 2]},
        replaces=["first.json", "second.json", "third.json"], why="test",
    )
    assert out["sections"]["first"] == {"a": 1} and out["sections"]["third"] == [1, 2]
    assert "the second read fell over" in out["sections"]["second"]["error"]
    assert out["complete"] is False and out["sections_not_collected"] == ["second"]
    assert out["merged"]["replaces"] == ["first.json", "second.json", "third.json"]
    whole = b._merged_member({"a": lambda: {"x": 1}}, replaces=["a.json"], why="test")
    assert whole["complete"] is True and "sections_not_collected" not in whole


def test_a_section_the_deadline_ended_is_not_swallowed_and_the_rest_say_they_were_not_reached():
    from src.database.maintenance import StatementTimeout

    def late():
        raise StatementTimeout("deadline")

    out = b._merged_member(
        {"one": lambda: {"ok": True}, "two": late, "three": lambda: {"never": "run"}},
        replaces=[], why="test",
    )
    assert out["sections"]["one"] == {"ok": True}
    assert "deadline ended this section" in out["sections"]["two"]["skipped"]
    assert "deadline had passed" in out["sections"]["three"]["skipped"]
    assert out["complete"] is False and out["sections_not_collected"] == ["two", "three"]


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ({"passed": True, "total": 5, "failed_count": 0}, "pass"),
        ({"summary": {"total": 4, "passed": 4, "failed": 0}}, "pass"),
        ({"passed": False, "total": 5, "failed_count": 2}, "fail"),
        ({"summary": {"total": 4, "passed": 3, "failed": 1}}, "fail"),
        ({"passed": True, "total": 3, "failed_count": 1}, "fail"),  # the flag and the count disagree
        ({"passed": True, "total": 0}, "unknown"),  # a pass over zero checks proves nothing
        ({"something": "else"}, "unknown"),
        ("not an object", "unknown"),
        ({"passed": 1, "total": 3}, "unknown"),  # a number is not a flag
        # the third shape, checks listed one by one: counted from them, never read as a bare pass
        ({"passed": True, "checks": {}}, "unknown"),  # a pass over no check proves nothing
        ({"passed": True, "checks": {"a": False}}, "fail"),  # the flag says pass, a check failed
        ({"passed": True, "checks": {"a": True, "b": True}}, "pass"),
        ({"passed": True, "checks": [{"check": "a", "ok": True}, {"check": "b", "ok": False}]}, "fail"),
        ({"passed": True, "checks": [{"check": "a", "passed": True}]}, "pass"),
        # a pass with no count of checks behind it is not a bare pass (a shape this reader does not know)
        ({"passed": True}, "unknown"),
        ({"passed": True, "checks": {"a": {"ok": True}}}, "unknown"),
        ({"passed": True, "checks": {"a": 1}}, "unknown"),
        ({"passed": True, "checks": "all of them"}, "unknown"),
        ({"passed": True, "failed_count": 2}, "fail"),  # a failed count still outranks the missing total
        ({"passed": True, "passed_count": 3, "failed_count": 0}, "pass"),  # a count of passes is a count
    ],
)
def test_a_selftest_is_a_pass_only_when_it_says_so_and_ran_a_check(answer, verdict):
    assert b._selftest_verdict(answer)["verdict"] == verdict


def test_a_pass_read_from_listed_checks_keeps_the_count_of_them():
    """67 checks of seven self-tests were counted by the tests and lost from the record: a pass says how many it was over."""
    got = b._selftest_verdict({"passed": True, "checks": {"a": True, "b": True, "c": True}})
    assert got == {"total": 3, "passed": 3, "failed": 0, "verdict": "pass"}
    got = b._selftest_verdict({"passed": True, "checks": [{"check": "a", "ok": True}, {"check": "b", "ok": True}]})
    assert got == {"total": 2, "passed": 2, "failed": 0, "verdict": "pass"}


def test_selftests_keep_the_full_output_only_for_one_that_did_not_pass(monkeypatch):
    def broken():
        raise RuntimeError("cannot run")

    calls = [
        ("good", lambda: {"passed": True, "total": 2, "failed_count": 0, "detail": "long"}),
        ("bad", lambda: {"passed": False, "total": 2, "failed_count": 1, "detail": "why"}),
        ("odd", lambda: {"shape": "unknown"}),
        ("dead", broken),
    ]
    monkeypatch.setattr(b, "_selftest_calls", lambda: calls)
    out = b._selftests_member()
    assert out["summary"] == {"tests": 4, "pass": 1, "fail": 1, "unknown": 1, "error": 1, "all_pass": False}
    assert "output" not in out["tests"]["good"] and out["tests"]["bad"]["output"]["detail"] == "why"
    assert out["tests"]["odd"]["verdict"] == "unknown" and out["tests"]["dead"]["verdict"] == "error"
    assert out["merged"]["replaces"] == ["good.json", "bad.json", "odd.json", "dead.json"]


# ---------------------------------------------------------------------------------------------------
#  5. The budgets and the 4 MB of R119 (the coordinator's condition at the go on D)
# ---------------------------------------------------------------------------------------------------
def test_the_budgets_and_the_fixed_members_fit_one_part_with_the_headroom_the_table_states():
    """Worst case, every byte of the slots and of the new members incompressible: the budgets, the
    plan's estimate of the other new members, the largest zip actually measured and the volumes'
    own per-part overhead still leave the room the table states under one part. A budget raised
    carelessly eats the headroom and this fails; the answer is to measure again."""
    cap = dv.volume_max_bytes()
    assert cap == 4_000_000
    worst = (
        sum(s.budget_bytes for s in slots.SLOTS)
        + slots.OTHER_NEW_MEMBERS_BYTES
        + slots.LARGEST_ZIP_MEASURED_BYTES
        + dv._ZIP_OVERHEAD_MAX
    )
    free = cap - worst
    assert free >= slots.HEADROOM_AT_LEAST_BYTES, f"{free:,} bytes are left of a part, the table promises {slots.HEADROOM_AT_LEAST_BYTES:,}"
    # the stated figures are the ones the comment names, not drifted copies
    assert slots.LARGEST_ZIP_MEASURED_BYTES == 632_000 and slots.OTHER_NEW_MEMBERS_BYTES == 1_194_000
    # the arithmetic beside the number: the plan's 919 KB with its +125 KB session-forensics estimate swapped for the crash
    # trace export's worst case, COMPUTED from the export's own constants so that a cut that grows fails here: the newest earlier
    # end keeps ``NEWEST_EARLIER_TRACE_LINES`` lines (the cut of the one export that has the constant; the others have no such
    # distinction), the other earlier ends keep ``EARLIER_TRACE_LINES`` each, the previous session keeps ``_TRACE_REPORT_LINES``,
    # every line is at most ``_TRACE_LINE_BYTES`` + 4 bytes with the JSON around it, and about 10,000 bytes frame the member
    from src.monitoring import exit_evidence as ee

    line = ee._TRACE_LINE_BYTES + 4
    newest_earlier = getattr(ee, "NEWEST_EARLIER_TRACE_LINES", ee.EARLIER_TRACE_LINES)
    crash_trace = (newest_earlier + (ee.EARLIER_ENDS_LIMIT - 1) * ee.EARLIER_TRACE_LINES + ee._TRACE_REPORT_LINES) * line + 10_000
    assert crash_trace <= 400_000, f"the crash trace export's worst case is {crash_trace:,} bytes; the slot counts 400,000: measure again"
    assert slots.OTHER_NEW_MEMBERS_BYTES == 919_000 - 125_000 + 400_000
    assert free == 1_512_744, "the comment on the table states the free room; move them together"


def test_a_budget_raised_past_the_headroom_fails_the_pin(monkeypatch):
    fat = tuple(slots.Slot(s.name, s.target, s.owner, s.budget_bytes * 4, s.area) for s in slots.SLOTS)
    monkeypatch.setattr(slots, "SLOTS", fat)
    worst = (
        sum(s.budget_bytes for s in slots.SLOTS) + slots.OTHER_NEW_MEMBERS_BYTES
        + slots.LARGEST_ZIP_MEASURED_BYTES + dv._ZIP_OVERHEAD_MAX
    )
    assert dv.volume_max_bytes() - worst < slots.HEADROOM_AT_LEAST_BYTES, "four times the budgets must trip the pin"


def test_a_member_far_over_its_budget_is_named_over_budget_cut_on_record_boundaries_and_none_is_dropped(
    tmp_path, monkeypatch
):
    """The producer's own answer is never cut by the wrapper. The manifest says it is over its budget,
    the splitter keeps every part under the cap by cutting the member into numbered pieces, and the
    pieces put back are the producer's whole answer: nothing is dropped silently."""
    giant = _slot("giant.json", "tests.test_diagnostic_slots:giant_member", 100_000, area="storage")
    monkeypatch.setattr(slots, "SLOTS", (giant,))
    src = tmp_path / "oo-all-diagnostics-20261006-120000.zip"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        results = b._write_all_diagnostics_zip(slots.members(), z)
    (entry,) = [r for r in results if r["file"] == "giant.json"]
    assert entry["over_budget"] is True and entry["budget_bytes"] == 100_000 and entry["bytes"] > 8_000_000
    with zipfile.ZipFile(src) as z:
        in_manifest = {m["file"]: m for m in json.loads(z.read("manifest.json"))["members"]}
    assert in_manifest["giant.json"]["over_budget"] is True, "the archive's own manifest says so"
    assert src.stat().st_size > dv.volume_max_bytes(), "the archive is above the cap, so it is split"
    vol_dir = tmp_path / "v"
    manifest = dv.write_volume_set(src, vol_dir)
    assert manifest["cut_members"] == ["giant.json"], "the cut is named, never silent"
    assert all(v["bytes"] <= 4_000_000 for v in manifest["volumes"]) and len(manifest["volumes"]) >= 2
    (dest,) = [Path(p) for p in dv.reassemble_cut_members(vol_dir, tmp_path / "back")]
    assert json.loads(dest.read_text(encoding="utf-8")) == giant_member(100_000), "nothing was dropped"
