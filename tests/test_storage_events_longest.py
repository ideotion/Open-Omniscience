"""The journal keeps the longest events as well as the newest (the coordinator's keep rule, 2026-10-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS PINS. The 16 Oct 2026 bundles kept the newest 20 gate holds. The longest hold of the session (219.6 s) was not among them,
because a stream of newer, shorter holds had pushed it out; "the newest N" shows the lead-up to a crash and hides the worst stall of
the week. ``storage_events.LONGEST`` splits the cap of four kinds: the ``n`` longest by a named field AND the rest of the cap for the
newest. Every case below is red without the rule: the first is the exact failure in the bundles.
"""

from __future__ import annotations

import json

import pytest

from src.monitoring import storage_events as se

from .test_storage_events import _events, _member, journal  # noqa: F401  (journal is a fixture)


def _holds(*seconds: float, start: int = 0) -> None:
    for i, s in enumerate(seconds, start=start):
        se.record("gate_hold", {"n": i, "seconds": s})


def _by_n(kind: str = "gate_hold") -> dict[int, dict]:
    return {e["n"]: e for e in _events(kind)}


# --------------------------------------------------------------------------- #
#  The failure in the 16 Oct bundles
# --------------------------------------------------------------------------- #
def test_an_old_long_hold_survives_a_stream_of_newer_short_ones(journal):  # noqa: F811
    se.record("gate_hold", {"n": -1, "seconds": 219.6, "holder": "the longest of the session"})
    _holds(*([15.0] * 60))
    k = _member()["kinds"]["gate_hold"]
    kept = {e["n"]: e for e in k["events"]}
    assert -1 in kept, "the longest hold of the journal is kept though 60 newer ones came after it"
    assert kept[-1]["seconds"] == 219.6 and kept[-1]["picked_by"] == "longest"
    assert (k["total"], k["kept"], k["dropped"]) == (61, 20, 41), "the cap still limits what is kept, never what is counted"


def test_the_newest_are_kept_beside_the_longest_and_say_so(journal):  # noqa: F811
    for n, s in enumerate([100.0 + n for n in range(10)]):  # ten long holds, oldest first, the shortest of them first
        se.record("gate_hold", {"n": n, "seconds": s})
    _holds(*([1.0] * 30), start=10)  # then thirty short ones
    k = _member()["kinds"]["gate_hold"]
    assert k["keep_rule"] == {"longest": 10, "by": "seconds", "newest": 10}
    by_n = {e["n"]: e for e in k["events"]}
    assert sorted(by_n) == list(range(0, 10)) + list(range(30, 40)), "the ten longest and the ten newest, nothing else"
    assert {by_n[n]["picked_by"] for n in range(0, 10)} == {"longest"}
    assert {by_n[n]["picked_by"] for n in range(30, 40)} == {"newest"}
    assert [e["n"] for e in k["events"]] == sorted(by_n), "oldest first, as every other list in the member"


def test_a_hold_that_is_both_one_of_the_longest_and_one_of_the_newest_is_kept_once_and_says_both(journal):  # noqa: F811
    _holds(*([1.0] * 25))
    se.record("gate_hold", {"n": 25, "seconds": 500.0})  # the longest and the newest at once
    k = _member()["kinds"]["gate_hold"]
    by_n = {e["n"]: e for e in k["events"]}
    assert by_n[25]["picked_by"] == "both"
    assert k["kept"] == 20 == len(by_n), "counted once: the cap is never exceeded by an overlap"
    assert sorted(by_n)[-10:] == list(range(16, 26)), "the room the overlap left goes to the next newest, so the newest ten stay ten"


