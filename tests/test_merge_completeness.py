"""Every table must be TRIAGED for the additive restore-merge -- none may fall through.

WHY THIS EXISTS. A table in neither ``_MERGE_HANDLED`` nor ``_MERGE_IGNORED`` lands in
``_unmerged_tables``: counted in the restore report, copied by nothing. It reads as
intentional, and it is invisible on the only restore anyone routinely runs -- a
self-restore, where every row is already present and shows up as a "duplicate". The
2026-07-24 ``source_qualification_attempts`` bug was exactly this shape, and its recorded
lesson asked for "a completeness check that a new table must join one set or the other".
That check was never built. The P0 validation on the operator's 16.5 GB / 794k-article
corpus (2026-08-03) is what it cost: FOURTEEN tables in that middle state, four of them
carrying data no re-index can rebuild.

The operator's report listed only NINE, because ``_unmerged_tables`` skips empty tables --
so the field evidence UNDER-STATES the gap, and would under-state it differently on a
corpus that had used watches or the AI layer. A registry cannot be empty-dependent, which
is the second reason this check reads the SCHEMA rather than any particular corpus.

This guard changes no merge behaviour. It only makes the debt nameable, so a newly added
table cannot join it silently.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import pytest

pytest.importorskip("sqlalchemy")


def _registries():
    from src.backup.merge import _MERGE_HANDLED, _MERGE_IGNORED, _MERGE_NOT_CARRIED

    return _MERGE_HANDLED, _MERGE_IGNORED, _MERGE_NOT_CARRIED


def _mapped_tables() -> set[str]:
    from src.database.models import Base

    return {t.name for t in Base.metadata.sorted_tables}


def test_every_mapped_table_is_triaged_into_exactly_one_registry() -> None:
    """The completeness check itself: a NEW table must be classified deliberately.

    Failing here is not a bug in the test -- it means a table was added without deciding
    whether a restore must carry it. Put it in ``_MERGE_HANDLED`` (a handler copies it),
    ``_MERGE_IGNORED`` (a restore must NOT carry it, with the reason), or
    ``_MERGE_NOT_CARRIED`` (owed a handler, with the reason).
    """
    handled, ignored, not_carried = _registries()
    tables = _mapped_tables()

    untriaged = sorted(t for t in tables if t not in handled and t not in ignored and t not in not_carried)
    assert not untriaged, (
        "these tables are in NO merge registry, so a restore silently neither copies nor "
        f"declares them: {untriaged}. Classify each one deliberately."
    )


def test_no_table_is_claimed_by_two_registries() -> None:
    """Overlap would make the report's own account of a table ambiguous."""
    handled, ignored, not_carried = _registries()
    for a, b, an, bn in (
        (handled, ignored, "handled", "ignored"),
        (handled, set(not_carried), "handled", "not-carried"),
        (ignored, set(not_carried), "ignored", "not-carried"),
    ):
        overlap = sorted(a & b)
        assert not overlap, f"{overlap} is in both {an} and {bn}"


def test_every_not_carried_entry_states_a_reason() -> None:
    """A backlog entry without a reason is indistinguishable from an oversight -- which is
    the whole failure mode this registry exists to end."""
    _, _, not_carried = _registries()
    for table, reason in not_carried.items():
        assert reason.strip(), f"{table} has no reason"
        assert len(reason) > 15, f"{table}'s reason is too thin to act on: {reason!r}"


def test_the_owed_handlers_are_named_and_do_not_grow_silently() -> None:
    """The four kinds of data a fresh-install restore would drop today.

    Pinned by name so the backlog can only SHRINK without a deliberate edit: adding a new
    OWED table here is a conscious act, and removing one means a handler was built.
    """
    _, _, not_carried = _registries()
    owed = sorted(t for t, reason in not_carried.items() if reason.startswith("OWED:"))
    assert owed == [
        "ai_custom_prompt",
        "ai_keyword",
        "hazard_event_details",
        "keyword_tags",
        "law_revision_summaries",
        "stat_figures",
        "stat_subscriptions",
        "watch_matches",
        "watches",
    ], f"the owed-handler backlog changed: {owed}"


def test_the_registries_only_name_tables_that_exist() -> None:
    """A stale entry for a renamed or dropped table would quietly stop guarding anything."""
    handled, _, not_carried = _registries()
    tables = _mapped_tables()
    # _MERGE_IGNORED legitimately names non-model tables (alembic_version, FTS internals),
    # so it is exempt; the other two must refer to real mapped tables.
    for name, reg in (("_MERGE_HANDLED", handled), ("_MERGE_NOT_CARRIED", set(not_carried))):
        stale = sorted(t for t in reg if t not in tables)
        # Historical aliases are tolerated in _MERGE_HANDLED (older corpora carry them).
        if name == "_MERGE_NOT_CARRIED":
            assert not stale, f"{name} names tables that no longer exist: {stale}"
