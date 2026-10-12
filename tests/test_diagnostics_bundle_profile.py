"""The light/full diagnostics toggle: what it declines, and what it may never pretend.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY A TOGGLE AND NOT A RULE. Two maintainer rulings stand and neither was reconciled.
The 2026-09-02 crash brief, §3 ruling 4 (NOT `R4` of `docs/ledger/RULINGS_INDEX.md`, which
is a different ruling about export messages -- the brief numbers its own list), says the
diagnostics bundle "still runs EVERY member -- the bundle is the maintainer's only evidence
channel"; `R27` (2026-09-22) says members needing more than half the machine's RAM decline
below the floor. The toggle is the reconciliation the maintainer chose on 2026-09-22 and it
is `R28`: EVERY MEMBER stays the default and the only automatic behaviour, and a decline
happens solely because the operator asked for one. Nothing declines itself, so the 09-02
ruling is never overridden by a machine reading.

THE THREE THINGS THAT MUST NOT REGRESS, and each has its own test below:

1. **Full is untouched.** A full run declines nothing, and its manifest says so.
2. **A decline is never silent and never fabricates a cause.** The member is listed in the
   manifest with its reason, the archive carries a marker file naming why, and it must
   NEVER be written as a deadline it did not hit -- the branch that writes the
   `skipped-deadline` marker used to be a catch-all `else`, which would have shipped a file
   claiming a member the operator deliberately skipped "exceeded its wall-clock deadline".
3. **A light bundle can never be read as a full one.** Release gate row C closes on "every
   member non-zero"; a light run would satisfy a naive member count while carrying less
   evidence, so the manifest publishes `complete_profile` for a gate check to read.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from src.api.diagnostics.bundle import (
    _LIGHT_DECLINED,
    _write_all_diagnostics_zip,
    resolve_bundle_profile,
)


def _members():
    """A stand-in member list: two declined names and two ordinary ones.

    The declined names are taken from the real set rather than invented, so this exercises
    the shipped classification instead of a parallel one."""
    declined = sorted(_LIGHT_DECLINED)[:2]
    return [
        (declined[0], lambda: {"ran": True}),
        ("ordinary-one.json", lambda: {"ran": True}),
        (declined[1], lambda: {"ran": True}),
        ("ordinary-two.json", lambda: {"ran": True}),
    ]


def _build(profile):
    """Build a real archive and read back the manifest THE WRITER WROTE.

    The writer emits ``manifest.json`` itself, so a test that composed its own would be
    asserting against a reconstruction rather than the artifact an operator receives --
    and would pass even if the writer stopped passing the profile through."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        results = _write_all_diagnostics_zip(_members(), z, profile=profile)
    buf.seek(0)
    zf = zipfile.ZipFile(buf)
    man = json.loads(zf.read("manifest.json"))
    return results, man, zf


# --------------------------------------------------------------------------- #
# The resolver                                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("given", ["light", "LIGHT", " light "])
def test_light_is_recognised_however_it_is_spelled(given):
    assert resolve_bundle_profile(given) == "light"


def test_a_Query_sentinel_resolves_to_FULL_rather_than_raising():
    """THE TRAP THIS MODULE ALREADY CARRIES THREE TIMES, one type over. Called directly
    instead of through FastAPI -- which is how the sync `/all` route is driven by its own
    tests -- a ``Query("full")`` default arrives as the Query SENTINEL OBJECT, not as text.
    The first cut of the resolver did `(requested or "").strip()` and died with
    `AttributeError: 'Query' object has no attribute 'strip'`, taking the exclusive-window
    context manager down with it. Reproduced here so the next parameter added to this route
    meets the lesson rather than the bug."""
    from fastapi import Query

    assert resolve_bundle_profile(Query("full")) == "full"
    assert resolve_bundle_profile(Query("light")) == "full"


