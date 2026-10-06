"""A shipped stoplist change reaches the stored ``top_keyword_*`` columns (R111 step T3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP. A stopword shipped with an update hides a stored keyword at READ time on every listing
that reads the hidden predicate. Two stored things keep the old answer until something recomputes
them: the cached Home cards (their titles were made before the word was hidden; see
``src.briefing.service``) and ``Article.top_keyword_id`` / ``top_keyword_count`` /
``top_keyword_tied_n``, which the Articles list shows and sorts on. This module recomputes the
second. Hiding stays read-time: no mention row is touched, so the raw counts every other reader
uses are exactly what they were.

WHAT "STOPLISTED" MEANS HERE. The SHIPPED list only (``global_stopwords()``), never the user's
exclusions, minimum length or the built-in switch. Those are the user's own read-time settings and
change by a click; the stored columns follow what extraction itself drops, which is the shipped
list whatever the switch says. A word hidden only by a user's exclusion stays hidden by the
predicate, as on every other listing.

WHEN IT RUNS. When the fingerprint of the shipped list (sha256 of the sorted words) differs from the
one recorded by the last finished run, in the off-peak maintenance window and its offline timer. A
fresh install records the fingerprint after a run that finds nothing, so it never pays. The
fingerprint is written AFTER the last chunk: a kill, a restart or a failure leaves it unwritten and
the next window resumes from the stored cursor.

WHAT IT TOUCHES. Only articles whose top set held a hidden word. The top set is the keywords that
reached the highest count, so a hidden word can sit in it as a NON-lowest member of a tie, which the
stored representative id cannot show; the test therefore reads the article's own mentions (the
per-article covering index, no join to the wide article row) and asks whether a hidden word reached
the highest count. An article whose stored columns already equal the recomputed ones is counted and
not written (its record is wide, so a write rewrites many pages). An article whose columns are NULL
("never computed") is left for the index to fill. Each affected article is handled once, when its
walk reaches its LOWEST hidden keyword.

WHAT EACH NUMBER PROTECTS. Nothing here caps the work; every number says how it shares the machine.
A chunk reads, decides and writes in ONE short transaction under the write window, and no read
transaction spans two chunks (a long read pins the write-ahead log, which the crash read measured at
about 1,500 s). The chunk size is not a constant: it moves so the write window is held about
:data:`TARGET_HOLD_S` seconds, the longest another writer waits behind one chunk, between
:data:`MIN_CHUNK` (a chunk that still makes progress when each row is slow) and :data:`MAX_CHUNK` (one
chunk's mention reads and updated pages, so the log grows by a bounded amount per commit). The pass
stops at a chunk boundary when the storage guard (a pinned log or a full drive) or the memory guard
is engaged, on a stop request, or at its soft budget, and resumes at its cursor.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sqlalchemy import Table

_LOG = logging.getLogger("analytics.stoplist_recompute")

#: The resume point: ``<fingerprint>:<hidden keyword id>:<last article id>`` in ``derived_meta``.
#: It carries the fingerprint it was made under, so a cursor from an older list is never resumed.
CURSOR_KEY = "stoplist_recompute_cursor"

#: Write-window hold per chunk the size adapts to (see the module docstring).
TARGET_HOLD_S = 0.25
MIN_CHUNK = 25
MAX_CHUNK = 2000
START_CHUNK = 200
#: Articles remembered as reached within one pass. It protects the pass's resident memory (measured
#: about 63 bytes an id as a Python set of ints: 2 million ids took 125 MiB, so this cap is about
#: 31 MiB, under 1 % of the 4 GiB memory tier the crash diagnostics separated). Past it an article is
#: read again and the lowest-keyword test still decides, so the result never changes; only the pass
#: slows (50,000 articles that each hold ~22 hidden words: 14 s remembering all of them, 67 s with a
#: cap one fifth of the corpus, 86 s remembering none). A corpus under this many articles is never
#: affected, which is why the number is a corpus size and not a tier.
SEEN_CAP = 500_000
#: SQLite's variable limit is 999 on old builds; every ``IN`` list stays under it.
_IN_CHUNK = 900


def _budget_s() -> float:
    """Soft wall-clock budget of one pass (``OO_STOPLIST_RECOMPUTE_BUDGET_S``; 0 = unbounded)."""
    try:
        return float(os.getenv("OO_STOPLIST_RECOMPUTE_BUDGET_S", "30"))
    except ValueError:
        return 30.0


# --------------------------------------------------------------------------------- fingerprint


_fp_memo: tuple[object, str] | None = None


def current_fingerprint() -> str:
    """sha256 of the sorted shipped stoplist. Cached per process (the list is)."""
    global _fp_memo
    from src.analytics.extract import global_stopwords

    words = global_stopwords()
    memo = _fp_memo
    if memo is not None and memo[0] is words:
        return memo[1]
    digest = hashlib.sha256("\n".join(sorted(words)).encode("utf-8")).hexdigest()
    _fp_memo = (words, digest)
    return digest


def _state_path():
    from src.paths import data_dir

    return data_dir() / "stoplist_recompute.json"


def read_state() -> dict:
    """The last finished run and the last pass. Never raises; ``{}`` when there is none."""
    try:
        p = _state_path()
        if p.exists():
            doc = json.loads(p.read_text(encoding="utf-8"))
            return doc if isinstance(doc, dict) else {}
    except Exception:  # noqa: BLE001 - a diagnostic read must never crash
        pass
    return {}


def _write_state(doc: dict) -> None:
    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001 - the record is bookkeeping; the cursor decides resumption
        _LOG.warning("stoplist recompute state could not be written")


def needs_run() -> bool:
    """True while the recorded fingerprint is not the shipped list's."""
    try:
        return read_state().get("fingerprint") != current_fingerprint()
    except Exception:  # noqa: BLE001 - unknown means "not known to be pending"
        return False


