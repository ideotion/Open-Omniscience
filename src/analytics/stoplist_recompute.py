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
fresh install records the fingerprint after a run that finds nothing, so it never pays; the first
run on an existing corpus has no baseline and walks every hidden word (see below). The
fingerprint is written AFTER the last chunk: a kill, a restart or a failure leaves it unwritten and
the next window resumes from the stored cursor.

WHAT IT TOUCHES. Only articles that hold a hidden word (a mention of a keyword the walk reaches). The
top set is the keywords that reached the highest count, so a hidden word can sit in it as a NON-lowest
member of a tie, which the stored representative id cannot show; each reached article's own mentions
are therefore read (the per-article covering index, no join to the wide article row) and the top is
recomputed from them without the hidden words. An article whose stored columns already equal the
recomputed ones is counted and not written (its record is wide, so a write rewrites many pages). An article whose columns are NULL
("never computed") is left for the index to fill, except where a word taken off the list is
concerned (below). Each affected article is handled once, when its walk reaches its LOWEST walked
keyword.

NO SHORTCUT, AND WHAT KEEPS A HIDDEN WORD OUT OF A TOP. Every article a walk reaches is recomputed from
its mentions and compared with what is stored. (An earlier design skipped an article whose hidden
word sat below its visible top. That is true only if the stored top was made under a list that is a
SUBSET of today's hidden set, and a lost baseline, a stopped pass or a word swapped for another each
break it, so a top made under an older list could keep a word the next change hides. The measured cost
of reading them all, once per list, is in OPEN_QUEUE.md.) What is left to keep true is WHICH
articles are reached:

* A word TAKEN OFF the list (a ring exemption, a retired entry) is walked as a RESTORED keyword: its
  articles' tops were made without it, so they are reached through it, and a NULL there is filled (an
  article with only hidden words was written NULL, which looks like "never computed").
* A pass that STOPS or crashes on an intermediate list leaves tops made under lists the finished
  baseline does not know. So before a pass writes anything it records ``words_pending`` = every list
  walked since the last finished run (a checked write: no pass starts if it cannot be written), the
  restored words are (finished list + pending) minus today's, and the run counts as current only
  when the fingerprint matches AND nothing is pending.
* A walk is resumed only by the same walk: the cursor is keyed by the list fingerprint AND the plan
  (which words were restored), because the same list can be walked later with a larger plan, and
  resuming at a cursor past a restored keyword would never reach its articles.
* A baseline that does not travel with the data. The state file lives beside the database, not in
  it, so a restore, a merge swap or a moved database can read as current while its tops are older.
  The finished fingerprint is therefore ALSO written to ``derived_meta`` in the same transaction as
  the last cursor delete, and "current" needs both to agree and no cursor row to remain (a copy
  taken mid-pass carries one). When they do not agree (or the file is missing, unreadable or the wrong
  type) the baseline is UNKNOWN: no word is restored, because the lists it needed are lost, and a
  word taken off the list since then can stay missing from tops until its articles are re-indexed.
  A merge that carries articles forgets the whole baseline for the same reason, so a word taken off
  between the last finished run and the next window is not restored either.

WHAT EACH NUMBER PROTECTS. Nothing here caps the work; every number says how it shares the machine.
A chunk reads, decides and writes in ONE short transaction under the write window, and no read
transaction spans two chunks (a long read pins the write-ahead log, which the crash read measured at
about 1,500 s). The chunk size is not a constant: it moves so the write window is held about
:data:`TARGET_HOLD_S` seconds, the time another writer waits behind one chunk (aimed at, not guaranteed:
the controller reacts after the fact, and 0.28 to 0.39 s was the longest measured), between
:data:`MIN_CHUNK` (a chunk that still makes progress when each row is slow) and :data:`MAX_CHUNK` (the
most mention rows one chunk reads and the most article records it can rewrite). The write-ahead log is
MEASURED, as the polled high-water of the whole pass, not per chunk: 4.2 to 4.9 MiB over a
200,000-article pass and 19.7 MiB when every one of 50,000 articles with 12 KB bodies was rewritten (a
three-column update rewrites the whole record, overflow pages included, when its size changes); rows
wider than that are bounded by the time target alone. The window timed is the one other writers wait
behind, from the gate being HELD to the commit, so waiting for the gate never shrinks a chunk. The
pass stops at a chunk boundary when the storage guard (a pinned log or a full drive) or the memory
guard is engaged, on a stop request, or at its soft budget, and resumes at its cursor.
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

