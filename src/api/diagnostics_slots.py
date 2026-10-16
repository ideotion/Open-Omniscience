"""The slot table: where an owner's member of the Diagnostics zip comes from, without touching ``bundle.py``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (R119, docs/plans/2026-10-06-diagnostics-redesign/PLAN.md section 7). Every owner who wanted a
record in the zip used to edit ``bundle.py``, which has one pusher and a review per head; five
owners waited on one file. The contract below lets an owner add a member by writing ONE function in
their own module and one row here.

THE CONTRACT for a producer, ``def diagnostics_member(max_bytes: int) -> dict``:

* JSON-able, and it never raises (a raise becomes ``.error.txt`` and the outcome ``error``, as for any
  member, but a producer that can fail says so in its own words instead);
* it keeps the NEWEST records and says what it dropped when it reaches ``max_bytes``;
* counts, times, sizes, settings and reasons only, every figure carrying its method and n; no term,
  no article text, no address;
* it opens its own session if it needs one (a slot is a non-database member, so the build runs it on
  a worker thread under the 300 s deadline of every such member).

A producer that already exists in its owner's module with another signature needs no slot: it is
called from ``bundle.py``'s own list (``release-run.json`` calls ``last_release_run_report``,
``soak-window.json`` the plan thread's function), and the owner extends it there.

WHAT THE BUDGET IS. ``budget_bytes`` is the most RAW JSON the producer is asked to keep (``max_bytes``).
It protects the next member's room in a typical zip: one history, which grows with the number of
loggers or editions, cannot take what the other members' newest records need. It is NOT what keeps a
file under 4,000,000 bytes (the splitter guarantees that whatever the content is) and it is not a
guess about a typical size: the plan's table states each number and what it was measured on. The
budgets add to :data:`TOTAL_BUDGET_BYTES` at most; the zip carries what the producers write, which on
a young install is a small part of it. A producer that returns more than its budget is NOT cut here
(a cut that is not the producer's own would break its structure): the manifest entry says
``over_budget`` and the member is written whole (one file; the volume splitter cuts a file on record
boundaries only when the archive does not fit 4,000,000 bytes), and the test of each producer holds it
to its number.

WHAT A SLOT'S ANSWER PASSES THROUGH. :func:`thunk` hands the producer's answer through the bundle's member net
(``_scrubbed_member_value``: a leaf JSON cannot hold becomes the stated marker, then every string goes through
``scrubbed_value``, the passphrases the process holds taken out in every shape), so a producer that
catches its own failure and returns the engine's words is not a way for a held secret to reach the
zip. The producer still writes the class and a fixed label, not the words (the scrub is the net, not the
rule), and ``tests/test_diagnostic_slots.py`` plants a secret through a slot.

A SLOT WHOSE MODULE IS NOT IN THIS BUILD is listed in the manifest as ``not-in-build`` and writes no file,
so an owner can have a row here before their code lands, and a reader of an old archive is told the
member did not exist yet rather than that it came back empty. A slot whose module IS here but whose
function is missing or wrong is a failure, not an absence: ``tests/test_diagnostic_slots.py`` fails on
it, and at run time it is an ``error`` member with the reason. A MISSPELLED MODULE PATH, though, reads as
``not-in-build`` (the module is not found): for a slot built at this head ``test_every_slot_is_a_member_of_this_build_or_named_absent_and_never_both``
fails on it, and for a row not built yet only the owner's own PR shows the typo.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Slot:
    """One member that a module outside ``bundle.py`` produces."""

    name: str  # the member's file name in the zip
    target: str  # "module.path:function"
    owner: str  # who maintains the producer
    budget_bytes: int  # the most raw JSON the producer is asked to keep
    area: str  # the manifest's topical class for the member
    takes_budget: bool = True  # False: the producer has its own bound and no ``max_bytes``
    kwargs: dict[str, Any] = field(default_factory=dict)  # fixed arguments for a producer without a budget


#: The table. Order is the order the members are written. The first five are built; the rest are the
#: owners' records announced in the plan (section 6), each a proposal of where the owner's
#: ``diagnostics_member`` lives: an owner whose module has another path changes ONE line here.
#: THE NUMBERS, what each protects and how it was got (the plan's section 4 states the same ones). WHAT
#: THEY PROTECT: the budget is the raw JSON the producer is ASKED to keep, so one history cannot take the
#: room the other members' newest records need in a typical zip. It is NOT what keeps a file under the
#: 4,000,000 bytes of R119: the splitter keeps every part within that whatever a member holds (a member
#: above its budget is named ``over_budget`` in the manifest and written whole; the splitter cuts a file on
#: record boundaries only when the archive does not fit one part, and drops none), and ``test_the_budgets_and_the_fixed_members_fit_one_part`` holds the
#: budgets to the room they must leave. HOW EACH WAS GOT:
#:   * ``vitals`` 260,000: MEASURED on the producer's own fixture (25 loggers): 140 KB for the full
#:     retention, 189 KB with the three previous sessions' tails, 246 KB with 58-character logger names;
#:     260 KB is 6 per cent above the last (``vitals_history.MEMBER_BUDGET_BYTES`` holds the argument and
#:     a test holds the two numbers together). Not a maximum: a longer name drops the oldest hours first
#:     and the member says so.
#:   * ``runs`` 40,000: a BOUND, not a measurement: ten runs and sixty serves (``KEEP_RUNS``,
#:     ``KEEP_SERVES``), each line a few hundred bytes (the failure text is cut to ``ERROR_CHARS``),
#:     about 30 KB at 400 bytes a line.
#:   * ``pressure-light`` 40,000: MEASURED, not guessed: one snapshot with three busy threads at the depth
#:     of a test stack is 664 bytes, so the 16 the member can hold (8 per session, two sessions) are 10.6
#:     KB, and 40,000 leaves about four times that for the deeper stacks of a real run; a longer tail is
#:     cut oldest first and the member says how many.
#:   * ``boots`` 30,720: RC's own ``DEFAULT_MAX_BYTES`` (30 KiB), the argument is in ``boots.py`` (ten boots,
#:     each end record up to about 5 KiB; the member drops the OLDEST boots until it fits and says how
#:     many), and a test holds the two numbers together.
#:   * ``database-damage`` 40,000: MEASURED at the record's full retention, ``INCIDENTS_KEEP`` (20) incidents of
#:     distinct shapes and no table lists: 16,187 bytes (about 590 each, plus 4.4 KB of counters, notes and
#:     method); the per-table lists of a real check come on top, so 40,000 is about 2.5 times the measured part
#:     and ``test_the_damage_budget_holds_a_full_record_twice_over`` holds the two together. Over it the oldest
#:     incidents go first and then the check's table lists, and the member says each.
#:   * ``storage-events`` 125,000: MEASURED at the journal's full retention (``storage_events.KEEP``: 20 holds of the write gate, 10 each
#:     of guard engagements, checkpoints, notable checkpoints, store opens, pool timeouts and the three run kinds: the volume backup, restore and
#:     verification, the legacy single-file restores, the newsletter folder imports and the folder backups, restores and verifications of the large data) with the events the hooks write, the checkpoints with the reader snapshot ``hygiene`` hands every one of
#:     them, each run with EVERY field it can carry at once at a large value and the seconds of a run of more than a day (963 bytes raw with the process id, 945 as the member shows it; a real run is 146 to 299): 78,634
#:     bytes with ordinary names, 123,344 with every thread, route and frame name at the 160-character cut (the longest ``_clean`` lets
#:     through), of which 4,735 is the fixed part, the member's own text (each figure moves by a byte or two with the width of the process id every event carries). The keep rule
#:     (the longest beside the newest) added 1,494 to each: 494 to the fixed part (its sentence in the method and a ``keep_rule`` line for each of the four kinds it splits) and 1,000 for the ``picked_by`` of the 50 events of those kinds; the longest are kept beside the newest, so the cap does not move. 125,000 is
#:     1.3 per cent above the second (the page reading each store open carries, with every field either source can carry at its widest, adds 337 bytes to each of the ten). The gate holds carry the phase, its sample counts, the holder thread's CPU and switch counts and the machine's memory (4,920 bytes over the 20). The hard ceiling is 100 events at
#:     ``MAX_EVENT_BYTES`` (3,000), 300 KB, and a member over its budget drops the OLDEST events of its largest kind (one kept as a longest goes last) and says how
#:     many (``dropped_to_fit``); ``total`` and ``dropped`` never change by that cut. ``test_the_storage_events_budget_holds_a_full_journal``
#:     rebuilds both measurements and holds them to this number.
#:   * ``keyword-pipeline`` 60,000, the one not built yet, is its owner's FIRST ESTIMATE, to be replaced by a
#:     measurement when it lands (the budget is one line here, never in ``bundle.py``).
SLOTS: tuple[Slot, ...] = (
    Slot("vitals.json", "src.monitoring.vitals_history:diagnostics_member", "export", 260_000, "memory"),
    Slot("runs.json", "src.monitoring.diagnostics_runs:diagnostics_member", "export", 40_000, "runs"),
    # The minutes before a kill (WAL's snapshot, every 15 s while memory is short): vitals.json holds the
    # hours and days before it and names this member for what follows (``tail_in``).
    Slot("pressure-light.json", "src.monitoring.session_hwm:diagnostics_member", "WAL", 40_000, "memory"),
    # What each boot replayed and how the one before it ended (RC's record, built).
    Slot("boots.json", "src.monitoring.boots:diagnostics_member", "RC", 30_720, "sessions"),
    # WAL's damage record (built), then the owner's record not built yet, listed as ``not-in-build`` until its module exists.
    Slot("database-damage.json", "src.database.damage:diagnostics_member", "WAL", 40_000, "database"),
    # WAL's events behind the instant (built): holds of the write gate of 30 s or more, guard engagements, every checkpoint, each opening of
    # the store with its init_db slowest steps, the pool's checkout timeouts and the last ten volume backups, restores and verifications
    # (how each ended, never a path or a message), each kind with its total and what it dropped.
    Slot("storage-events.json", "src.monitoring.storage_events:diagnostics_member", "WAL", 125_000, "database"),
    Slot("keyword-pipeline.json", "src.analytics.keyword_pipeline:diagnostics_member", "keyword", 60_000, "keywords"),
)

#: The most the slot members can add together, in raw JSON. A cap on the budgets (their sum is 595,720 at
#: this head), not a size of any zip: at the first measure's 4.6 to 1 it is about 130 KB zipped of a part
#: of 4,000,000 bytes, which is what it protects (room for the members that are not slots).
TOTAL_BUDGET_BYTES = 600_000

#: THE ROOM THE BUDGETS MUST LEAVE (R119: one file, or parts, each under 4,000,000 bytes), as three
#: figures a test adds to the budgets, worst case (every slot and every new member incompressible, so
#: its zipped size is its raw size, which is never true and is the safe side of a pin):
#: ``LARGEST_ZIP_MEASURED_BYTES``: the largest of the 17 builds the crash read measured (the Lenovo
#: build, 632 KB zipped; 629 KB by the crash read's own count): every member that existed then, a
#: MEASUREMENT;
#: ``OTHER_NEW_MEMBERS_BYTES``: the plan's section-4 budgets of the new members that are not slots
#: (machine 20, selftests 4, storage 120, contention 200, session-forensics, release-run 150,
#: wiki-lane-history 300 KB): an ESTIMATE, which the plan says it is, and it is the figure to replace
#: when those members are measured. The session-forensics part was +125 KB in the plan and is now the crash trace
#: export's stated worst case after its cut grew from 60 lines to 400/400/120 and each line was cut to 202 bytes as
#: written (206 with the JSON around it): the earlier ends (400 + 9 x 120) = 1,480 lines x 206 = 304,880 bytes, about
#: 10,000 of framing, and the previous session's trace 400 lines x 206 = 82,400 bytes, together 397,280, bounded at
#: 400,000 and counted whole as the member's increment (the 60 lines it replaces are already inside the measured figure
#: below, so this is the safe side; the export's own measure on the nastiest text is 259,137 to 289,001 bytes for the
#: earlier ends). The sum is 919,000 - 125,000 + 400,000 = 1,194,000;
#: ``HEADROOM_AT_LEAST_BYTES``: what the test requires to stay free of a part after the two above and
#: the sum of the budgets, and what a budget raised carelessly would eat. At this head the sum is
#: 595,720 with all seven rows and the free room 1,512,744 bytes (12,744 over the 1,500,000 floor), so a row can grow by that much before
#: the pin fails (and the failure is a reason to measure again, never to raise the pin).
LARGEST_ZIP_MEASURED_BYTES = 632_000
OTHER_NEW_MEMBERS_BYTES = 1_194_000
HEADROOM_AT_LEAST_BYTES = 1_500_000


def split_target(target: str) -> tuple[str, str]:
    module, _, function = target.partition(":")
    return module, function


def module_in_build(slot: Slot) -> bool:
    """Whether the slot's module can be imported in this build, decided without running it."""
    try:
        return importlib.util.find_spec(split_target(slot.target)[0]) is not None
    except (ImportError, ValueError):
        return False