def incomplete() -> bool:
    """The last pass stopped early on a list that has not been finished (the offline timer runs
    passes back to back only then)."""
    try:
        st = read_state()
        return st.get("fingerprint") != current_fingerprint() and (st.get("last_pass") or {}).get(
            "complete"
        ) is False
    except Exception:  # noqa: BLE001
        return False


def state_stamp() -> object:
    """Changes whenever a pass records itself (the timer stops a loop that records nothing)."""
    return (read_state().get("last_pass") or {}).get("at")


# ------------------------------------------------------------------------------------- cursor


def _cursor_get(session: Any, fp: str) -> tuple[int, int]:
    from src.database.models import DerivedMeta

    try:
        raw = session.query(DerivedMeta.value).filter(DerivedMeta.key == CURSOR_KEY).scalar()
        if raw:
            got_fp, kid, aid = str(raw).split(":")
            if got_fp == fp:
                return int(kid), int(aid)
    except Exception:  # noqa: BLE001 - a lost cursor costs a re-scan, never a wrong value
        pass
    return 0, 0


def _cursor_set(session: Any, fp: str, kid: int, aid: int) -> None:
    from src.database.models import DerivedMeta

    value = f"{fp}:{int(kid)}:{int(aid)}"
    row = session.get(DerivedMeta, CURSOR_KEY)
    if row is None:
        session.add(DerivedMeta(key=CURSOR_KEY, value=value, updated_at=datetime.now(UTC)))
    else:
        row.value = value
        row.updated_at = datetime.now(UTC)


# ---------------------------------------------------------------------------------- the pass


def hidden_keyword_ids(session: Any) -> list[int]:
    """Ids of the keyword rows whose normalized term is on the shipped list, ascending."""
    from src.analytics.extract import global_stopwords
    from src.database.models import Keyword

    words = sorted(global_stopwords())
    ids: list[int] = []
    for i in range(0, len(words), _IN_CHUNK):
        batch = words[i : i + _IN_CHUNK]
        ids.extend(
            int(kid)
            for (kid,) in session.query(Keyword.id).filter(Keyword.normalized_term.in_(batch))
        )
    return sorted(set(ids))


def _guard_reason() -> str | None:
    """Why a chunk must not start now (the same two guards the maintenance window reads)."""
    try:
        from src.scheduler import memguard, storage_guard

        if memguard.memory_guard.engaged:
            return "memory_pressure"
        if storage_guard.storage_guard.enabled() and storage_guard.storage_guard.engaged:
            return "storage_pressure"
    except Exception:  # noqa: BLE001 - a guard read must never block (it only ever defers)
        return None
    return None


def next_chunk_size(n: int, held_s: float) -> int:
    """Move the chunk so the write window is held about :data:`TARGET_HOLD_S` seconds."""
    if held_s > TARGET_HOLD_S:
        n = n // 2
    elif held_s < TARGET_HOLD_S / 2:
        n = n * 2
    return max(MIN_CHUNK, min(MAX_CHUNK, n))