@pytest.mark.parametrize("given", [None, "", "full", "ligth", "minimal", "0", "true", 1, object()])
def test_anything_unrecognised_resolves_to_FULL_not_light(given):
    """The direction matters. A typo, a stale client or a future profile name must never
    silently produce a SMALLER bundle than the operator believes they asked for: an
    unexpectedly complete bundle costs time, an unexpectedly incomplete one costs the
    evidence R4 calls the maintainer's only channel."""
    assert resolve_bundle_profile(given) == "full"


# --------------------------------------------------------------------------- #
# Full is untouched (R4)                                                      #
# --------------------------------------------------------------------------- #


def test_a_full_run_declines_nothing_and_says_so():
    results, man, zf = _build("full")

    assert [r["outcome"] for r in results] == ["ok"] * 4
    assert man["profile"]["name"] == "full"
    assert man["profile"]["complete_profile"] is True
    assert man["profile"]["declined"] == []
    assert not [n for n in zf.namelist() if n.endswith(".declined.txt")]


def test_every_member_is_written_on_a_full_run():
    _results, _man, zf = _build("full")
    for name, _fn in _members():
        assert name in zf.namelist()


# --------------------------------------------------------------------------- #
# A decline is never silent, and never borrows another cause                  #
# --------------------------------------------------------------------------- #


def test_light_declines_exactly_the_named_set_and_runs_the_rest():
    results, _man, _zf = _build("light")
    by_name = {r["file"]: r["outcome"] for r in results}

    declined = sorted(_LIGHT_DECLINED)[:2]
    assert by_name[declined[0]] == "declined-light"
    assert by_name[declined[1]] == "declined-light"
    assert by_name["ordinary-one.json"] == "ok"
    assert by_name["ordinary-two.json"] == "ok"


def test_a_declined_member_carries_its_reason_in_the_manifest():
    """In the manifest, not only in a sidecar: a reader parsing manifest.json must be able
    to say WHY a member is absent without opening a .txt, or the absence reads as a gap."""
    results, man, _zf = _build("light")

    for r in results:
        if r["outcome"] == "declined-light":
            assert r["declined_reason"], f"{r['file']} declined with no reason"
    reasons = {d["file"]: d["reason"] for d in man["profile"]["declined"]}
    assert len(reasons) == 2
    assert all(reasons.values())


def test_a_declined_member_ships_a_marker_that_names_the_choice():
    _results, _man, zf = _build("light")
    declined = sorted(_LIGHT_DECLINED)[0]

    marker = zf.read(declined + ".declined.txt").decode()
    assert "LIGHT profile" in marker
    assert _LIGHT_DECLINED[declined][:40] in marker
    assert "FULL" in marker, "the marker must say how to get the member"


def test_a_declined_member_NEVER_claims_a_deadline_it_did_not_hit():
    """THE DEFECT THIS PINS, found while wiring the toggle. The branch that writes the
    `skipped-deadline` marker was a catch-all `else`, so any outcome that was not `ok` fell
    into it -- and a member the operator deliberately skipped would have shipped a file
    saying it "exceeded its wall-clock deadline and was abandoned". A fabricated cause is
    worse than no file at all, because it points the reader at a limit that never fired."""
    _results, _man, zf = _build("light")
    names = zf.namelist()

    assert not [n for n in names if "skipped-deadline" in n], (
        "a declined member borrowed the deadline path's marker"
    )


def test_the_declined_member_is_not_written_as_an_empty_payload():
    """An empty `<name>.json` would read as "we looked and found nothing", which is a
    different claim from "we did not look"."""
    _results, _man, zf = _build("light")
    declined = sorted(_LIGHT_DECLINED)[0]
    assert declined not in zf.namelist()
    assert declined + ".declined.txt" in zf.namelist()


# --------------------------------------------------------------------------- #
# A light bundle can never be read as a full one (gate row C)                 #
# --------------------------------------------------------------------------- #


