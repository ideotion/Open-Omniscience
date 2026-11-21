"""One encrypted database file per lane, opened ONLY through the one keyed path.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULINGS THIS MODULE IS. Q719 = a and Q1004 = a: ``wiki.db``, ``law.db`` and
``osm.db`` sit BESIDE ``corpus.db``, linked by ids, each an opt-in backup member,
"so a 100 GB lane never bloats the corpus file or its encryption rekey". Q720 = a
and Q1005 = a: "encrypted with the same passphrase, same threat model, no
exceptions" — because the SELECTION (which pages, which countries) reveals the
operator's interests even though the data itself is public.

HOW "THE SAME" IS GUARANTEED RATHER THAN INTENDED. Every lane connection is built
by ``src.database.connect.connect``, the app's ONE factory — the same function the
corpus engine's creator calls, with a different path. That is the whole mechanism,
and it is why there is no key handling in this file: the passphrase is the process
passphrase, the driver choice is the file header's, the fresh-file page size is
DB-10 §1b's, and a wrong key raises ``WrongPassphraseError`` here exactly as it
does for the corpus. A second key path would be a second thing to get wrong.

NO PER-LANE PLAINTEXT — AND THAT TOOK A GUARD, not just an omission. This module
passes neither ``key=`` nor ``create_encrypted=``, so there is no per-lane OVERRIDE;
that much was always true. But it is not what the sentence above used to claim. The
factory's fresh-file precedence puts the app-wide ``OO_DB_PLAINTEXT`` opt-out AHEAD of
the process passphrase, so with that variable set and a real passphrase in hand — the
state of an ordinary unlocked, already-encrypted corpus on a machine where the flag is
also exported — ``create_lane`` produced a PLAINTEXT lane beside it. Measured, not
feared. An already-encrypted corpus is immune to the same rule (an existing encrypted
file never consults the flag), so the divergence is lane-shaped: the corpus was created
before the flag mattered and the lane is created after.

``create_lane`` therefore refuses outright to make a plaintext lane while the corpus on
disk is encrypted, naming the variable. Two refusals, not one:
  * the store is LOCKED (no passphrase, no plaintext opt-out) -> ``DatabaseLockedError``,
    rather than quietly waiting for an unlock that may not come; an absent lane is an
    honest state and a half-made one is not;
  * the corpus is ENCRYPTED and the plaintext opt-out is on -> refuse, because the one
    thing this module may never do is put an operator's tracked-source selection in the
    clear beside a corpus they were told is protected.

AN ABSENT LANE IS ABSENT, NEVER ZERO. ``connect()`` CREATES a missing file, which
makes every "does this lane exist?" question a hazard: asking it through the
factory would answer by creating the thing. So existence is a ``stat``, size is
``None`` when the file is not there, and nothing in this module opens a lane it was
not asked to open. This is the brief's S2 clause ("an absent lane file reported
ABSENT, never a zero-byte lane") enforced at the only layer that can enforce it.

CROSS-FILE LINKS. SQLite has no cross-database foreign keys, so a revision's
``article_id`` names a row in ``corpus.db`` with nothing enforcing it. See
``src.versioned.integrity`` for the check that stands in for the constraint, and
``models.py``'s docstring for why it can only ever be a point-in-time reading.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, Table, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.monitoring.secret_scrub import log_failure
from src.versioned.lanes import LaneSpec, lane

_LOG = logging.getLogger("versioned.store")

#: Engines are per-process and per-lane. Built lazily — a lane nobody touches costs
#: nothing, and a boot must never open a lane file just to have one.
#:
#: KEYED ON ``(kind, path)``, NOT ON ``kind``. ``lane_path`` resolves through
#: ``data_dir()``, which reads ``OO_DATA_DIR`` at CALL time — so a test (or an
#: operator moving their data folder) can change where a lane lives while a cached
#: engine still points at the old file. The recorded shape of this defect is "the
#: engine binds once per process, so a function-scoped fixture that re-points
#: OO_DATA_DIR gets the first store", and it fails SILENTLY: the second lane reads
#: and writes the first one's rows. Including the path in the key makes a moved
#: lane a cache miss instead.
_engines: dict[tuple[str, str], Engine] = {}
_factories: dict[tuple[str, str], sessionmaker] = {}
_lock = threading.Lock()

#: R702 part 2 (row 256): the lanes whose file is being switched for its rebuilt copy right now (``held_for_swap``). While a kind
#: is here no connection to its file is OPENED: the engine's creator waits for the switch to end (it lasts a moment: the log is
#: folded, a second name is given, the new file is moved in) and is refused by name after :data:`SWAP_WAIT_S`. A connection
#: opened in that moment would bind the old file's log names to the new file, or keep the old file's log open under a name the
#: new file then owns.
_swapping: dict[str, object] = {}  # kind -> the token of the hold that has it (released only by that hold: R161's shape)
#: The lock under ``_swap_cond``. Entered as ``with _swap_lock:``, never ``with _swap_lock:`` (R144: a Condition's own Python-level
#: ``__enter__``/``__exit__`` can leave the lock held when an interrupt lands in them).
_swap_lock = threading.RLock()
_swap_cond = threading.Condition(_swap_lock)
#: What each kind's engines have open on the lane file, kept per KIND (not per engine) so it survives an engine being disposed and
#: forgotten, all under ``_swap_cond``:
#:   * ``_opening``: creators that passed the not-switching check and have not yet handed a connection to the pool. Counted IN THE
#:     SAME LOCKED STEP as that check, so a hold that begins while an open is under way (the key derivation alone takes ~170 ms)
#:     sees it, and an open that has not passed the check yet waits for the hold to end;
#:   * ``_live``: every connection the pools hold, idle or handed out (the pool's ``connect`` event adds it, its ``close`` and
#:     ``close_detached`` events remove it);
#:   * ``_out``: the ones handed out right now (``checkout`` adds, ``checkin`` and a close remove). Sets of ids rather than
#:     counters, so an unpaired event (a ``checkin`` for a checkout that failed) can never take the figure below the truth.
_opening: dict[str, int] = {}
_live: dict[str, set[int]] = {}
_out: dict[str, set[int]] = {}
#: Moved by every disposal of a kind's engines (a hold, ``dispose_lane``). A connection made under an earlier generation is
#: CLOSED when it comes back (``checkin``) instead of going idle: its engine's pool was replaced while it was out, so it would
#: otherwise sit open in a pool nothing reaches any more, on the file a switch may have moved away.
_gen: dict[str, int] = {}
_GEN_KEY = "oo_lane_generation"


def _next_generation(kind: str) -> None:
    with _swap_lock:
        _gen[kind] = _gen.get(kind, 0) + 1
#: How long a connection waits for a lane's switch to end before it is refused (seconds). Above the log fold's own retry budget
#: (``repair.FOLD_RETRY_S``, 30 s) with a margin, so a hold that ends in time is never seen as a refusal by a reader that waited.
SWAP_WAIT_S = 60.0
#: How long a hold waits for opens already under way to land and for connections handed out to come back (seconds), before it
#: refuses with :class:`LaneInUse`.
HOLD_SETTLE_S = 2.0


class LaneSwapping(RuntimeError):
    """The lane's file was being switched for its rebuilt copy (R702 part 2) for longer than a connection waits: nothing was
    opened, so nothing was read or saved. Fixed words; do it again."""


#: Fixed words for :class:`LaneSwapping` (keyed in every locale).
SWAPPING_WORDS = "this store's file was being switched for its rebuilt copy, so nothing was opened; do it again"


class LaneInUse(RuntimeError):
    """A connection to the lane was still open (or being opened) when its switch was to begin, so nothing was switched. ``count``
    says how many."""

    def __init__(self, count: int) -> None:
        super().__init__(f"{count} connection(s) to this store were still open")
        self.count = count


class LaneAlreadyHeld(RuntimeError):
    """A second hold of a lane that is already held for a switch (one rebuild runs at a time, so this is a guard, not a path)."""


#: The generation an open on this thread began under (read by the pool's ``connect`` event, which runs right after the creator on
#: the same thread): an open under way when a hold began is stale, wherever its connection lands.
_open_gen = threading.local()


def _begin_open(kind: str) -> None:
    """Called by a lane engine's creator before it opens the file: wait while this kind's file is being switched, then count the
    open as under way, in ONE locked step. After :data:`SWAP_WAIT_S` it is refused with :class:`LaneSwapping`."""
    with _swap_lock:
        if kind in _swapping and not _swap_cond.wait_for(lambda: kind not in _swapping, timeout=SWAP_WAIT_S):
            raise LaneSwapping(SWAPPING_WORDS)
        _opening[kind] = _opening.get(kind, 0) + 1
        _open_gen.value = _gen.get(kind, 0)


def _end_open(kind: str) -> None:
    with _swap_lock:
        _opening[kind] = max(0, _opening.get(kind, 0) - 1)
        _swap_cond.notify_all()


def _note(kind: str, conn_id: int, *, live: bool | None = None, out: bool | None = None) -> None:
    with _swap_lock:
        if live is not None:
            (_live.setdefault(kind, set()).add if live else _live.setdefault(kind, set()).discard)(conn_id)
        if out is not None:
            (_out.setdefault(kind, set()).add if out else _out.setdefault(kind, set()).discard)(conn_id)
        _swap_cond.notify_all()


def in_use(kind: str) -> int:
    """How many connections to this lane are handed out right now, or being opened (0 for a lane nobody opened). Idle connections
    in a pool are not counted: they hold nothing, and a hold closes them."""
    with _swap_lock:
        return len(_out.get(kind, ())) + _opening.get(kind, 0)


def _open_now(kind: str) -> int:
    """Every connection the pools have open on this lane, idle or handed out, plus the opens under way (call with ``_swap_cond``)."""
    return len(_live.get(kind, ())) + _opening.get(kind, 0)


def quiet(kind: str) -> bool:
    """Whether NOTHING of this process is open on the lane file, nor being opened. Read by the switch again right before it gives
    the old file its second name and moves the new one in."""
    with _swap_lock:
        return _open_now(kind) == 0


@contextmanager
def held_for_swap(kind: str) -> Iterator[None]:
    """Hold this lane's file still for a switch (R702 part 2). In one locked step the kind is marked as switching, so from then on
    no connection to it is opened (an opener waits, see :func:`_begin_open`) and every open already under way is counted. Every
    engine of the kind is then disposed (its idle connections closed; one handed out is closed when it comes back), and the hold waits up to
    :data:`HOLD_SETTLE_S` for the opens under way to land and the connections handed out to come back, disposing again as they do.
    If any is still open it is REFUSED with :class:`LaneInUse`: that connection would go on using the old file, and its log by a
    name the new file then owns. Not re-entrant (:class:`LaneAlreadyHeld`)."""
    token = object()
    try:
        with _swap_lock:
            if kind in _swapping:
                raise LaneAlreadyHeld("this store is already held for a switch")
            _swapping[kind] = token
            _gen[kind] = _gen.get(kind, 0) + 1
        with _lock:
            # KEPT in the cache, not forgotten: a connection opened through one of them (a caller already holding its factory)
            # then lands in a pool the next pass of the loop below, and the next hold, can still reach and close.
            engines = [_engines[k] for k in _keys_of(kind)]
        deadline = time.monotonic() + HOLD_SETTLE_S
        while True:
            for eng in engines:
                eng.dispose()  # a connection that came back (or finished opening) since the last pass is idle now: closed here
            with _swap_lock:
                left = _open_now(kind)
                if not left:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LaneInUse(left)
                _swap_cond.wait(timeout=min(0.05, remaining))
        yield
    finally:
        # Released by asking whose it is (R161): an interrupt anywhere above leaves no mark of THIS hold behind, and a refused
        # second hold never takes away the first one's.
        with _swap_lock:
            if _swapping.get(kind) is token:
                del _swapping[kind]
            _swap_cond.notify_all()


class PlaintextLaneRefused(RuntimeError):
    """A lane would have been created in the clear beside an encrypted corpus.

    Its own type rather than ``ValueError`` because a caller that wants to offer the
    operator a way out (unset the flag, or decrypt on purpose) has to be able to tell
    this from a locked store, which is a different situation with a different remedy.
    """


def _corpus_path() -> Path:
    from src.paths import data_dir

    return data_dir() / "open_omniscience.db"


def _corpus_is_encrypted() -> bool:
    """Is the corpus ciphertext ON DISK? A header read, never an inference.

    ``False`` when the corpus does not exist yet: a lane created before any corpus is
    not beside an encrypted one, and refusing then would block a fresh install.
    """
    from src.database.connect import is_encrypted_file

    return is_encrypted_file(_corpus_path()) is True


class LaneAbsentError(FileNotFoundError):
    """The lane has no database file, and the caller did not ask for one to be made.

    A ``FileNotFoundError`` subclass so ordinary path-shaped handling works, and a
    named type so a caller can tell "this lane has never run" from "the disk is
    broken" — which is precisely the distinction Settings -> Storage renders.
    """


def lane_path(kind: str) -> Path:
    """Where this lane's database file lives. Pure: creates nothing, opens nothing.

    ``data_dir()`` itself creates the DATA DIRECTORY (and chmods it 0700), which is
    the app's own convention and is not a lane side effect.
    """
    from src.paths import data_dir

    return data_dir() / lane(kind).filename


def lane_exists(kind: str) -> bool:
    """True when this lane's file is on disk. A ``stat``, never an open."""
    return lane_path(kind).is_file()