def _one_chunk(
    session: Any,
    ids: list[int],
    pos: int,
    after: int,
    n: int,
    hidden: frozenset[int],
    seen: set[int] | None = None,
) -> dict:
    """Read, decide and write one chunk inside the caller's transaction (the write window is
    already held). The chunk covers up to ``n`` mention rows of the hidden keywords from
    ``ids[pos]`` (resuming after article ``after``), moving to the next keyword when one is
    exhausted, so a keyword with few mentions does not cost a transaction of its own.

    ``seen`` (optional) holds the articles already reached in this pass: the walk meets an article
    first at its LOWEST hidden keyword, so a later meeting needs no read at all. It only saves reads;
    after a resume it starts empty and the lowest-keyword test below still keeps each article to one
    handling.

    Returns the new position ``(pos, after)`` and the counts."""
    from sqlalchemy import bindparam, select

    from src.analytics.store import top_keyword_of
    from src.database.derived_views import KeywordMentionRead as KM
    from src.database.models import Article

    out = {"scanned": 0, "handled_later": 0, "top_unaffected": 0, "never_computed": 0,
           "already_clean": 0, "updated": 0, "to_none": 0}
    found: list[tuple[int, int]] = []  # (hidden keyword id, article id), in walk order
    start_pos = pos
    walk_started = time.monotonic()
    while pos < len(ids) and len(found) < n:
        # A keyword with few mentions costs an index probe, not rows: the walk over many of them
        # is bounded by the same hold target (half of it; the reads and the write follow).
        if pos > start_pos and time.monotonic() - walk_started > TARGET_HOLD_S / 2:
            break
        kid = ids[pos]
        want = n - len(found)
        aids = [
            int(a)
            for (a,) in session.execute(
                select(KM.article_id)
                .where(KM.keyword_id == kid, KM.article_id > after)
                .order_by(KM.article_id)
                .limit(want)
            )
        ]
        found.extend((kid, a) for a in aids)
        if len(aids) < want:  # this keyword's mentions are exhausted
            pos, after = pos + 1, 0
        else:
            after = aids[-1]
    out["pos"], out["after"] = pos, after
    out["scanned"] = len(found)
    if not found:
        return out
    if seen is not None:
        fresh = [(k, a) for k, a in found if a not in seen]
        out["handled_later"] += len(found) - len(fresh)
        found = fresh
    wanted = sorted({a for _k, a in found})
    if seen is not None and len(seen) < SEEN_CAP:
        seen.update(wanted)
    contrib: dict[int, dict[int, int]] = defaultdict(dict)
    for i in range(0, len(wanted), _IN_CHUNK):
        batch = wanted[i : i + _IN_CHUNK]
        for aid, k, c in session.execute(
            select(KM.article_id, KM.keyword_id, KM.count).where(KM.article_id.in_(batch))
        ):
            contrib[int(aid)][int(k)] = int(c)
    new_of: dict[int, tuple[int | None, int | None, int | None]] = {}
    for kid, aid in found:
        cont = contrib.get(aid, {})
        held = [k for k in cont if k in hidden]
        if not held or min(held) != kid:
            out["handled_later"] += 1  # its lowest hidden keyword is another one
            continue
        visible = {k: c for k, c in cont.items() if k not in hidden}
        top_hidden = max((cont[k] for k in held), default=0)
        top_visible = max((c for c in visible.values() if c > 0), default=0)
        if top_hidden <= 0 or top_hidden < top_visible:
            out["top_unaffected"] += 1
            continue
        new_of[aid] = top_keyword_of(visible)
    if not new_of:
        return out
    stored: dict[int, tuple[Any, Any, Any]] = {}
    ids_new = list(new_of)
    for i in range(0, len(ids_new), _IN_CHUNK):
        batch = ids_new[i : i + _IN_CHUNK]
        for row in session.execute(
            select(
                Article.id,
                Article.top_keyword_id,
                Article.top_keyword_count,
                Article.top_keyword_tied_n,
            ).where(Article.id.in_(batch))
        ):
            stored[int(row[0])] = (row[1], row[2], row[3])
    changes = []
    for aid, new in new_of.items():
        old = stored.get(aid)
        if old is None or old[1] is None:
            out["never_computed"] += 1  # NULL = never computed: the index fills it forward
        elif tuple(old) == new:
            out["already_clean"] += 1
        else:
            changes.append({"_aid": aid, "tk": new[0], "tc": new[1], "tn": new[2]})
            if new[1] is None:
                out["to_none"] += 1
    if changes:
        tbl = cast("Table", Article.__table__)
        # ``updated_at`` is written back as itself: an ORM or Core UPDATE would otherwise stamp
        # every article this pass fixes as edited just now.
        session.execute(
            tbl.update()
            .where(tbl.c.id == bindparam("_aid"))
            .values(
                top_keyword_id=bindparam("tk"),
                top_keyword_count=bindparam("tc"),
                top_keyword_tied_n=bindparam("tn"),
                updated_at=tbl.c.updated_at,
            ),
            changes,
        )
        out["updated"] = len(changes)
    return out