#: The resume point: ``<fingerprint>.<plan>:<hidden keyword id>:<last article id>`` in ``derived_meta``
#: (``<fingerprint>.<plan>`` is ``_run``'s walk key; ``<plan>`` is a hash of the bool ``known`` and the
#: words taken off the list). It carries the list and the plan it was made under, so a cursor from an
#: older list, or from a smaller walk, is never resumed.
CURSOR_KEY = "stoplist_recompute_cursor"
#: The fingerprint of the last FINISHED run, in the database beside the data it describes (written in
#: the transaction that deletes the last cursor), so a restored or moved database cannot read as
#: current on the strength of a state file that stayed behind.
DONE_KEY = "stoplist_recompute_done"

#: Write-window hold per chunk the size adapts to (see the module docstring).
TARGET_HOLD_S = 0.25
MIN_CHUNK = 25
MAX_CHUNK = 2000
#: The first chunk: small enough that a slow store holds the window briefly before anything is
#: measured; the controller doubles it each chunk that held the window under half the target (three
#: doublings, so four chunks at the least, from here to 1,600).
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
    """Soft wall-clock budget of one pass (``OO_STOPLIST_RECOMPUTE_BUDGET_S``; 0 = unbounded).

    It protects the scheduler's run lock, which the maintenance window holds while the pass runs: a
    "Collect now" asked meanwhile answers busy for up to this long. It is read once a chunk has run, so
    it bounds the wait without ever stopping a pass before it moves."""
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


def _write_state(doc: dict) -> bool:
    """Write the state file; False (and a log line) when it could not be written."""
    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
        return True
    except Exception:  # noqa: BLE001 - the record is bookkeeping; the cursor decides resumption
        _LOG.warning("stoplist recompute state could not be written")
        return False


def _words_of(value: Any) -> set[str] | None:
    """A recorded word list as a set; None when it is not a list of strings (an unusable record)."""
    if isinstance(value, list) and all(isinstance(w, str) for w in value):
        return set(value)
    return None


def _pending_of(state: dict) -> set[str] | None:
    """The lists walked since the last finished run (empty when none); None when unusable."""
    raw = state.get("words_pending")
    return set() if raw is None else _words_of(raw)


def _is_current(state: dict, fp: str) -> bool:
    """The state file alone says nothing is owed: the fingerprint matches and nothing is pending."""
    pending = _pending_of(state)
    return state.get("fingerprint") == fp and pending is not None and not pending


def needs_run() -> bool:
    """True while the state file does not say the shipped list is finished (a fingerprint that is
    not the list's, or lists walked since the last finished run). The database's own record is
    checked by the pass itself."""
    try:
        return not _is_current(read_state(), current_fingerprint())
    except Exception:  # noqa: BLE001 - unknown means "not known to be pending"
        return False


def incomplete() -> bool:
    """The last pass stopped early on a list that has not been finished (the offline timer runs
    passes back to back only then)."""
    try:
        st = read_state()
        return not _is_current(st, current_fingerprint()) and (st.get("last_pass") or {}).get(
            "complete"
        ) is False
    except Exception:  # noqa: BLE001
        return False


def state_stamp() -> object:
    """Changes whenever a pass records itself (the timer stops a loop that records nothing)."""
    return (read_state().get("last_pass") or {}).get("at")


# ------------------------------------------------------------------------------------- cursor


def _cursor_get(session: Any, walk_key: str) -> tuple[int, int]:
    from src.database.models import DerivedMeta

    try:
        raw = session.query(DerivedMeta.value).filter(DerivedMeta.key == CURSOR_KEY).scalar()
        if raw:
            got_fp, kid, aid = str(raw).split(":")
            if got_fp == walk_key:
                return int(kid), int(aid)
    except Exception:  # noqa: BLE001 - a lost cursor costs a re-scan, never a wrong value
        pass
    return 0, 0


def _meta_set(session: Any, key: str, value: str) -> None:
    from src.database.models import DerivedMeta

    row = session.get(DerivedMeta, key)
    if row is None:
        session.add(DerivedMeta(key=key, value=value, updated_at=datetime.now(UTC)))
    else:
        row.value = value
        row.updated_at = datetime.now(UTC)