def test_a_light_manifest_refuses_the_complete_flag():
    """Release gate row C closes on a bundle with every member non-zero. A light run keeps
    the member LIST intact by design, so a gate check counting members would pass on less
    evidence than the row asks for. `complete_profile` is the boolean it should read."""
    _results, man, _zf = _build("light")

    assert man["profile"]["name"] == "light"
    assert man["profile"]["complete_profile"] is False
    assert "declined" in man["profile"]["note"].lower()


def test_the_light_note_says_it_was_a_choice_rather_than_a_failure():
    _results, man, _zf = _build("light")
    note = man["profile"]["note"]
    assert "chose" in note or "choice" in note
    assert "FULL" in note


# --------------------------------------------------------------------------- #
# The declined set is real                                                    #
# --------------------------------------------------------------------------- #


def test_every_declined_name_is_an_actual_bundle_member():
    """A declined-set entry naming a member that does not exist is silently dead: the
    operator asks for light, the cost is still paid, and nothing says so. Read against the
    real member list's source rather than a copy of it.

    THE SLICE COMES FROM THE PARSER, not from a guessed delimiter. The first cut did
    ``split("def _all_diagnostics_members", 1)[1].split("\\ndef ", 1)[0]`` -- the exact
    shape `tests/js_source_helper` exists to retire, where a delimiter that does not occur
    silently makes the "body" the whole rest of the module and the assertion is satisfied
    by some other function."""
    import pathlib

    from tests.js_source_helper import python_function_source

    src = pathlib.Path("src/api/diagnostics/bundle.py").read_text(encoding="utf-8")
    block = python_function_source(src, "_all_diagnostics_members")

    missing = [name for name in _LIGHT_DECLINED if f'("{name}"' not in block]
    assert not missing, f"declined names that are not members: {missing}"


def test_every_declined_member_states_a_reason():
    for name, reason in _LIGHT_DECLINED.items():
        assert reason and len(reason) > 40, f"{name} has no stated reason"


# --------------------------------------------------------------------------- #
# R27: the MACHINE declines a member, on the full profile too (finding F12)    #
# --------------------------------------------------------------------------- #


# A SYNTHETIC heavy member. The real one (the keyword digest: 3,322.8 MiB on the operator's
# 2026-09-11 run, finding F12) stopped being heavy on 2026-09-30, when the export was made
# memory-bounded and re-measured (see the comment on ``_MEMBER_RSS_NEED_MB``). The R27 MECHANISM
# is what these tests pin, so it is exercised through a member the map is told about, both there
# and in the light profile's set (the overlap R27's own ledger entry warns about), for the
# length of one test.
_HEAVY = "synthetic-heavy-member.json"
_HEAVY_NEED_MB = 3322.8


def _ram(monkeypatch, mb_total):
    """Pin the machine's RAM for one test, and clear the big-scan override."""
    from src.api.diagnostics import bundle

    monkeypatch.delenv("OO_ALLOW_BIG_SCANS", raising=False)
    monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: mb_total)
    monkeypatch.setitem(bundle._MEMBER_RSS_NEED_MB, _HEAVY, _HEAVY_NEED_MB)
    monkeypatch.setitem(bundle._LIGHT_DECLINED, _HEAVY, "synthetic: declined in the light profile too")


def test_a_measured_member_declines_when_it_needs_more_than_half_the_RAM(monkeypatch):
    """F12: this member raised peak RSS by 3,322.8 MiB on a 4,029 MiB VM -- the only
    member of that 72-member run above 0.0 MiB. One member, by itself, putting a machine
    into swap. S1.3 declines whole-corpus SCANS below the floor and a bundle member is
    not a scan, which is the gap R27 closes."""
    from src.api.diagnostics.bundle import ram_declined_reason

    _ram(monkeypatch, 4029.0)
    reason = ram_declined_reason(_HEAVY)
    assert reason and "3,322.8" in reason and "4,029" in reason
    assert "F12" in reason


