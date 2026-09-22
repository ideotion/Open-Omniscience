"""The planned-work reverse index: what it must find, and what it may never cry wolf about.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THE MECHANISM EXISTS (maintainer-asked 2026-09-22): *"find a way so that future bug
discovery would not contradict what has been planned ... to help future unaware sessions to
become aware of the changes, and to avoid redoing some thinking that has already been
done."* ``shipped.csv`` answers "which files WERE touched"; nothing answered "which files a
PLANNED decision already owns", and ``CLAUDE.md`` names none of the plan files at all.

WHY THESE TESTS AND NOT OTHERS. The index is parsed out of prose, so the two ways it dies
are both silent:

1. **It stops finding things** — a brief's header format drifts and the generator returns
   fewer rows, with no error. Guarded by asserting that EVERY brief contributes and that
   named, load-bearing pairs are present.
2. **It finds too much** — and a tool that answers every question the same way answers
   none of them. Two real over-matches are pinned as regressions below, because both were
   live in the first cut and both would have discredited the tool on its first use.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import planned_index  # noqa: E402


@pytest.fixture(scope="module")
def entries():
    return planned_index.build()


def _by_path(entries, path):
    return [e for e in entries if e.path == path]


# --------------------------------------------------------------------------- #
# It finds what it is for                                                     #
# --------------------------------------------------------------------------- #


def test_every_slice_brief_contributes_at_least_one_entry(entries):
    """THE ROT GUARD. The generator reads each brief's own blockquote header. If that
    format drifts -- or a brief is added without one -- the generator returns quietly
    fewer rows and the tool degrades to silence, which reads exactly like "nothing is
    planned for this file". A brief that contributes nothing is the alarm."""
    briefs = {p.stem.split("_")[0] for p in planned_index.BRIEFS.glob("S*.md")}
    contributing = {e.id for e in entries if e.kind == "slice"}
    assert briefs, "no slice briefs were found at all -- the path is wrong"
    assert not (briefs - contributing), f"briefs that contribute nothing: {sorted(briefs - contributing)}"


def test_it_finds_the_ruling_that_governs_the_next_change_to_a_file(entries):
    """The case the mechanism was asked for: a session opens a file and learns a decision
    about it already exists. R26 rules the next change to the memory tiers."""
    ids = {e.id for e in _by_path(entries, "src/config/memory_budget.py")}
    assert "R26" in ids


def test_it_finds_an_UNANSWERED_ruling_standing_over_a_code_path(entries):
    """Q925 is the unanswered law-adapter-order question, and the adapter registry is
    where an unaware session would answer it for itself."""
    hits = [e for e in _by_path(entries, "src/law/adapters/registry.py") if e.id == "Q925"]
    assert hits and hits[0].status == "pending-ruling"


def test_it_carries_a_briefs_own_MUST_NOT_TOUCH_clause(entries):
    """The loudest thing a brief says, and the one a later session is likeliest to cross
    without knowing it was ever decided."""
    forbidden = [e for e in entries if e.status == "must-not-touch"]
    assert forbidden, "no Must NOT touch clause was extracted from any brief"
    assert all(e.kind == "slice" for e in forbidden)


def test_two_slices_that_must_never_be_concurrent_both_show_on_the_file_they_share(entries):
    """S05-02 and S05-10 both rewrite the merge, and S05-02's own header says they must
    never run concurrently. Either one alone is a plan; seeing both is the warning."""
    ids = {e.id for e in _by_path(entries, "src/backup/merge.py")}
    assert {"S05-02", "S05-10"} <= ids


# --------------------------------------------------------------------------- #
# It does not cry wolf                                                        #
# --------------------------------------------------------------------------- #


def test_a_BARE_ROOT_is_never_an_index_key(entries):
    """REGRESSION, live in the first cut. S08-01's scope says it adds "new modules under
    `src/`" -- true, and useless. Taken as a directory entry it matched every source file
    in the tree, so two 0.7/0.8 briefs appeared on every lookup any session would ever
    run. An index that answers every question the same way answers none of them."""
    roots = {r.rstrip("/") for r in planned_index._ROOTS}
    bare = [e for e in entries if e.path.rstrip("/") in roots]
    assert not bare, f"bare roots indexed as paths: {sorted({e.path for e in bare})}"


def test_a_directory_entry_always_has_a_component_below_its_root(entries):
    for e in entries:
        if e.path.endswith("/"):
            assert e.path.rstrip("/").count("/") >= 1, e.path


def test_a_file_is_never_indexed_against_ITSELF(entries):
    """A gate file naming itself in every one of its own rows is not information; it was
    148 rows for one path before this."""
    assert not [e for e in entries if e.path == e.where.split(":")[0]]


def test_a_SLICE_being_blocked_is_not_the_same_status_as_a_ruling_being_unanswered(entries):
    """REGRESSION, and the one that would have made the strict check unusable. A blocked
    SLICE cannot start; that never means its files are untouchable. Conflating the two put
    `src/static/index.html` -- which nearly every PR edits -- under a hard failure."""
    statuses = {e.status for e in entries}
    assert "slice-blocked" in statuses
    assert "blocked" not in statuses, "the ambiguous 'blocked' status is back"


def test_no_path_carries_an_unbounded_pile_of_entries(entries):
    from collections import Counter

    counts = Counter(e.path for e in entries)
    over = {p: n for p, n in counts.items() if n > planned_index._PATH_CAP + 1}
    assert not over, f"paths over the cap with no overflow row: {over}"


def test_an_overflow_row_states_the_REAL_total_rather_than_truncating_silently(entries):
    for e in entries:
        if e.status == "more":
            assert "further entries" in e.title and "total for this path" in e.title


# --------------------------------------------------------------------------- #
# The query tool, end to end                                                  #
# --------------------------------------------------------------------------- #


def _run(*args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "planned.py"), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )


def test_a_lookup_prints_the_ruling_and_where_to_read_it():
    out = _run("src/config/memory_budget.py")
    assert out.returncode == 0, out.stderr
    assert "R26" in out.stdout
    assert "RULINGS_INDEX.md" in out.stdout


def test_an_unplanned_path_says_so_AND_says_the_absence_is_weak_evidence():
    """The honest refusal. The index is parsed out of prose, so 'nothing found' is not
    'nothing exists' -- and a confident silence is the expensive failure here."""
    out = _run("src/this/file/does/not/exist.py")
    assert out.returncode == 0
    assert "nothing planned" in out.stdout
    assert "ABSENCE IS WEAKER EVIDENCE THAN PRESENCE" in out.stdout


def test_strict_FAILS_on_a_code_path_under_an_unanswered_ruling():
    out = _run("--strict", "src/law/adapters/registry.py")
    assert out.returncode == 2, out.stdout
    assert "Q925" in out.stdout
    assert "ACK Q925" in out.stdout, "the failure must say how to proceed deliberately"


def test_strict_PASSES_on_a_ledger_file_every_session_is_required_to_edit():
    """THE PROTOCOL requires recording a ruling in `OPEN_QUEUE.md` in the turn it is given.
    A check that failed a PR for doing that would be the tool arguing with the rule it
    exists to serve."""
    out = _run("--strict", "docs/ledger/OPEN_QUEUE.md", "docs/ledger/shipped.csv")
    assert out.returncode == 0, out.stdout


def test_strict_PASSES_on_a_file_merely_claimed_by_a_held_slice():
    out = _run("--strict", "src/static/index.html")
    assert out.returncode == 0, out.stdout