def lane_file_bytes(kind: str) -> int | None:
    """Bytes this lane occupies on disk, or ``None`` when the lane is ABSENT.

    ``None`` and ``0`` are different facts and this function refuses to merge them:
    a lane that has never run holds no bytes, and a lane file that exists and is
    empty is a different, reportable state. The figure INCLUDES the ``-wal`` and
    ``-shm`` sidecars when present, because that is what the operator's disk is
    actually holding — a size that omitted a multi-gigabyte WAL would understate
    the thing the budget surface exists to show.
    """
    p = lane_path(kind)
    if not p.is_file():
        return None
    total = 0
    for candidate in (p, p.with_name(p.name + "-wal"), p.with_name(p.name + "-shm")):
        try:
            total += candidate.stat().st_size
        except OSError:
            # A sidecar that vanished between the two calls is normal (a checkpoint
            # ran). The main file's own OSError is not, and it surfaces as a smaller
            # figure rather than an exception, because a storage panel must not 500.
            continue
    return total


def _build_engine(spec: LaneSpec, path: Path) -> Engine:
    """A SQLAlchemy engine over one lane file, keyed by the ONE factory.

    Deliberately NOT a copy of ``session.py``'s engine: the corpus pool is sized for
    up to ~50 concurrent collector workers, and a lane is written by one adapter at
    a time behind the same single-writer discipline. A small pool keeps a 100 GB
    lane from holding fifty SQLCipher page caches open beside the corpus's.
    """

    from src.database import file_identity

    def _open():
        from src.database.connect import connect

        # No ``key=``, no ``create_encrypted=``: the factory's own precedence is the
        # ruling (Q720/Q1005). Passing either here would be this module deciding a
        # lane's at-rest state, which is the one thing it must not do.
        return connect(str(path), check_same_thread=False, timeout=30)

    # Row 148: each connection carries the identity of the file it opened, so one that outlives an encryption swap of the lane
    # is dropped at checkout and refused at commit, never left saving into the replaced file (``file_identity``).
    _pinned = file_identity.pinned_creator(path, _open)

    def _creator():
        # R702 part 2: never opened while the file is switched for its rebuilt copy, and counted as under way from the same locked
        # step that checked it (``_begin_open``) until the pool's ``connect`` event below takes it over, or the open fails.
        _begin_open(spec.kind)
        try:
            return _pinned()
        except BaseException:
            _end_open(spec.kind)
            raise

    eng = create_engine(
        f"sqlite:///{path}",
        future=True,
        hide_parameters=True,  # as the corpus engine (src/database/session.py): an error names the statement, never its values
        creator=_creator,
        pool_size=2,
        max_overflow=4,
        pool_timeout=30,
    )

    @event.listens_for(eng, "connect")
    def _lane_opened(dbapi_connection, record) -> None:
        # The FIRST of this module's connect listeners: the open under way becomes a live connection. SQLAlchemy does NOT close a
        # connection whose later connect listener raised (no ``close`` event fires), so the one of ours that can fail
        # (``_lane_pragmas``: WAL on a locked file) closes it and forgets it itself. ``file_identity``'s stamp cannot raise (a
        # ``stat`` that fails is None). STATED LIMIT: a failure in the dialect's own connect handler, before this one, leaves the
        # open counted, which refuses this lane's later rebuilds until a restart (a refusal, never a loss).
        with _swap_lock:
            record.info[_GEN_KEY] = getattr(_open_gen, "value", _gen.get(spec.kind, 0))
        _note(spec.kind, id(dbapi_connection), live=True)
        _end_open(spec.kind)

    @event.listens_for(eng, "handle_error")
    def _lane_storage_guard_on_error(context) -> None:
        """A lane is written to the same drive as the corpus (one reached 100 GB): a write
        that fails for want of space must stop collection as the corpus engine's does.
        Observes only; the error still propagates unchanged."""
        try:
            from src.scheduler.storage_guard import on_engine_error

            on_engine_error(context)
        except Exception:  # noqa: BLE001 - an observer never replaces the real error
            pass

    # A failed statement whose DRIVER error is SQLITE_CORRUPT names THIS lane's file as damaged and
    # stops this lane's writers, never the corpus's (``database/damage.py``). Observes only.
    from src.database import damage

    damage.attach(eng, spec.kind)
    file_identity.attach(eng, path)

    # R702 part 2: what the lane's switch must know is open (``_live``, ``_out``). The checkout listener is registered AFTER
    # ``file_identity``'s own, so a connection it drops at checkout (one on a replaced file) is never counted as handed out.
    @event.listens_for(eng, "checkout")
    def _lane_checked_out(dbapi_connection, _record, _proxy) -> None:
        _note(spec.kind, id(dbapi_connection), out=True)

    @event.listens_for(eng, "checkin")
    def _lane_checked_in(dbapi_connection, record) -> None:
        if dbapi_connection is None:
            return
        _note(spec.kind, id(dbapi_connection), out=False)
        with _swap_lock:
            stale = record.info.get(_GEN_KEY) != _gen.get(spec.kind, 0)
        if stale:
            record.invalidate()  # closed now (its ``close`` event forgets it), never left idle in a pool nothing reaches

    @event.listens_for(eng, "close")
    def _lane_closed(dbapi_connection, _record) -> None:
        _note(spec.kind, id(dbapi_connection), live=False, out=False)

    @event.listens_for(eng, "close_detached")
    def _lane_closed_detached(dbapi_connection) -> None:
        _note(spec.kind, id(dbapi_connection), live=False, out=False)

    @event.listens_for(eng, "connect")
    def _lane_pragmas(dbapi_connection, _record) -> None:
        """WAL + the safety PRAGMAs, mirroring the corpus engine's own listener.

        ``mmap_size`` is deliberately NOT set: SQLCipher pages cannot be mapped
        through the codec, and a lane is encrypted by ruling, so the corpus
        listener's plaintext-only mmap branch would never fire here anyway.
        """
        try:
            _apply_lane_pragmas(dbapi_connection)
        except BaseException:
            _note(spec.kind, id(dbapi_connection), live=False, out=False)  # the pool drops it without a ``close`` event
            with contextlib.suppress(Exception):
                dbapi_connection.close()
            raise

    return eng