def test_the_keyword_digest_was_REMEASURED_when_its_code_changed(monkeypatch):
    """A measured constant is a claim about one version of the code. The digest's 3,322.8 MiB
    was the unbounded builder; the bounded one was measured at ~186 MiB on a 6 M-keyword
    synthetic corpus, so the machine F12 was measured on now RUNS it. The 500 is a ceiling on
    the reading, not the reading: a new number that high means the export grew again."""
    from src.api.diagnostics.bundle import _MEMBER_RSS_NEED_MB, ram_declined_reason

    _ram(monkeypatch, 4029.0)
    assert 0 < _MEMBER_RSS_NEED_MB["keyword-log-digest.json"] < 500
    assert ram_declined_reason("keyword-log-digest.json") is None


def test_the_same_member_RUNS_on_a_machine_that_can_hold_it(monkeypatch):
    """Self-limiting by construction: half of 8,192 is 4,096, and the member needs
    3,322.8. No second threshold to keep in step with the first."""
    from src.api.diagnostics.bundle import ram_declined_reason

    _ram(monkeypatch, 8192.0)
    assert ram_declined_reason(_HEAVY) is None


def test_an_UNMEASURED_MACHINE_never_declines(monkeypatch):
    """The inference-hardware-gate lesson, in its mirror form: refusing capability for
    want of a measurement is the opposite error to over-claiming it."""
    from src.api.diagnostics.bundle import ram_declined_reason

    _ram(monkeypatch, None)
    assert ram_declined_reason(_HEAVY) is None


def test_an_UNMEASURED_MEMBER_never_declines(monkeypatch):
    """Absence of a reading is not a reading. The map grows when a run MEASURES
    something -- every bundle records `rss_peak_rise_kb` per member -- never when
    somebody estimates."""
    from src.api.diagnostics.bundle import _MEMBER_RSS_NEED_MB, ram_declined_reason

    _ram(monkeypatch, 512.0)  # absurdly small; still runs an unmeasured member
    assert ram_declined_reason("card-audit.json") is None
    assert "card-audit.json" not in _MEMBER_RSS_NEED_MB


def test_the_EXISTING_override_lifts_it_rather_than_a_second_switch(monkeypatch):
    """S1.3 already has `OO_ALLOW_BIG_SCANS`. A second key for the same idea is how two
    surfaces come to disagree about one setting."""
    from src.api.diagnostics.bundle import ram_declined_reason

    _ram(monkeypatch, 4029.0)
    monkeypatch.setenv("OO_ALLOW_BIG_SCANS", "1")
    assert ram_declined_reason(_HEAVY) is None


def test_a_FULL_bundle_that_declined_for_RAM_is_NOT_complete(monkeypatch):
    """THE ROW-C HOLE THIS RULING RE-OPENS, closed in the same change.

    `complete_profile` was `profile == "full"` -- true for one PR, because until R27 only
    the operator could decline. Now the MACHINE can decline on a FULL run, so that
    shortcut would report a bundle missing its heaviest member as complete and close
    release gate row C ("every member non-zero") on less evidence than the clause names.
    The boolean now means what its name says."""
    from src.api.diagnostics.bundle import _profile_block

    results = [
        {"file": "ordinary.json", "outcome": "ok"},
        {"file": _HEAVY, "outcome": "declined-ram", "declined_reason": "needs 3,322.8 MiB"},
    ]
    block = _profile_block("full", results)

    assert block["name"] == "full"
    assert block["complete_profile"] is False
    assert "INCOMPLETE" in block["note"] and _HEAVY in block["note"]
    assert [d["declined_by"] for d in block["declined"]] == ["machine"]


def test_a_full_run_that_declined_NOTHING_is_still_complete():
    from src.api.diagnostics.bundle import _profile_block

    block = _profile_block("full", [{"file": "a.json", "outcome": "ok"}])
    assert block["complete_profile"] is True
    assert block["declined"] == []


