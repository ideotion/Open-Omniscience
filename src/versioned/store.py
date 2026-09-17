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

NO PER-LANE PLAINTEXT. ``connect()`` decides a FRESH file's at-rest state from the
process passphrase and the app-wide ``OO_DB_PLAINTEXT`` opt-out; this module passes
neither ``key=`` nor ``create_encrypted=``, so a lane can never be created
plaintext while the corpus is encrypted. ``create_lane`` additionally REFUSES to
create a lane file when no passphrase is available (``DatabaseLockedError``),
rather than quietly waiting for an unlock that may not come — an absent lane is an
honest state and a half-made one is not.

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

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

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

    def _creator():
        from src.database.connect import connect

        # No ``key=``, no ``create_encrypted=``: the factory's own precedence is the
        # ruling (Q720/Q1005). Passing either here would be this module deciding a
        # lane's at-rest state, which is the one thing it must not do.
        return connect(str(path), check_same_thread=False, timeout=30)

    eng = create_engine(
        f"sqlite:///{path}",
        future=True,
        creator=_creator,
        pool_size=2,
        max_overflow=4,
        pool_timeout=30,
    )

    @event.listens_for(eng, "connect")
    def _lane_pragmas(dbapi_connection, _record) -> None:
        """WAL + the safety PRAGMAs, mirroring the corpus engine's own listener.

        ``mmap_size`` is deliberately NOT set: SQLCipher pages cannot be mapped
        through the codec, and a lane is encrypted by ruling, so the corpus
        listener's plaintext-only mmap branch would never fire here anyway.
        """
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

    return eng


def lane_engine(kind: str, *, create: bool = False) -> Engine:
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
        stale = [k for k in _engines if k[0] == kind and k != key]
        eng = _engines.get(key)
        if eng is None:
            eng = _build_engine(spec, path)
            _engines[key] = eng
            _factories[key] = sessionmaker(bind=eng, autocommit=False, autoflush=False, future=True)
    # Dispose OUTSIDE the lock: ``Engine.dispose`` closes sockets/file handles and
    # must never run while another thread is waiting to build its own engine.
    for k in stale:
        old = _engines.pop(k, None)
        _factories.pop(k, None)
        if old is not None:
            old.dispose()
    return eng


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

    eng = lane_engine(kind, create=True)
    create_schema(kind, eng)
    if fresh:
        _LOG.info("created the %s lane at %s", spec.kind, path.name)
    return path


def create_schema(kind: str, engine: Engine | None = None) -> None:
    """Materialise the lane tables and stamp ``lane_meta``. Idempotent.

    ``LaneBase.metadata`` — never the corpus ``Base.metadata``. The two are separate
    declarative roots precisely so this line cannot put lane tables in ``corpus.db``
    and ``alembic check`` cannot demand migrations for them (see ``models.py``).
    """
    from src.versioned.models import LaneBase, LaneMeta

    eng = engine if engine is not None else lane_engine(kind, create=True)
    LaneBase.metadata.create_all(eng)
    factory = _factories[(kind, str(lane_path(kind)))]
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


@contextmanager
def lane_session(kind: str, *, create: bool = False) -> Iterator[Session]:
    """A session on one lane. Commits on success, rolls back on error, always closes."""
    lane_engine(kind, create=create)
    factory = _factories[(kind, str(lane_path(kind)))]
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

    Called when the store LOCKS: a pooled SQLCipher connection holds a derived key in
    memory, and a lane that kept one open after the operator locked the app would be
    a quiet exception to the lock. Also the safe thing to call before any file-level
    operation on the lane (a snapshot, a restore swap).
    """
    with _lock:
        keys = [k for k in _engines if k[0] == kind]
        engines = [_engines.pop(k) for k in keys]
        for k in keys:
            _factories.pop(k, None)
    for eng in engines:
        eng.dispose()


def dispose_all() -> None:
    """Dispose every open lane. The lock path's one call, and the suite's reset."""
    for kind in {k[0] for k in list(_engines)}:
        dispose_lane(kind)