def _apply_lane_pragmas(dbapi_connection: Any) -> None:
    """The body of ``_lane_pragmas`` (a function of its own so the listener can clean up after it)."""
    cur = dbapi_connection.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        # Bounded, and much smaller than the corpus's RAM-derived budget: a lane
        # engine can be open BESIDE the corpus engine, so its cache is additive
        # to a figure another module already sized against the machine.
        cur.execute("PRAGMA cache_size=-16000")  # 16 MiB
        cur.execute("PRAGMA journal_size_limit=67108864")  # 64 MiB
    finally:
        cur.close()


def _other_engines_of(kind: str, key: tuple[str, str]) -> list[tuple[str, str]]:
    """The cached engines of ``kind`` under another file than ``key`` (call it with ``_lock`` held). A function of its own because a
    comprehension is inlined into its caller on CPython 3.13 and the back-edge of its filter-skip then sits outside the exception table of
    the ``with _lock`` in ``lane_engine`` (R205): an interrupt there would skip the lock's release."""
    return [k for k in _engines if k[0] == kind and k != key]


def _keys_of(kind: str) -> list[tuple[str, str]]:
    """The cached engine keys of ``kind`` (call it with ``_lock`` held), for the same reason as :func:`_other_engines_of`: the
    ``with _lock`` in ``dispose_lane`` (R205)."""
    return [k for k in _engines if k[0] == kind]