def test_the_manifest_says_WHO_declined_each_member():
    """Two different facts to an operator: one is a choice they can unmake by re-running,
    the other is this machine refusing on their behalf."""
    from src.api.diagnostics.bundle import _profile_block

    block = _profile_block(
        "light",
        [
            {"file": _HEAVY, "outcome": "declined-ram", "declined_reason": "ram"},
            {"file": "fixity.json", "outcome": "declined-light", "declined_reason": "heavy"},
        ],
    )
    by = {d["file"]: d["declined_by"] for d in block["declined"]}
    assert by == {_HEAVY: "machine", "fixity.json": "operator"}
    # ...and the note warns that FULL would not have collected the machine-declined one.
    assert "would not have run under FULL" in block["note"]


def test_a_RAM_decline_is_never_reported_as_a_light_profile_CHOICE(monkeypatch):
    """The order of the two checks carries meaning. Telling an operator they skipped
    something they were never going to be allowed to run on this box sends them to
    re-run under FULL for a member that would decline again."""
    import io
    import zipfile

    from src.api.diagnostics.bundle import _write_all_diagnostics_zip

    _ram(monkeypatch, 4029.0)
    members = [(_HEAVY, lambda: {"ran": True}), ("ordinary.json", lambda: {"ran": True})]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        results = _write_all_diagnostics_zip(members, z, profile="light")
    buf.seek(0)
    marker = zipfile.ZipFile(buf).read(_HEAVY + ".declined.txt").decode()

    assert {r["file"]: r["outcome"] for r in results}[_HEAVY] == "declined-ram"
    assert "does not have the memory" in marker
    assert "OO_ALLOW_BIG_SCANS" in marker
    assert "choice you made" not in marker.replace("not a choice you made", "")


# --------------------------------------------------------------------------- #
# R27 sized from the INSTANCE (2026-09-30): the keyword digest's need is      #
# estimated from the instance's own counts, and held against what is          #
# available now as well as against half of total RAM                          #
# --------------------------------------------------------------------------- #

_EST = "keyword-log-digest.json"


def _estimated(monkeypatch, need_mb, *, total, available, floor=256.0):
    """Pin the estimator's answer, the machine's RAM and what is free, and clear the override."""
    from src.api.diagnostics import bundle

    monkeypatch.delenv("OO_ALLOW_BIG_SCANS", raising=False)
    monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: total)
    monkeypatch.setitem(bundle._MEMBER_NEED_ESTIMATORS, _EST, lambda _db, _avail=None: need_mb)
    monkeypatch.setattr("src.database.maintenance._available_mb", lambda: available)
    monkeypatch.setattr("src.database.maintenance._read_memory_floor_mb", lambda: floor)
    return object()  # the gate only hands the session to the estimator


def test_an_estimated_member_declines_when_it_would_leave_the_memory_stop_no_room(monkeypatch):
    """1,500 MiB expected, 1,700 available, 256 kept free by the stop: 1,756 > 1,700. Half of an
    8 GB machine is 4,096, so R27's own rule would have let it run -- and the stop would have
    ended the export halfway, after minutes of work. It is declined before the first byte."""
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=8192.0, available=1700.0)
    reason = ram_declined_reason(_EST, db=db)
    assert reason and "1,500.0" in reason and "1,700" in reason and "256" in reason
    assert "estimated from this instance's own counts" in reason
    assert "OO_ALLOW_BIG_SCANS" in reason


def test_an_estimated_member_runs_when_it_fits_with_the_floor_to_spare(monkeypatch):
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=8192.0, available=1757.0)
    assert ram_declined_reason(_EST, db=db) is None


def test_an_estimated_member_still_obeys_half_of_total_RAM(monkeypatch):
    """R27 is kept, not replaced: plenty AVAILABLE does not lift the half-of-total rule."""
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=2500.0, available=9000.0)
    reason = ram_declined_reason(_EST, db=db)
    assert reason and "finding F12" in reason and "1,250" in reason