def test_the_kept_list_never_exceeds_the_cap_whatever_the_order_and_holds_both_guarantees(journal):  # noqa: F811
    import random

    rng = random.Random(7)
    lengths = [round(i * 0.01 + rng.random() * 0.005, 4) for i in range(200)]  # distinct, and in no particular order once shuffled
    rng.shuffle(lengths)
    for n, s in enumerate(lengths):
        se.record("gate_hold", {"n": n, "seconds": s})
        assert len(_events("gate_hold")) <= se.KEEP["gate_hold"]
    k = _member()["kinds"]["gate_hold"]
    assert (k["total"], k["kept"], k["dropped"]) == (200, 20, 180)
    kept = {e["n"] for e in k["events"]}
    longest_ten = set(sorted(range(200), key=lambda i: -lengths[i])[:10])
    assert longest_ten <= kept, "the ten longest of the whole stream are all there, wherever they came in it"
    assert set(range(190, 200)) <= kept, "and so are the ten newest"


# --------------------------------------------------------------------------- #
#  What counts as a length
# --------------------------------------------------------------------------- #
def test_ties_go_to_the_newer_hold(journal):  # noqa: F811
    _holds(*([30.0] * 40))
    assert sorted(_by_n()) == list(range(20, 40)), "equal lengths: the newer wins, so a flat stream is the plain newest-twenty rule"


@pytest.mark.parametrize("junk", [None, True, False, "219.6", float("nan"), [219.6], {"s": 1}], ids=repr)
def test_a_value_that_is_not_a_number_is_never_a_length(journal, junk):  # noqa: F811
    """A hold whose ``seconds`` is a bool, a string or NaN cannot out-rank a real one, cannot disturb the order of the real ones (a NaN
    in a sort key leaves the order undefined), and cannot crash the journal. Twelve real holds are longer than the ten the rule keeps,
    the junk one sits among them, and thirty short ones follow."""
    for n in range(3):
        se.record("gate_hold", {"n": n, "seconds": 200.0 - n})
    se.record("gate_hold", {"n": -1, "seconds": junk})
    for n in range(3, 12):
        se.record("gate_hold", {"n": n, "seconds": 200.0 - n})
    _holds(*([0.5] * 30), start=100)  # shorter than True would be (1.0): a bool read as a number would be a long hold
    kept = _by_n()
    assert -1 not in kept, "a non-number is the shortest of all: it goes when the cap is reached"
    assert set(range(10)) <= set(kept), "the ten longest real holds are all there"
    assert len(kept) == 20


@pytest.mark.parametrize("junk", [True, float("nan")], ids=repr)
def test_a_value_that_is_not_a_number_does_not_out_rank_short_real_holds_either(journal, junk):  # noqa: F811
    """The other way round: among holds all SHORTER than a bool would read as (True is 1.0), the junk one is still not the longest."""
    se.record("gate_hold", {"n": -1, "seconds": junk})
    _holds(*([0.5] * 40))
    assert -1 not in _by_n()
    assert len(_by_n()) == 20


@pytest.mark.parametrize("at", [0, 3, 6, 9])
def test_select_with_a_nan_among_the_real_lengths_keeps_the_ten_longest_real_ones(at):
    """The function by itself, on the whole list at once (the journal evaluates it on every append, which can hide an order a NaN
    scrambled): a NaN in a sort key leaves the order of the others undefined, so it must never be a key."""
    real = [{"n": n, "seconds": 200.0 - n} for n in range(12)]
    events = [*real[:at], {"n": -1, "seconds": float("nan")}, *real[at:], *({"n": 100 + i, "seconds": 0.5} for i in range(30))]
    kept = {e["n"] for e in se._select("gate_hold", events)}
    assert -1 not in kept and set(range(10)) <= kept and len(kept) == 20


def test_an_event_without_the_field_is_kept_only_as_one_of_the_newest(journal):  # noqa: F811
    for n in range(40):
        se.record("gate_hold", {"n": n})  # no seconds at all: the rule falls back to the plain newest
    assert sorted(_by_n()) == list(range(20, 40))