def lane_engine(kind: str, *, create: bool = False) -> Engine:
    """See :func:`_engine_and_factory`; the engine alone."""
    return _engine_and_factory(kind, create=create)[0]


def _engine_and_factory(kind: str, *, create: bool = False) -> tuple[Engine, sessionmaker]:
    """The engine for ``kind``. Refuses an absent lane unless ``create=True``.

    ``create=True`` is the ONLY path that may bring a lane file into existence, and
    it is spelled at every call site rather than defaulted, because "at first
    enablement" (the brief's design note) is a decision a reader should be able to
    find by grepping for the word.
    """
    spec = lane(kind)
    path = lane_path(kind)
    if not path.is_file() and not create:
        raise LaneAbsentError(f"the {spec.kind} lane has no database file at {path.name}")
    key = (kind, str(path))
    with _lock:
        stale = _other_engines_of(kind, key)
        eng = _engines.get(key)
        if eng is None:
            eng = _build_engine(spec, path)
            _engines[key] = eng
            _factories[key] = sessionmaker(bind=eng, autocommit=False, autoflush=False, future=True)
        # Read in the same locked step as the engine: ``dispose_lane`` pops both under this lock, and a factory looked up after the
        # lock was let go could be gone (a KeyError).
        factory = _factories[key]
    # Dispose OUTSIDE the lock: ``Engine.dispose`` closes sockets/file handles and
    # must never run while another thread is waiting to build its own engine.
    for k in stale:
        old = _engines.pop(k, None)
        _factories.pop(k, None)
        if old is not None:
            old.dispose()
    return eng, factory