def maybe_recompute_top_keywords(
    *, should_stop: Callable[[], bool] | None = None, budget_s: float | None = None
) -> dict:
    """Recompute the stored top keywords for the current shipped list, resumably. Never raises.

    ``{"skipped": "current"}`` when nothing is due; otherwise the pass's tally with
    ``complete`` True once the whole walk is done (the fingerprint is recorded then, and only then).
    """
    from src.monitoring.engine_text import engine_text

    stop = should_stop or (lambda: False)
    try:
        fp = current_fingerprint()
        if read_state().get("fingerprint") == fp:
            return {"skipped": "current"}
        reason = _guard_reason()
        if reason:
            return {"skipped": reason, "complete": False}
        return _run(fp, stop, _budget_s() if budget_s is None else budget_s)
    except Exception as exc:  # noqa: BLE001 - a background safety net must never break the window
        # The engine's words can carry the statement it failed on: the passphrase is taken out
        # of the text before it is cut or recorded, and no traceback is logged.
        text = f"{type(exc).__name__}: {engine_text(exc)}"[:200]
        _LOG.warning("stoplist recompute failed: %s", text)
        return {"skipped": text, "complete": False}


def _run(fp: str, stop: Callable[[], bool], budget: float) -> dict:
    from src.database.derived_views import require_mentions_view
    from src.database.models import DerivedMeta
    from src.database.session import session_scope
    from src.database.writer import hold_write_window

    t0 = time.monotonic()
    tally: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(timespec="microseconds"),
        "fingerprint": fp,
        "scanned": 0,
        "updated": 0,
        "already_clean": 0,
        "never_computed": 0,
        "top_unaffected": 0,
        "handled_later": 0,
        "to_none": 0,
        "chunks": 0,
        "write_window_s": 0.0,
        "complete": False,
        "stopped_by": None,
    }
    with session_scope() as session:  # a short read of its own; nothing spans two chunks
        require_mentions_view(session)
        ids = hidden_keyword_ids(session)
        kid0, after0 = _cursor_get(session, fp)
    tally["hidden_keywords"] = len(ids)
    tally["resumed_at"] = [kid0, after0] if (kid0 or after0) else None
    hidden = frozenset(ids)
    n = START_CHUNK
    seen: set[int] = set()
    pos = bisect.bisect_left(ids, kid0)
    after = after0 if pos < len(ids) and ids[pos] == kid0 else 0
    while pos < len(ids):
        reason = "stop" if stop() else _guard_reason()
        if reason is None and budget > 0 and time.monotonic() - t0 > budget:
            reason = "budget"
        if reason:
            tally["stopped_by"] = reason
            _finish(tally, fp)
            return tally
        held0 = time.monotonic()
        with session_scope() as session:
            hold_write_window(session)
            got = _one_chunk(session, ids, pos, after, n, hidden, seen)
            pos, after = got["pos"], got["after"]
            _cursor_set(session, fp, ids[pos] if pos < len(ids) else ids[-1] + 1, after)
        held = time.monotonic() - held0
        tally["chunks"] += 1
        tally["write_window_s"] = round(tally["write_window_s"] + held, 3)
        for key in ("scanned", "updated", "already_clean", "never_computed",
                    "top_unaffected", "handled_later", "to_none"):
            tally[key] += got[key]
        n = next_chunk_size(n, held)
    with session_scope() as session:  # the walk is done: a cursor must not outlive its fingerprint
        row = session.get(DerivedMeta, CURSOR_KEY)
        if row is not None:
            hold_write_window(session)
            session.delete(row)
    tally["complete"] = True
    tally["chunk_size_at_end"] = n
    _finish(tally, fp)
    return tally


def _finish(tally: dict, fp: str) -> None:
    """Record the pass; the fingerprint only when the walk is complete."""
    state = read_state()
    last = {k: v for k, v in tally.items() if k != "fingerprint"}
    doc = {**state, "last_pass": last, "list_size": None}
    try:
        from src.analytics.extract import global_stopwords

        doc["list_size"] = len(global_stopwords())
    except Exception:  # noqa: BLE001
        pass
    if tally.get("complete"):
        doc["fingerprint"] = fp
        doc["completed_at"] = tally["at"]
    _write_state(doc)
    _LOG.info("stoplist recompute: %s", last)
