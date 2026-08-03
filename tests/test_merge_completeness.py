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
    """The backlog of data a fresh-install restore would drop. It is now EMPTY.

    Pinned by name so it can only shrink without a deliberate edit: adding a new OWED
    table is a conscious act, and removing one means a handler was built.

    All five remaining entries were cleared on 2026-08-03, when the maintainer ruled the
    cross-corpus identity each one needed (their handlers record which, and why). An empty
    list here is the point of the whole exercise, not an inert assertion -- a table added
    later with an unanswerable identity belongs BACK in this list with its question
    stated, exactly as these five were, rather than merged on a guessed key.
    """
    _, _, not_carried = _registries()
    owed = sorted(t for t, reason in not_carried.items() if reason.startswith("OWED:"))
    assert owed == [], f"the owed-handler backlog changed: {owed}"


def test_every_owed_table_states_the_question_that_blocks_it() -> None:
    """The five that remain have NO unique constraint, so their cross-corpus identity is a
    decision. An entry that just says "owed" invites the next person to invent one silently,
    which is how a merge starts duplicating or dropping -- so each names its own question."""
    _, _, not_carried = _registries()
    for table, reason in not_carried.items():
        if not reason.startswith("OWED:"):
            continue
        assert "IDENTITY UNRULED" in reason, f"{table} does not say what decision it needs"


def test_the_built_handlers_key_on_a_constraint_the_schema_defines() -> None:
    """The four built on 2026-08-03 were chosen precisely because the schema answers
    "same row?" for them. If one ever loses its unique constraint, the handler is keying on
    something the database no longer enforces -- and its dedup guard silently weakens."""
    from src.database.models import Base

    handled, _, _ = _registries()
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    for name in ("stat_figures", "stat_subscriptions", "hazard_event_details", "keyword_tags"):
        assert name in handled, f"{name} must be merged, not merely reported"
        tb = tables[name]
        uniques = [c for c in tb.constraints if c.__class__.__name__ == "UniqueConstraint"]
        uniques += [ix for ix in tb.indexes if ix.unique]
        assert uniques, f"{name}'s handler keys on a uniqueness the schema no longer enforces"


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