def create_lane(kind: str) -> Path:
    """Create this lane's file (encrypted, by the factory's own rules) and its schema.

    Idempotent: an existing lane is re-opened and ``create_all`` is a no-op, which is
    what makes this safe to call from an enablement path that may be clicked twice.

    REFUSES BY NAME WHEN THE STORE IS LOCKED — and the refusal is a better-named
    RESTATEMENT of the factory's own, not the thing standing between this app and a
    plaintext lane. MEASURED, because a mutation matrix asked: with this branch
    deleted, ``connect()`` still refuses a fresh unkeyed file, with
    *"wiki.db does not exist yet: choose a passphrase (encrypted by default) or set
    OO_DB_PLAINTEXT=1 explicitly"*, and leaves no file behind. An earlier version of
    this docstring claimed the alternative was a plaintext lane; that was wrong, and
    a claim like it inside a security-shaped guard is how a redundant check acquires
    a reason nobody re-checks.

    It is KEPT because the message differs in the way that matters to whoever reads
    it: this one names the LANE and says the file shares the corpus passphrase,
    where the factory names a file and talks about ``OO_DB_PLAINTEXT``. That makes
    it OUR stated requirement rather than one inherited from a collaborator that
    could relax it — and ``tests/test_versioned_store.py`` asserts the wording, so
    it is falsifiable rather than decorative.
    """
    from src.database.connect import DatabaseLockedError, get_passphrase, plaintext_mode

    spec = lane(kind)
    path = lane_path(kind)
    fresh = not path.is_file()
    if fresh and not get_passphrase() and not plaintext_mode():
        raise DatabaseLockedError(
            f"the {spec.kind} lane cannot be created while the store is locked: "
            "its file is encrypted with the same passphrase as the corpus"
        )
    if fresh and plaintext_mode() and _corpus_is_encrypted():
        # The factory would honour the flag and write a plaintext lane here — the
        # opt-out outranks the passphrase for a FRESH file, and an already-encrypted
        # corpus never reaches that branch, so nothing else in the app would notice.
        raise PlaintextLaneRefused(
            f"refusing to create the {spec.kind} lane in the clear: the corpus at "
            f"{_corpus_path().name} is encrypted, and OO_DB_PLAINTEXT is set. A lane "
            "holds which sources you track, which is as revealing as the corpus. "
            "Unset OO_DB_PLAINTEXT for this process, or decrypt the corpus deliberately."
        )

    eng = lane_engine(kind, create=True)
    create_schema(kind, eng)
    if fresh:
        _LOG.info("created the %s lane at %s", spec.kind, path.name)
    return path