def test_the_existing_override_lifts_an_estimated_decline_too(monkeypatch):
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=2500.0, available=100.0)
    monkeypatch.setenv("OO_ALLOW_BIG_SCANS", "1")
    assert ram_declined_reason(_EST, db=db) is None


def test_an_unreadable_machine_never_declines_an_estimated_member(monkeypatch):
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=None, available=None, floor=None)
    assert ram_declined_reason(_EST, db=db) is None


def test_without_a_session_the_measured_constant_applies_exactly_as_before(monkeypatch):
    from src.api.diagnostics.bundle import ram_declined_reason

    _estimated(monkeypatch, 99999.0, total=4029.0, available=10.0)
    assert ram_declined_reason(_EST) is None  # 200 MiB measured < half of 4,029


def test_an_estimate_that_cannot_be_made_falls_back_to_the_measured_constant(monkeypatch):
    from src.api.diagnostics import bundle

    _estimated(monkeypatch, 0.0, total=4029.0, available=10.0)

    def _boom(_db, _avail=None):
        raise RuntimeError("no such table")

    monkeypatch.setitem(bundle._MEMBER_NEED_ESTIMATORS, _EST, _boom)
    monkeypatch.setitem(bundle._MEMBER_RSS_NEED_MB, _EST, 3322.8)
    reason = bundle.ram_declined_reason(_EST, db=object())
    assert reason and "it measured a 3,322.8 MiB peak RSS rise" in reason


def test_the_bundle_hands_its_session_to_the_gate(monkeypatch):
    """The member loop must pass its session, or the estimate is never made and the digest is
    gated on a constant forever."""
    import io
    import zipfile

    from src.api.diagnostics.bundle import _write_all_diagnostics_zip

    db = _estimated(monkeypatch, 1500.0, total=8192.0, available=1700.0)
    members = [(_EST, lambda: {"ran": True}), ("ordinary.json", lambda: {"ran": True})]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        results = _write_all_diagnostics_zip(members, z, profile="full", db=db)
    outcomes = {r["file"]: r["outcome"] for r in results}
    assert outcomes[_EST] == "declined-ram" and outcomes["ordinary.json"] == "ok"


# --------------------------------------------------------------------------- #
# The gate's OWN READING is recorded (field diagnostics 2026-09-30, B4): what  #
# it saw, for a member that ran and for one it declined                        #
# --------------------------------------------------------------------------- #


def test_a_declined_member_carries_what_the_gate_saw(monkeypatch):
    """The decision alone cannot be checked afterwards: the last sample in a run's pressure log
    is not the one the gate read (B4). Every number the decision rests on is in the reading."""
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=8192.0, available=1700.0)
    reading: dict = {}
    reason = ram_declined_reason(_EST, db=db, reading=reading)
    assert reason is not None
    assert reading["decision"] == "declined" and reading["declined_by"] == "available-memory"
    assert reading["need_mb"] == 1500.0 and reading["need_basis"] == "estimated"
    assert reading["total_mb"] == 8192.0 and reading["total_ceiling_mb"] == 4096.0
    assert reading["total_share"] == 0.5
    assert reading["available_mb"] == 1700.0 and reading["memory_stop_floor_mb"] == 256.0
    assert reading["available_line_applied"] is True and reading["override"] is False
    # THE STAMP IS THE TIME OF THE READING, in UTC with its offset, the form the session's memory
    # marks carry (the gate's reading is wanted on that timeline). Parsed and compared with the
    # clock: a stamp frozen at import, or one in local time with no offset, fails here.
    from datetime import UTC, datetime, timedelta

    sampled = datetime.fromisoformat(reading["sampled_at"])
    assert sampled.utcoffset() == timedelta(0), "UTC, with the offset written"
    assert abs((datetime.now(UTC) - sampled).total_seconds()) < 30
    assert sampled.microsecond == 0, "to the second"