# --------------------------------------------------------------------------- #
#  The same rule for the other kinds that have a duration
# --------------------------------------------------------------------------- #
def test_the_rule_names_a_field_for_every_kind_it_splits_and_no_other():
    assert set(se.LONGEST) == {"gate_hold", "guard", "pool_timeout", "open"}
    for kind, (field, n_long) in se.LONGEST.items():
        assert 0 < n_long < se.KEEP[kind], f"{kind}: a rule that keeps only the longest, or none of them, is not a split"
        assert field in {"seconds", "waited_s", "total_ms"}
    for kind in ("checkpoint", "checkpoint_notable", "run_export", "run_import", "run_verify"):
        assert kind not in se.LONGEST, "the checkpoint has its own notable lane and the run kinds their own rule"


def test_a_long_guard_engagement_survives_a_stream_of_short_ones(journal):  # noqa: F811
    se.record("guard", {"n": -1, "seconds": 3600.0, "kind": "wal"})
    for n in range(30):
        se.record("guard", {"n": n, "seconds": 5.0, "kind": "wal"})
    k = _member()["kinds"]["guard"]
    kept = {e["n"]: e for e in k["events"]}
    assert -1 in kept and kept[-1]["picked_by"] == "longest"
    assert k["keep_rule"] == {"longest": 5, "by": "seconds", "newest": 5}
    assert (k["total"], k["kept"], k["dropped"]) == (31, 10, 21)


def test_the_longest_pool_timeout_and_the_slowest_open_survive_too(journal):  # noqa: F811
    se.note_pool_timeout(waited_s=95.5, thread="the slow one", route="GET /x")
    for _ in range(25):
        se.note_pool_timeout(waited_s=30.0, thread="t", route="GET /y")
    se.note_open("unlock", total_ms=99_000.0)
    for _ in range(25):
        se.note_open("unlock", total_ms=1_000.0)
    pt = _events("pool_timeout")
    assert any(e["waited_s"] == 95.5 and e["picked_by"] == "longest" for e in pt)
    assert len(pt) == 10
    op = _events("open")
    assert any(e["total_ms"] == 99_000.0 and e["picked_by"] == "longest" for e in op)
    assert len(op) == 10


def test_a_kind_without_a_rule_keeps_the_newest_and_carries_no_picked_by(journal):  # noqa: F811
    for n in range(30):
        se.record("checkpoint", {"n": n, "seconds": 100.0 - n})
    k = _member()["kinds"]["checkpoint"]
    assert [e["n"] for e in k["events"]] == list(range(20, 30)), "the plain newest ten"
    assert all("picked_by" not in e for e in k["events"]) and "keep_rule" not in k


# --------------------------------------------------------------------------- #
#  Open events and the file
# --------------------------------------------------------------------------- #
def test_an_open_hold_is_always_kept_and_one_that_was_cut_cannot_be_updated(journal):  # noqa: F811
    se.record("gate_hold", {"n": 0, "seconds": 1.0}, key=("hold", 0))
    _holds(*([2.0] * 40), start=1)
    assert se.update("gate_hold", ("hold", 0), {"phase": "late"}) is False, "it was cut: nothing to update, and no error"
    se.record("gate_hold", {"n": 100, "seconds": 0.0}, key=("hold", 100))
    assert 100 in _by_n(), "the hold in progress is the newest event, so it is always kept"
    assert se.update("gate_hold", ("hold", 100), {"phase": "now"}) is True
    assert se.end("gate_hold", ("hold", 100), {"seconds": 250.0}) is True
    _holds(*([2.0] * 40), start=101)
    kept = _by_n()
    assert 100 in kept and kept[100]["seconds"] == 250.0 and kept[100]["picked_by"] == "longest", (
        "ended at 250 s, it was the newest and is now the longest: it stays after 40 shorter holds"
    )


def test_the_longest_survives_a_restart_and_the_next_process_adds_to_it(journal, monkeypatch):  # noqa: F811
    se.record("gate_hold", {"n": -1, "seconds": 219.6})
    _holds(*([10.0] * 40))
    se.flush()
    se.reset_for_tests(keep_file=True)  # the process ends: memory gone, the file stays
    monkeypatch.setattr(se, "_PROC", "the-next-process")
    assert -1 in _by_n() and _by_n()[-1]["picked_by"] == "longest", "read back from the file"
    _holds(*([10.0] * 40), start=100)  # the next process writes 40 more short ones
    k = _member()["kinds"]["gate_hold"]
    kept = {e["n"]: e for e in k["events"]}
    assert -1 in kept and kept[-1]["session"] == "earlier", "an earlier process's longest hold is still there, marked as earlier"
    assert (k["total"], k["kept"], k["dropped"]) == (81, 20, 61)
    assert sorted(n for n in kept if n != -1) == list(range(121, 140)), "the rest of the cap is the newest, this process's"