def _lane_specific_models(kind: str) -> tuple[type[DeclarativeBase], ...]:
    """The tables only ONE lane has, imported lazily so this module stays dependency-free.

    The shared schema is deliberately lane-agnostic (``versioned_entity_facts`` exists
    so a lane can state its own facts without its own columns), but a lane whose data
    is RELATIONAL — a law document's identity group, its provisions' addresses — needs
    real tables with real uniqueness, and a fact-row bag cannot carry a unique index.

    Returning them per kind rather than letting ``create_all`` take the whole metadata
    is what keeps those tables OUT of the other lanes' files: importing
    ``src.law.lane_models`` anywhere registers its tables on the shared
    ``LaneBase.metadata``, so a bare ``metadata.create_all(engine)`` would put three
    empty law tables into ``wiki.db`` for any operator who happened to load the module.
    """
    if kind == "law":
        from src.law.lane_models import LAW_LANE_MODELS

        return LAW_LANE_MODELS
    if kind == "wiki":
        # The ``allpages`` walk's page list and bookmark (Q701 = c; S05-06). Its own
        # tables, never ``versioned_entities``: see ``src/wiki/lane_models.py``.
        from src.wiki.lane_models import WIKI_LANE_MODELS

        return WIKI_LANE_MODELS
    if kind == "osm":
        # One country's objects, the cuts that made them, and the change MODEL (S05-04).
        from src.osm.lane_models import OSM_LANE_MODELS

        return OSM_LANE_MODELS
    if kind == "medical":
        # PubMed's kept records, their class changes, the ids the user named, the files read (S07-01; R745).
        from src.medical.lane_models import MEDICAL_LANE_MODELS

        return MEDICAL_LANE_MODELS
    return ()


