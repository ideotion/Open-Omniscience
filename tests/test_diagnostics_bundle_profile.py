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
    real member list's source rather than a copy of it."""
    import pathlib

    src = pathlib.Path("src/api/diagnostics/bundle.py").read_text(encoding="utf-8")
    block = src.split("def _all_diagnostics_members", 1)[1].split("\ndef ", 1)[0]

    missing = [name for name in _LIGHT_DECLINED if f'("{name}"' not in block]
    assert not missing, f"declined names that are not members: {missing}"


def test_every_declined_member_states_a_reason():
    for name, reason in _LIGHT_DECLINED.items():
        assert reason and len(reason) > 40, f"{name} has no stated reason"