def test_a_file_the_previous_build_wrote_is_read_without_a_loss_and_the_rule_applies_from_the_next_record(journal):  # noqa: F811
    for n in range(20):  # the newest 20, which is all the previous build kept
        se.record("gate_hold", {"n": n, "seconds": float(n)})
    se.flush()
    se.reset_for_tests(keep_file=True)
    k = _member()["kinds"]["gate_hold"]
    assert (k["total"], k["kept"], k["dropped"]) == (20, 20, 0)
    se.record("gate_hold", {"n": 99, "seconds": 0.5})
    kept = _by_n()
    assert len(kept) == 20 and 99 in kept
    assert set(range(10, 20)) <= set(kept), "the ten longest of the old file are still there"
    assert 0 not in kept, "the shortest and oldest went"


def test_a_file_that_holds_more_than_the_cap_is_cut_by_the_rule_when_it_is_read(journal):  # noqa: F811
    """A journal file edited by hand, or written by a build with a larger cap, must not put more than the cap in the member."""
    for n in range(20):
        se.record("gate_hold", {"n": n, "seconds": 1.0})
    se.flush()
    doc = json.loads(journal.read_text(encoding="utf-8"))
    events = doc["kinds"]["gate_hold"]["events"]
    extra = [{**events[0], "n": 20 + i, "seconds": 1.0} for i in range(20)]
    events[3]["seconds"] = 500.0  # an old long one in the middle
    doc["kinds"]["gate_hold"]["events"] = events + extra
    doc["kinds"]["gate_hold"]["total"] = 40
    journal.write_text(json.dumps(doc), encoding="utf-8")
    se.reset_for_tests(keep_file=True)
    k = _member()["kinds"]["gate_hold"]
    kept = {e["n"]: e for e in k["events"]}
    assert 3 in kept and kept[3]["picked_by"] == "longest"
    assert (k["total"], k["kept"], k["dropped"]) == (40, 20, 20)


# --------------------------------------------------------------------------- #
#  The select function itself, and the budget cut
# --------------------------------------------------------------------------- #
def test_select_is_idempotent_and_keeps_the_order():
    events = [{"n": n, "seconds": float((n * 37) % 91)} for n in range(120)]
    once = se._select("gate_hold", events)
    assert len(once) == 20 and once == sorted(once, key=lambda e: e["n"])
    assert se._select("gate_hold", once) == once
    assert se._select("gate_hold", events[:7]) == events[:7], "within the cap nothing is touched"


def test_the_budget_cut_spares_the_longest_until_nothing_else_is_left(journal):  # noqa: F811
    se.record("gate_hold", {"n": -1, "seconds": 219.6, "route": "r" * 100})
    for n in range(40):
        se.record("gate_hold", {"n": n, "seconds": 3.0, "route": "r" * 100})
    full = len(json.dumps(_member(), separators=(",", ":")))
    cut = se.diagnostics_member(full - 1500)
    kept = {e["n"] for e in cut["kinds"]["gate_hold"]["events"]}
    assert -1 in kept, "the zip is kept for this event: the oldest of the OTHERS goes first"
    gone = cut["dropped_to_fit"]["gate_hold"]
    assert cut["kinds"]["gate_hold"]["kept"] == 20 - gone
    assert cut["kinds"]["gate_hold"]["total"] == 41 and cut["kinds"]["gate_hold"]["dropped"] == 21, "the cap's own counts never change by the cut"
    assert not any(n in kept for n in range(20, 20 + gone)), "the oldest newest-pick went first"