def _lane_specific_setup(kind: str, engine: Engine) -> None:
    """What ONE lane needs beyond its tables, imported lazily like its models.

    The wiki lane's search index (``R52``, ``src/wiki/lane_search.py``) is an FTS5 table and
    the triggers that queue each new text for it -- SQL that ``create_all`` cannot express.
    Created HERE, with the schema, so the triggers exist before the lane's first write can
    need them. It never fails the schema: a lane that cannot hold the index still collects,
    and the next open tries again.
    """
    if kind != "wiki":
        return
    try:
        from src.wiki.lane_search import ensure_index

        ensure_index(engine)
    except Exception as exc:  # noqa: BLE001 - the search index must never stop the lane opening
        log_failure(_LOG, "the Wikipedia lane search index could not be set up", exc, level=logging.WARNING)

class LaneSchemaError(RuntimeError):
    """A lane file whose schema this build cannot reconcile without a real migration."""


def add_missing_columns(engine: Engine) -> list[str]:
    """ADD the columns a newer build declared and an older lane file does not have.

    WHY THIS EXISTS, AND WHY IT IS NOT A MIGRATION FRAMEWORK. ``create_all`` creates
    missing TABLES and never touches an existing one's columns — that is
    SQLAlchemy's documented behaviour, not a surprise — so a column added to
    ``models.py`` reaches a FRESH lane file and no other. ``models.py`` says there is
    "deliberately NO alembic history for lane files in 0.4: these tables are born
    here, so there is nothing to migrate", which was true for exactly as long as one
    build had declared them. S04-09 added ``VersionedEntity.deleted_at`` (Q713's
    mark) and a facts table, so a lane file created by S04-08's build and opened by
    this one would raise ``no such column`` on its first read. The table arrives
    through ``create_all``; the column had nowhere to arrive from until here.

    WHAT IT HANDLES AND WHAT IT REFUSES. It adds NULLABLE columns, and columns with a
    scalar server-side default, because those are the additions whose meaning for
    existing rows is unambiguous: every old row gets NULL (or the default), which is
    exactly what "this build did not know about it" means. It REFUSES — by name,
    loudly, without touching the file — a declared column that is NOT NULL with no
    default, because filling one for existing rows is a decision about their contents
    that only a real migration can make. It never drops, renames or retypes anything:
    a column present in the file and absent from the model is LEFT ALONE, since the
    file may have been written by a build newer than this one and destroying its data
    to match an older model is the worst thing this function could do.

    Returns the ``table.column`` names it added, so a caller can log what changed
    rather than discovering it later. Empty on an up-to-date file, which is the
    ordinary case and costs one ``PRAGMA`` per table.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text as sa_text

    from src.versioned.models import LaneBase

    # PLAN FIRST, APPLY SECOND, and that order is the whole difference between a
    # refusal and a half-applied schema. Applying as it went would add every column
    # BEFORE the one it refuses, leaving a file that is neither the old shape nor the
    # new one — and nothing on disk would say which. Planning first means a refusal
    # touches nothing at all.
    plan: list[tuple[str, str, str]] = []  # (table, column, DDL clause)
    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table in LaneBase.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all just made it, with every column.
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            if not column.nullable and column.server_default is None:
                raise LaneSchemaError(
                    f"{table.name}.{column.name} is NOT NULL with no server default; "
                    "an existing lane file cannot be given one without deciding what "
                    "its existing rows should say. This needs a real migration. "
                    "Nothing was changed."
                )
            ddl = column.type.compile(engine.dialect)
            clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'
            default = getattr(column.server_default, "arg", None)
            if default is not None:
                # A ``FetchedValue`` server default has no literal to write, and one
                # that is a SQL expression rather than a scalar is not something this
                # additive path should be inventing DDL for. Both fall through to a
                # plain nullable ADD COLUMN, which is the honest behaviour: the rows
                # get NULL and the model's Python-side default fills new writes.
                clause += f" DEFAULT {default}"
            plan.append((table.name, column.name, clause))

    added: list[str] = []
    for table_name, column_name, clause in plan:
        with engine.begin() as conn:
            conn.execute(sa_text(clause))
        added.append(f"{table_name}.{column_name}")
    if added:
        _LOG.info("lane schema: added %s", ", ".join(added))
    return added


def create_schema(kind: str, engine: Engine | None = None) -> None:
    """Materialise the lane tables and stamp ``lane_meta``. Idempotent.

    ``LaneBase.metadata`` — never the corpus ``Base.metadata``. The two are separate
    declarative roots precisely so this line cannot put lane tables in ``corpus.db``
    and ``alembic check`` cannot demand migrations for them (see ``models.py``).

    The table list is EXPLICIT — the shared models plus this kind's own — rather than
    the whole metadata; see ``_lane_specific_models`` for why that distinction is
    load-bearing rather than tidy.
    """
    from src.versioned.models import LANE_MODELS, LaneBase, LaneMeta

    eng = engine if engine is not None else lane_engine(kind, create=True)
    # The two changes that met here compose, and the reason is one line in
    # `add_missing_columns`: it SKIPS a table the file does not have. So creating only
    # this kind's tables (which is what keeps three empty law tables out of every
    # operator's wiki.db) leaves the column pass nothing to do for the tables this lane
    # does not own, rather than pointing it at tables that were never created.
    # ``__table__`` rather than ``__tablename__``: the OSM lane's ``osm_objects`` is built
    # from a ``Table`` (its curated columns are generated), so it has no ``__tablename__``.
    wanted = [
        cast("Table", m.__table__)
        for m in (*LANE_MODELS, *_lane_specific_models(kind))
    ]
    LaneBase.metadata.create_all(eng, tables=wanted)
    add_missing_columns(eng)
    # ``.get``: a switch's hold may have popped the cached factory meanwhile; one bound to this engine does the same job.
    factory = _factories.get((kind, str(lane_path(kind)))) or sessionmaker(bind=eng, autocommit=False, autoflush=False, future=True)
    with factory() as session:
        row = session.query(LaneMeta).first()
        if row is None:
            session.add(LaneMeta(kind=kind, schema_version=1))
            session.commit()
        elif row.kind != kind:
            # A wiki lane opened as a law lane would write rows that read as real.
            # Refuse loudly; there is no safe repair this function could perform.
            raise ValueError(
                f"{lane_path(kind).name} says it holds the {row.kind!r} lane, not {kind!r}"
            )
    _lane_specific_setup(kind, eng)


@contextmanager
def lane_session(kind: str, *, create: bool = False) -> Iterator[Session]:
    """A session on one lane. Commits on success, rolls back on error, always closes."""
    _eng, factory = _engine_and_factory(kind, create=create)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_lane(kind: str) -> None:
    """Close this lane's pool and forget the engine.

    WHY, and what is actually true. A pooled SQLCipher connection holds a derived key in
    memory and an open handle on the file, so any path that drops the passphrase or
    replaces the file must drop these too. An earlier version of this docstring said
    "called when the store LOCKS" — and nothing called it at all, which made the
    sentence a description of an intention.

    What is true now: this tree has NO in-process relock (grep-verified — the only
    callers of ``set_passphrase(None)`` are the crypto-erase and a fresh-state failure
    path), so "locking" is a restart and a restart takes the engines with it. The two
    real in-process events are ``src/safety/crypto_erase.py`` (which calls
    ``dispose_all`` once every lane's salt page is gone and before the passphrase is
    cleared: closing first would write a large lane log back while the salt is still on
    the disk, row 28) and ``src/database/encrypt_tool.py``
    (which swaps each file underneath, so a cached engine would keep using the replaced
    one). Both call it. Also the right thing before any other file-level operation on a
    lane — a snapshot, a restore swap.
    """
    _next_generation(kind)  # a connection out right now is closed when it comes back, not left in the replaced pool
    with _lock:
        keys = _keys_of(kind)
        engines = [_engines.pop(k) for k in keys]
        for k in keys:
            _factories.pop(k, None)
    for eng in engines:
        eng.dispose()


def dispose_all() -> None:
    """Dispose every open lane. The lock path's one call, and the suite's reset."""
    for kind in {k[0] for k in list(_engines)}:
        dispose_lane(kind)