def resolve(slot: Slot) -> Callable[..., Any]:
    """The producer itself. Raises when the module is here and the function is not: that is a mistake of
    the table or of the owner, and it is never reported as an absence."""
    module, function = split_target(slot.target)
    fn = getattr(importlib.import_module(module), function, None)
    if not callable(fn):
        raise AttributeError(f"{slot.target}: the module is in this build but has no callable {function}")
    return fn


def thunk(slot: Slot) -> Callable[[], Any]:
    """The member's thunk: resolves and calls the producer at run time, so importing the table imports
    none of the owners' modules."""

    def run() -> Any:
        fn = resolve(slot)
        value = fn(max_bytes=slot.budget_bytes) if slot.takes_budget else fn(**slot.kwargs)
        # The net under every producer: whatever it caught and wrote into its answer reaches the zip with the
        # passphrases the process holds taken out (scrub first; the producer's own cuts came before, so it also
        # writes a class and a fixed label, never the engine's words). The net is the bundle's own
        # (``_scrubbed_member_value``, shared with ``selftests.json``): it round-trips the answer through the
        # member encoder first, so a leaf JSON cannot hold is the stated marker, not ``str(leaf)``. Imported here
        # because the bundle imports this module.
        from src.api.diagnostics.bundle import _scrubbed_member_value

        return _scrubbed_member_value(value)

    run.__name__ = "slot_" + slot.name.replace(".", "_").replace("-", "_")
    return run


def members() -> list[tuple[str, Callable[[], Any]]]:
    """``(name, thunk)`` for every slot whose module is in this build, in table order."""
    return [(s.name, thunk(s)) for s in SLOTS if module_in_build(s)]


def not_in_build() -> list[dict[str, Any]]:
    """The slots that write no file because their module is not here yet, for the manifest."""
    return [
        {"file": s.name, "owner": s.owner, "target": s.target, "state": "not-in-build"}
        for s in SLOTS
        if not module_in_build(s)
    ]


def in_build(name: str) -> bool:
    """Whether the slot named ``name`` writes a member in this build (the bundle's pointers name a member only
    when it is one)."""
    return any(s.name == name and module_in_build(s) for s in SLOTS)


def budget_of(name: str) -> int | None:
    for s in SLOTS:
        if s.name == name:
            return s.budget_bytes
    return None


def area_of(name: str) -> str:
    """The topical class of a member: the slot's own, else the plan's table, else ``unclassified``
    (which a test refuses, so a member added without an area fails in CI and never in a reader's
    archive)."""
    for s in SLOTS:
        if s.name == name:
            return s.area
    from src.api import diagnostics_plan as plan

    return plan.MEMBER_AREAS.get(name, plan.UNCLASSIFIED_AREA)