def test_a_member_that_ran_carries_the_same_reading(monkeypatch):
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=8192.0, available=5000.0)
    reading: dict = {}
    assert ram_declined_reason(_EST, db=db, reading=reading) is None
    assert reading["decision"] == "run" and "declined_by" not in reading
    assert reading["available_mb"] == 5000.0 and reading["need_mb"] == 1500.0


def test_the_total_ram_line_names_itself_when_it_is_the_one_that_declined(monkeypatch):
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=2500.0, available=9000.0)
    reading: dict = {}
    assert ram_declined_reason(_EST, db=db, reading=reading)
    assert reading["declined_by"] == "total-ram" and reading["total_ceiling_mb"] == 1250.0


def test_the_counts_an_estimate_was_made_from_travel_with_it(monkeypatch):
    """"Estimated" is not a reading a reader can check; the counts are."""
    from src.api.diagnostics import bundle

    db = _estimated(monkeypatch, 0.0, total=8192.0, available=5000.0)
    monkeypatch.setitem(
        bundle._MEMBER_NEED_ESTIMATORS, _EST,
        lambda _db, _avail=None: {
            "need_mb": 1170.25, "articles": 1_825_094, "keyword_id_bound": 14_654_527,
            "languages": 83, "exportable_keywords": 415_000, "per_language": 5000,
        },
    )
    reading: dict = {}
    bundle.ram_declined_reason(_EST, db=db, reading=reading)
    assert abs(reading["need_mb"] - 1170.25) < 0.06
    assert reading["need_counts"] == {
        "articles": 1_825_094, "keyword_id_bound": 14_654_527, "languages": 83,
        "exportable_keywords": 415_000, "per_language": 5000,
    }
    assert "need_mb" not in reading["need_counts"]


def test_the_real_estimator_hands_its_counts_to_the_gate(tmp_path, monkeypatch):
    """Not a stub: the bundle's own estimator over a real (tiny) database fills the reading."""
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.diagnostics import bundle

    p = tmp_path / "gate.db"
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, language TEXT);"
        "CREATE TABLE keywords (id INTEGER PRIMARY KEY);"
        "INSERT INTO articles (id, language) VALUES (1,'en'),(2,'fr'),(3,'en');"
        "INSERT INTO keywords (id) VALUES (1),(2),(3),(4),(5);"
    )
    con.commit()
    con.close()
    db = sessionmaker(bind=create_engine(f"sqlite:///{p}"))()
    try:
        monkeypatch.delenv("OO_ALLOW_BIG_SCANS", raising=False)
        monkeypatch.setattr("src.config.memory_budget.total_ram_mb", lambda: 8192.0)
        monkeypatch.setattr("src.database.maintenance._available_mb", lambda: 6000.0)
        monkeypatch.setattr("src.database.maintenance._read_memory_floor_mb", lambda: 256.0)
        reading: dict = {}
        assert bundle.ram_declined_reason(_EST, db=db, reading=reading) is None
    finally:
        db.close()
    assert reading["need_basis"] == "estimated"
    counts = reading["need_counts"]
    assert counts["articles"] == 3 and counts["keyword_id_bound"] == 5
    assert counts["languages"] == 3  # en, fr, and the "?" an article without one falls in
    assert counts["exportable_keywords"] == 5 and counts["per_language"] == 5000


def test_a_static_reading_records_the_machine_without_having_used_the_available_line(monkeypatch):
    """Without a session the measured constant applies and R27's half-of-RAM rule is the only
    line. The numbers are still recorded (they are what the next reader wants); the reading says
    the available-memory line was not applied to them."""
    from src.api.diagnostics.bundle import ram_declined_reason

    _estimated(monkeypatch, 99999.0, total=4029.0, available=10.0)
    reading: dict = {}
    assert ram_declined_reason(_EST, reading=reading) is None
    assert reading["need_basis"] == "static-constant" and "need_counts" not in reading
    assert reading["need_mb"] == 200.0
    assert reading["available_mb"] == 10.0 and reading["available_line_applied"] is False
    assert reading["decision"] == "run"