def _cursor_set(session: Any, walk_key: str, kid: int, aid: int) -> None:
    _meta_set(session, CURSOR_KEY, f"{walk_key}:{int(kid)}:{int(aid)}")


def _done_get(session: Any) -> str | None:
    from src.database.models import DerivedMeta

    raw = session.query(DerivedMeta.value).filter(DerivedMeta.key == DONE_KEY).scalar()
    return str(raw) if raw else None


# ---------------------------------------------------------------------------------- the pass


def hidden_keyword_ids(session: Any, words: Any = None) -> list[int]:
    """Ids of the keyword rows whose normalized term is on the shipped list (or on ``words``),
    ascending."""
    from src.analytics.extract import global_stopwords
    from src.database.models import Keyword

    words = sorted(global_stopwords() if words is None else words)
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
    restored: frozenset[int] = frozenset(),
) -> dict:
    """Read, decide and write one chunk inside the caller's transaction (the write window is
    already held). The chunk covers up to ``n`` mention rows of the hidden keywords from
    ``ids[pos]`` (resuming after article ``after``), moving to the next keyword when one is
    exhausted, so a keyword with few mentions does not cost a transaction of its own.

    ``seen`` (optional) holds the articles already reached in this pass: the walk meets an article
    first at its LOWEST hidden keyword, so a later meeting needs no read at all. It only saves reads;
    after a resume it starts empty and the lowest-keyword test below still keeps each article to one
    handling.

    ``restored`` holds the keywords a previous run hid and the list no longer holds: an article
    reached through one is also filled when its stored columns are NULL. EVERY reached article is
    recomputed from its mentions and compared with what is stored: there is no shortcut (see the
    module docstring).

    Returns the new position ``(pos, after)`` and the counts."""
    from sqlalchemy import bindparam, select

    from src.analytics.store import top_keyword_of
    from src.database.derived_views import KeywordMentionRead as KM
    from src.database.models import Article

    out = {"scanned": 0, "handled_later": 0, "never_computed": 0,
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
            contrib[int(aid)][int(k)] = contrib[int(aid)].get(int(k), 0) + int(c)
    new_of: dict[int, tuple[int | None, int | None, int | None]] = {}
    via_restored: set[int] = set()
    for kid, aid in found:
        cont = contrib.get(aid, {})
        walked = [k for k in cont if k in hidden or k in restored]
        if not walked or min(walked) != kid:
            out["handled_later"] += 1  # its lowest walked keyword is another one
            continue
        visible = {k: c for k, c in cont.items() if k not in hidden}
        if any(k in restored for k in walked):  # a restored word also fills a NULL
            via_restored.add(aid)
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
        if old is None or (old[1] is None and aid not in via_restored):
            # (An article reached through a restored word is filled even when its columns are
            # NULL: an article with only hidden words was written NULL by an earlier pass, which
            # is indistinguishable from "never computed", and the value is a function of its mentions.)
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
        if _is_current(read_state(), fp) and _database_current(fp):
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


def _database_current(fp: str) -> bool:
    """The DATABASE says the list is finished: it carries the finished fingerprint and no cursor (a
    cursor is a pass in flight; a copy taken mid-pass carries one)."""
    from src.database.models import DerivedMeta
    from src.database.session import session_scope

    with session_scope() as session:
        if _done_get(session) != fp:
            return False
        return session.query(DerivedMeta.key).filter(DerivedMeta.key == CURSOR_KEY).first() is None


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
        "handled_later": 0,
        "to_none": 0,
        "chunks": 0,
        "write_window_s": 0.0,
        "max_window_s": 0.0,
        "complete": False,
        "stopped_by": None,
    }
    from src.analytics.extract import global_stopwords

    shipped = set(global_stopwords())
    state = read_state()
    finished_words = _words_of(state.get("words"))
    pending = _pending_of(state)
    with session_scope() as session:  # a short read of its own; nothing spans two chunks
        require_mentions_view(session)
        done_here = _done_get(session)
        # The baseline is KNOWN only when the file and the database agree on the last finished run
        # and the file's lists are readable; otherwise the words taken off the list since cannot be
        # found (see the module docstring).
        known = (
            finished_words is not None
            and pending is not None
            and done_here is not None
            and state.get("fingerprint") == done_here
        )
        taken_off = ((finished_words or set()) | (pending or set())) - shipped if known else set()
        hidden_ids = hidden_keyword_ids(session)
        restored_ids = hidden_keyword_ids(session, taken_off) if taken_off else []
        ids = sorted(set(hidden_ids) | set(restored_ids))
        # The cursor belongs to the WALK, not only to the list: the same list can be walked with a
        # larger plan (restored words below the cursor) than the pass that left it, and resuming there
        # would skip them. The plan is part of its key.
        plan = hashlib.sha256(f"{known}|{','.join(sorted(taken_off))}".encode()).hexdigest()[:16]
        walk_key = f"{fp}.{plan}"
        kid0, after0 = _cursor_get(session, walk_key)
    # Before the first chunk commits, every list this walk is about to leave tops under is recorded
    # (a checked write): a stop, a crash or a later change of list can then still account for them.
    walked = (pending or set()) | shipped
    if walked != pending:
        # A garbled record is replaced WITHOUT the finished fingerprint and words: what it truncated
        # cannot be rebuilt, so the next attempt must read as unknown, not as known with a short lineage.
        base = state if pending is not None else {
            k: v for k, v in state.items() if k not in ("fingerprint", "words")
        }
        if not _write_state({**base, "words_pending": sorted(walked)}):
            return {"skipped": "state_unwritable", "complete": False}
    tally["baseline_known"] = known
    tally["hidden_keywords"] = len(hidden_ids)
    tally["restored_keywords"] = len(set(restored_ids) - set(hidden_ids))
    tally["resumed_at"] = [kid0, after0] if (kid0 or after0) else None
    hidden = frozenset(hidden_ids)
    restored = frozenset(restored_ids) - hidden
    n = START_CHUNK
    seen: set[int] = set()
    pos = bisect.bisect_left(ids, kid0)
    after = after0 if pos < len(ids) and ids[pos] == kid0 else 0
    while pos < len(ids):
        reason = "stop" if stop() else _guard_reason()
        # The budget is checked once a chunk has run: a budget shorter than one chunk must still
        # make progress, or every pass would record itself and the offline timer would loop on it.
        if reason is None and tally["chunks"] > 0 and budget > 0 and time.monotonic() - t0 > budget:
            reason = "budget"
        if reason:
            tally["stopped_by"] = reason
            _finish(tally, fp)
            return tally
        with session_scope() as session:
            hold_write_window(session)
            held0 = time.monotonic()  # the window others wait behind: gate held to commit
            got = _one_chunk(session, ids, pos, after, n, hidden, seen, restored)
            pos, after = got["pos"], got["after"]
            _cursor_set(session, walk_key, ids[pos] if pos < len(ids) else ids[-1] + 1, after)
        held = time.monotonic() - held0
        tally["chunks"] += 1
        tally["write_window_s"] = round(tally["write_window_s"] + held, 3)
        tally["max_window_s"] = round(max(tally["max_window_s"], held), 3)
        for key in ("scanned", "updated", "already_clean", "never_computed",
                    "handled_later", "to_none"):
            tally[key] += got[key]
        n = next_chunk_size(n, held)
    with session_scope() as session:  # the walk is done: a cursor must not outlive its fingerprint
        hold_write_window(session)
        row = session.get(DerivedMeta, CURSOR_KEY)
        if row is not None:
            session.delete(row)
        _meta_set(session, DONE_KEY, fp)  # in the same transaction: the data carries its baseline
    tally["complete"] = True
    tally["chunk_size_at_end"] = n
    _finish(tally, fp)
    return tally


def _finish(tally: dict, fp: str) -> None:
    """Record the pass; the fingerprint only when the walk is complete."""
    state = read_state()
    last = dict(tally)  # carries the fingerprint the pass ran on: a stopped pass names its list
    doc = {**state, "last_pass": last, "list_size": None}
    try:
        from src.analytics.extract import global_stopwords

        words = global_stopwords()
        doc["list_size"] = len(words)
    except Exception:  # noqa: BLE001
        words = None
    if tally.get("complete"):
        doc["fingerprint"] = fp
        doc["completed_at"] = tally["at"]
        doc.pop("words_pending", None)  # everything walked is now accounted for
        if words is not None:
            doc["words"] = sorted(words)  # the list this run finished: the next one finds what left it
    _write_state(doc)
    _LOG.info("stoplist recompute: %s", last)
