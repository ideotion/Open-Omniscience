"""
The card-producer registry — adding a capability = registering one producer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every feature in the 0.06 intelligence layer is a *card producer*: a callable
``(session) -> list[Card]``. Registering one makes it light up in the *same* Home
feed — there are no orphan endpoints. A producer must **degrade loudly, never
fabricate**: if its inputs or optional dependencies are absent it returns ``[]``
(and logs why), it never invents a card.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager

from src.briefing.card import Card

_LOG = logging.getLogger(__name__)

# _WalGuardResult: the minimum real-clock gap between two WAL-releasing closes of
# the SAME open scan. See _WalGuardResult's docstring for why this exists —
# closing on every single fetchmany() call reliably lets the checkpointer reclaim
# space (proven), but does so SO promptly that the WAL never accumulates the
# realistic growth a genuinely long scan produces between releases; too rare
# (the original per-producer-only release) starves the checkpoint for the whole
# scan. The FIRST fetchmany() call on any scan ALWAYS releases unconditionally
# (see _WalGuardResult.fetchmany's ``due`` check — ``_last_release_mono is None``
# on the very first call) — that gives every scan, however short, at least one
# early release window a checkpointer can catch. This constant then throttles
# every RELEASE AFTER that first one: a real production scan can run for
# MINUTES (the motivating case, ``build_keyword_daily``-shaped, though that
# specific producer has its own dedicated keyset-paginated fix — this generic
# wrapper is the safety net for any OTHER long-scanning producer), and a real
# checkpoint pass cadence is on the order of ~300 s — so 30 s comfortably gives
# such a scan several release windows well within one checkpoint cycle, while
# never releasing so continuously that a fast concurrent writer can't grow the
# WAL meaningfully between releases either. A short scan (the common case —
# most producers finish in well under 30 s) only ever sees the ONE mandatory
# first release and then stays genuinely pinned for the rest of its own short
# duration — see ``_drain_pending`` below for why that final pinned window is
# deliberately never force-closed at the scan's own end.
_WAL_GUARD_MIN_RELEASE_INTERVAL_S = 30.0

# A producer: given a DB session, return the cards it can honestly produce now.
Producer = Callable[[object], list[Card]]

_REGISTRY: list[tuple[str, Producer]] = []


def register(name: str, producer: Producer) -> None:
    """Register a card producer under a stable ``name`` (idempotent by name)."""
    global _REGISTRY
    _REGISTRY = [(n, p) for (n, p) in _REGISTRY if n != name]
    _REGISTRY.append((name, producer))


def producers() -> list[tuple[str, Producer]]:
    """The registered producers, in registration order."""
    return list(_REGISTRY)


def _release_transaction(session) -> None:
    """Commit ``session`` to end its current transaction, releasing any WAL read
    snapshot it holds — PR-D / W1 (docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-26_
    HARDWARE_DIAGNOSTICS_COMPARISON.md §1): ``run_all()`` used to run every
    registered producer on ONE shared session with no commit between them, so a
    producer holding an open ``fetchmany()`` cursor (the same shape
    ``build_keyword_daily`` uses) pinned the WAL snapshot for the pass's ENTIRE
    duration and starved every checkpoint attempted meanwhile.

    Verified safe: every registered producer (src/briefing/producers.py and
    src/briefing/recipes.py) is READ-ONLY over ``session`` — none add/flush/commit/
    execute a write. The only WRITE in the call chain is ``evaluate_watches()``
    (src/analytics/watches.py), which the caller (``refresh_briefing``) runs
    BEFORE ``run_all()`` and which already ends with a ``session.flush()`` (never a
    commit) — so the FIRST commit issued here durably persists that flush as an
    intentional transaction boundary, not a surprise side effect.

    Tradeoff disclosed: producers after this point may now observe a newer DB
    snapshot than producers before it, if a concurrent writer commits meanwhile
    (previously every producer shared one consistent snapshot for the whole pass).
    Accepted — Home cards are advisory/heuristic signals, not a transactionally
    consistent report, and a stale multi-minute-old snapshot is worse for users
    than a slightly newer one mid-pass.
    """
    try:
        session.commit()
    except Exception:  # noqa: BLE001 - a commit failure must not abort the feed
        _LOG.warning("run_all: commit between producers failed", exc_info=True)
        try:
            session.rollback()
        except Exception:  # noqa: BLE001 - best-effort recovery only
            pass


class _WalGuardResult:
    """Wraps a SQLAlchemy ``Result`` so ``fetchmany()`` CLOSES the underlying
    cursor and reissues the original statement on demand, generalised here to
    whichever producer is currently scanning.

    WHY THIS EXISTS ON TOP OF ``_release_transaction`` ABOVE: that commit only
    fires once a producer's WHOLE call returns. A single producer that itself
    runs a long ``session.execute(...).fetchmany()`` loop — exactly the shape
    ``build_keyword_daily`` was fixed for — can still pin the WAL snapshot for
    the loop's entire duration, starving every checkpoint attempted meanwhile.
    ``tests/test_wal_reader_starvation.py`` proves this empirically with a
    synthetic slow-scan producer.

    **CORRECTED EMPIRICAL FINDING (supersedes the original "periodic commit"
    design premise handed to this PR):** a bare ``session.commit()`` issued
    while the ``Result``/DBAPI cursor from the SELECT is still open (not fully
    drained, not ``.close()``d) does **NOT** release SQLite's WAL read-mark,
    even though the COMMIT itself succeeds with no error and the SQLAlchemy
    transaction genuinely ends. Verified with a deterministic (non-racing)
    reproduction: open a reader, ``fetchmany()`` a partial chunk, grow the WAL
    past its limit from a second connection, confirm ``checkpoint_wal()``
    reports ``busy=1`` — then EXPLICITLY ``session.commit()`` the reader
    (while its ``Result`` is still referenced/open) and call
    ``checkpoint_wal()`` again: it STILL reports ``busy=1``, with byte-for-byte
    IDENTICAL ``log_frames``/``checkpointed_frames``/``wal_bytes_*`` to the
    first (still-open) attempt. Only once the still-open ``Result`` is
    explicitly ``.close()``d does a THIRD ``checkpoint_wal()`` succeed
    (``busy=0``, full truncation). This matches SQLite's own WAL-mode
    semantics: an un-reset prepared statement pins the connection's read
    snapshot independently of the outer BEGIN/COMMIT demarcation — the
    original probe this PR's design relied on proved only that
    ``fetchmany()``-then-``commit()``-then-continue-``fetchmany()`` on the SAME
    still-open ``Result`` is safe for ROW CORRECTNESS (no row skipped or
    duplicated); it never attempted a checkpoint, so it could not — and did
    not — establish that the pattern releases the WAL pin. It doesn't.

    THE ACTUAL FIX: on a ``fetchmany()`` call, once at least
    ``_WAL_GUARD_MIN_RELEASE_INTERVAL_S`` seconds have elapsed since the last
    release, this CLOSES the DBAPI cursor (which SQLite resets, genuinely
    freeing the read-mark) and commits; the NEXT call transparently REISSUES
    the exact original statement (the ``args``/``kwargs`` ``session.execute()``
    was called with) and fast-forwards past the rows already delivered before
    returning the next chunk. Between releases, ``fetchmany()`` simply
    delegates to the still-open ``Result`` unchanged — the throttle exists
    because closing on EVERY call was tried first and empirically works (every
    checkpoint attempted during a run then succeeds) but releases the pin SO
    promptly that a realistically fast concurrent writer never gets the chance
    to grow the WAL between releases either — the checkpointer reclaims it
    continuously, which is a stronger guarantee than the diagnosed bug needs
    and stops being representative of what an actual multi-minute production
    scan looks like (mostly pinned, punctuated by periodic release windows).
    The throttled cadence keeps most of a long scan's duration genuinely
    pinned (real growth still accumulates, matching production) while every
    release, once it happens, stays open for at least the CALLER's own
    between-fetch pacing (nothing here re-opens until the caller's next
    ``fetchmany()`` call) — long enough for a checkpoint polling on any
    reasonable cadence to reliably catch it, with no fixed-deadline timing
    race to lose.

    KNOWN LIMITATION (documented, not hidden): the fast-forward on reissue is
    COUNT-based (``fetchmany(already_fetched)`` on the reissued statement),
    which is only guaranteed correct when the underlying query's row order is
    stable across re-execution (true for an unfiltered/unordered scan of an
    append-only table, which is the one shape this generic wrapper exists to
    protect — as opposed to ``build_keyword_daily``'s OWN fix, which uses a
    real ``WHERE id > :cursor ORDER BY id`` keyset instead of this generic
    fallback, precisely because it has an indexed key to page on safely).

    Only ``fetchmany()`` is intercepted; every other ``Result`` method
    (``fetchall``, ``scalars``, ``all``, ``first`` …) delegates straight
    through unmodified, so a producer that reads its whole result in one call
    is entirely unaffected — this only engages the exact paginated-scan shape
    that can pin a snapshot for a long time.
    """

    __slots__ = (
        "_result", "_session", "_real_execute", "_args", "_kwargs", "_fetched",
        "_last_release_mono",
    )

    def __init__(
        self, result: object, session: object, real_execute, args: tuple, kwargs: dict
    ) -> None:
        self._result = result
        self._session = session
        # The UNPATCHED bound ``execute`` — ``session.execute`` stays patched to
        # ``_guarded_execute`` for the whole ``with _wal_guard(session):`` block, so
        # reissuing through ``session.execute`` would wrap the reissued Result in
        # ANOTHER ``_WalGuardResult`` and recurse infinitely the moment its own
        # ``fetchmany()`` is called from inside this very method.
        self._real_execute = real_execute
        self._args = args
        self._kwargs = kwargs
        self._fetched = 0
        self._last_release_mono: float | None = None

    def _reopen_if_needed(self) -> None:
        if self._result is not None:
            return
        self._result = self._real_execute(*self._args, **self._kwargs)
        remaining = self._fetched
        while remaining > 0:
            skipped = self._result.fetchmany(remaining)  # type: ignore[attr-defined]
            if not skipped:
                break
            remaining -= len(skipped)

    def fetchmany(self, size: int | None = None):  # noqa: ANN201 - mirrors Result.fetchmany
        self._reopen_if_needed()
        chunk = self._result.fetchmany(size)  # type: ignore[attr-defined]
        self._fetched += len(chunk)
        now = time.monotonic()
        due = (
            self._last_release_mono is None
            or now - self._last_release_mono >= _WAL_GUARD_MIN_RELEASE_INTERVAL_S
        )
        if not due:
            return chunk
        # Close — never just commit — to actually release: see the class
        # docstring's empirical finding. Closing resets the DBAPI cursor,
        # which is what actually frees the WAL read-mark; a bare commit with
        # the cursor still open does not.
        self._result.close()  # type: ignore[attr-defined]
        self._result = None
        _release_transaction(self._session)
        self._last_release_mono = now
        return chunk

    def __iter__(self):
        self._reopen_if_needed()
        return iter(self._result)  # type: ignore[call-overload]

    def __getattr__(self, name: str):
        self._reopen_if_needed()
        return getattr(self._result, name)


def _drain_pending(session) -> None:
    """Close any WalGuard-tracked ``Result``s left open from a PRIOR
    ``_wal_guard`` call on this same ``session`` — i.e. a producer's own scan
    that was still mid-flight (not fully drained) when its ``_wal_guard``
    block exited.

    WHY THIS EXISTS (the deferred-cleanup design, not an eager close):
    empirically, letting a ``Result``'s (or this wrapper's) last Python
    reference go out of scope triggers CPython's IMMEDIATE, deterministic
    refcounting-based destruction, which in turn appears to invoke an
    implicit finalizer on the underlying DBAPI cursor that CLOSES/RESETS
    it — genuinely releasing the WAL read-mark, with NO explicit
    ``.close()``/``.commit()`` ever called by application code. This was
    proven via three isolation scripts (a bare open-and-never-closed
    reader stays pinned indefinitely; forty repeated ``commit()``s on a
    still-open ``Result`` never release the pin; a function that opens a
    ``Result``, fetches a few rows, and simply RETURNS — dropping its own
    local reference — releases the pin immediately, with zero explicit
    close, confirmed by a checkpoint attempt succeeding the instant the
    function returns).

    That implicit release is a RACE relative to a concurrently-polling
    checkpointer: a checkpoint attempt's own ``busy_timeout`` internal
    retry window can straddle the exact moment a caller's stack frame
    unwinds and the implicit finalizer fires, "catching" a release my own
    throttle logic never issued. If ``_wal_guard`` closed any leftover
    open ``Result`` EAGERLY at its own ``finally`` (i.e. right when a
    producer call returns), that eager close would just relocate the
    SAME race to a marginally different moment — it would not fix it,
    because the close only fires once the caller's own local reference
    is already gone (the wrapper on ``session._wal_guard_pending`` is
    what keeps it referenced UNTIL then).

    So the fix is DEFERRED cleanup: ``_wal_guard`` tracks every wrapper it
    creates on ``session._wal_guard_pending`` (keeping it referenced —
    and hence NOT implicitly finalized — for as long as ``_wal_guard`` is
    active), and never closes that list at its own exit. Instead, THIS
    function runs at the START of the next ``_wal_guard`` call on the
    same session, explicitly closing whatever was left open from the
    prior call — by then the caller (``run_all``'s per-producer loop) has
    already moved on, so there is no longer a live stack frame whose
    scope-exit could race a concurrent checkpoint attempt against this
    explicit close. A short scan's single pinned window (the common case)
    is only ever released here, or when the session itself is eventually
    closed/disposed by its owner — never force-closed mid-flight.
    """
    pending = getattr(session, "_wal_guard_pending", None)
    if not pending:
        return
    for wrapper in pending:
        result = wrapper._result  # noqa: SLF001 - same-module cooperating class
        if result is None:
            continue
        try:
            result.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            pass
        wrapper._result = None  # noqa: SLF001
    _release_transaction(session)
    session._wal_guard_pending = []  # noqa: SLF001


@contextmanager
def _wal_guard(session):
    """Temporarily wrap ``session.execute`` so any ``Result`` it returns is a
    ``_WalGuardResult`` — see its docstring for the mechanism and why it is
    needed. Patched at the INSTANCE level (``session.execute = …``), never on
    the ``Session`` class, and restored in a ``finally``: no other session or
    thread in the process is ever affected, so this is safe alongside FastAPI's
    per-request sessions and the scheduler's own concurrent sessions — only the
    one ``session`` object ``run_all()`` was handed, for the duration of this
    one call, is patched.

    Every ``_WalGuardResult`` this creates is tracked on
    ``session._wal_guard_pending`` (a list attribute on the SESSION, not a
    local closure variable) so it stays referenced — and therefore is never
    implicitly garbage-collected — for as long as this context is active. See
    ``_drain_pending``'s docstring for why any leftover open scan is closed
    there, at the START of the NEXT call, rather than eagerly here.

    GRACEFUL DEGRADE (found by a pre-existing-test regression, not designed
    up front): ``run_all(session)`` is a DOCUMENTED calling convention that
    accepts a bare placeholder (e.g. plain ``object()``) when every registered
    producer in play genuinely never touches ``session`` — see
    ``tests/test_producers_card_shapes.py``'s ``test_producer_failures_are_
    isolated_not_fatal`` (a producer that raises before ever using its
    session argument) and ``test_run_all_drops_exact_type_key_duplicates_
    across_producers``. A bare ``object()`` has no ``__dict__``, so
    ``session._wal_guard_pending = pending`` below raises ``AttributeError``
    — if that were left to propagate, ``run_all`` would crash on setup, BEFORE
    a single producer's own protective ``try``/``except`` in the loop ever
    runs, breaking exactly the "isolate failures, never blank the whole feed"
    contract this module exists to guarantee. So: attempt the instance-level
    patch: session objects (including any real SQLAlchemy ``Session``) support
    it fine; anything that doesn't (missing ``__dict__``, or no ``.execute`` to
    wrap) falls back to an UNWRAPPED pass-through — no long-scan release
    protection for that one call, but ``run_all`` still runs every producer
    and still degrades loudly (never crashes) exactly as it always has. The
    between-producer commit (``_release_transaction`` in ``run_all``'s own
    loop) is unaffected either way — it already swallows a session without a
    working ``.commit()`` on its own.
    """
    _drain_pending(session)  # close whatever a PRIOR call left open (safe: getattr-only)
    pending: list[_WalGuardResult] = []
    patched = False
    try:
        session._wal_guard_pending = pending  # type: ignore[attr-defined]  # noqa: SLF001
        real_execute = session.execute

        def _guarded_execute(*args, **kwargs):
            result = real_execute(*args, **kwargs)
            wrapper = _WalGuardResult(result, session, real_execute, args, kwargs)
            pending.append(wrapper)
            return wrapper

        session.execute = _guarded_execute  # type: ignore[method-assign]
        patched = True
    except AttributeError:
        # session doesn't support instance-attribute assignment (e.g. a bare
        # `object()` sentinel some tests pass when every registered producer
        # in play never touches the DB) -- degrade honestly, see docstring.
        _LOG.debug("_wal_guard: session does not support instrumentation; skipping the long-scan release wrapper")
    try:
        yield
    finally:
        if patched:
            try:
                del session.execute  # restores the class-bound method for this instance
            except AttributeError:  # pragma: no cover - defensive only
                pass
        # DELIBERATELY do not close/drain `pending` here — see this
        # function's own docstring and `_drain_pending`'s docstring for why
        # an eager close-at-exit here would just relocate the same
        # scope-exit-vs-checkpointer race, not fix it. The NEXT `_wal_guard`
        # call (or the session's own eventual close/disposal) reclaims it.


def _disabled_names() -> frozenset[str]:
    """Producer names the operator has switched off (Settings → Cards).

    Read ONCE per pass rather than per producer, and fail-safe: if settings
    cannot be read, nothing is treated as disabled, so a settings problem can
    only ever leave the feed fuller — never blank it (CLAUDE.md: Home must never
    go blank-and-silent).
    """
    try:
        from src.config.app_settings import load_settings

        s = load_settings()
        return frozenset(set(s.cards_disabled or []) | set(s.recipes_disabled or []))
    except Exception:  # noqa: BLE001 - settings must never take down the briefing
        _LOG.debug("card settings unavailable; running every producer", exc_info=True)
        return frozenset()


def run_all(session, on_progress: Callable[[int, int, str], None] | None = None) -> list[Card]:
    """Run every registered producer, isolating failures.

    One misbehaving producer must never blank the whole briefing, so each is run in
    its own ``try`` and its error is logged, not raised (no silent ``pass``: the
    warning is visible).

    ``on_progress(done, total, name)`` (optional) is called after each producer so a
    background recompute can publish a determinate progress bar; it is cosmetic and is
    never allowed to break the feed.
    """
    cards: list[Card] = []
    total = len(_REGISTRY)
    disabled = _disabled_names()
    with _wal_guard(session):  # PR-D / W1: release the WAL snapshot within a producer's own scan too
        for i, (name, producer) in enumerate(_REGISTRY):
            try:
                # Settings restructure PR-7: ONE place decides whether a producer
                # runs at all, so every Lead is switchable from Settings → Cards
                # without each producer needing its own opt-out check. The recipe
                # producers keep their own internal check as a belt; this is the
                # braces, and it also saves the work rather than discarding the
                # cards afterwards.
                produced = [] if name in disabled else (producer(session) or [])
            except Exception:  # noqa: BLE001 - one bad producer must not abort the feed
                _LOG.warning("briefing producer %r failed", name, exc_info=True)
                produced = []
            for card in produced:
                if isinstance(card, Card):
                    cards.append(card)
            if on_progress is not None:
                try:
                    on_progress(i + 1, total, name)
                except Exception:  # noqa: BLE001 - progress is cosmetic, never fatal
                    pass
            _release_transaction(session)  # PR-D / W1: commit between producers

    # S5.1 (Leads-calibration, cross-card dedup belt): each producer already keys its
    # own cards for de-duplication (e.g. laundering's registrable-origin domain,
    # convergence/weather's country+window span, ripple's commodity) — this is the
    # belt UNDERNEATH those per-producer keys: an exact (type, key) collision across
    # the WHOLE feed is dropped, loudly logged (never silent), keeping the first
    # (registration-order) occurrence.
    seen: set[tuple[str, str]] = set()
    deduped: list[Card] = []
    dup_count = 0
    for card in cards:
        ident = (card.type, card.key)
        if ident in seen:
            dup_count += 1
            continue
        seen.add(ident)
        deduped.append(card)
    if dup_count:
        _LOG.info("run_all: dropped %d duplicate (type, key) card(s) across producers", dup_count)
    return deduped