def test_an_estimate_that_failed_says_so_in_the_reading(monkeypatch):
    from src.api.diagnostics import bundle

    _estimated(monkeypatch, 0.0, total=4029.0, available=2000.0)

    def _boom(_db, _avail=None):
        raise RuntimeError("no such table: keywords")

    monkeypatch.setitem(bundle._MEMBER_NEED_ESTIMATORS, _EST, _boom)
    reading: dict = {}
    bundle.ram_declined_reason(_EST, db=object(), reading=reading)
    assert reading["need_basis"] == "static-constant"
    assert reading["estimate_error"].startswith("RuntimeError: no such table")


def test_a_gated_member_nothing_could_size_is_recorded_as_unavailable_never_blank(monkeypatch):
    from src.api.diagnostics import bundle

    _estimated(monkeypatch, 0.0, total=4029.0, available=2000.0)
    monkeypatch.setitem(bundle._MEMBER_NEED_ESTIMATORS, _EST, lambda _db, _avail=None: 1 / 0)
    monkeypatch.delitem(bundle._MEMBER_RSS_NEED_MB, _EST)
    reading: dict = {}
    assert bundle.ram_declined_reason(_EST, db=object(), reading=reading) is None
    assert reading["need_mb"] is None and reading["need_basis"] == "unavailable"
    assert reading["decision"] == "run" and "ZeroDivisionError" in reading["estimate_error"]


def test_an_unknown_member_has_no_reading(monkeypatch):
    """The gate made no decision about it, so there is nothing to record -- an empty dict, not a
    fabricated 'run'."""
    from src.api.diagnostics.bundle import ram_declined_reason

    _estimated(monkeypatch, 1500.0, total=512.0, available=1.0)
    reading: dict = {}
    assert ram_declined_reason("card-audit.json", db=object(), reading=reading) is None
    assert reading == {}


def test_the_override_is_in_the_reading_and_the_reading_does_not_change_the_answer(monkeypatch):
    from src.api.diagnostics.bundle import ram_declined_reason

    db = _estimated(monkeypatch, 1500.0, total=2500.0, available=100.0)
    with_reading: dict = {}
    without = ram_declined_reason(_EST, db=db)
    assert without is not None
    assert ram_declined_reason(_EST, db=db, reading=with_reading) == without
    monkeypatch.setenv("OO_ALLOW_BIG_SCANS", "1")
    lifted: dict = {}
    assert ram_declined_reason(_EST, db=db, reading=lifted) is None
    assert lifted["override"] is True and lifted["decision"] == "run"
    assert lifted["available_mb"] == 100.0, "the override lifts the decline, not the witness"


def test_the_manifest_records_the_reading_for_a_declined_and_for_a_run_member(monkeypatch):
    import io
    import json
    import zipfile

    from src.api.diagnostics.bundle import _write_all_diagnostics_zip

    for available, outcome in ((1700.0, "declined-ram"), (5000.0, "ok")):
        db = _estimated(monkeypatch, 1500.0, total=8192.0, available=available)
        members = [(_EST, lambda: {"ran": True}), ("ordinary.json", lambda: {"ran": True})]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            results = _write_all_diagnostics_zip(members, z, profile="full", db=db)
        by_file = {r["file"]: r for r in results}
        assert by_file[_EST]["outcome"] == outcome
        assert by_file[_EST]["gate"]["available_mb"] == available
        assert by_file[_EST]["gate"]["decision"] == ("declined" if outcome != "ok" else "run")
        assert "gate" not in by_file["ordinary.json"], "a member the gate does not know has none"
        shipped = json.loads(zipfile.ZipFile(buf).read("manifest.json"))["members"]
        assert {m["file"]: m for m in shipped}[_EST]["gate"] == by_file[_EST]["gate"]
