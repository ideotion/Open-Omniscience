"""The keyword FOLD job: re-key keywords written before lemmatisation (Q416 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

**THE RULING.** Q416 = a (2026-09-15, gate row M): *"Add ``simplemma`` to the core
dependencies; lemmatise at extraction; a migration re-normalises existing keywords under a
job."* PR #1148 did the first two: since then extraction files ``studies`` under ``study``.
Every article indexed before it still carries ``studies`` as its own keyword, so the same
word is split across two rows -- one for old articles, one for new -- until each old article
is re-indexed. This job removes that split without re-indexing: it re-keys the stored
mentions, reading no article text.

**THE INVARIANT: THE JOB KEYS A MENTION EXACTLY AS A RE-INDEX WOULD.** For every mention of a
single-word term, the target is :func:`src.analytics.extract.lemma_key` -- the function
extraction itself calls -- under the language extraction used for that article
(:class:`~src.analytics.article_lang_map.ArticleLanguageMap`, ``"en"`` when the article has
none, exactly as ``index_article`` does). A mention whose key does not change is not touched.
``tests/test_keyword_fold.py`` pins this against a real re-index of the same articles.

**WHAT MOVES, ROW BY ROW** (one page of a keyword's mentions, in ONE transaction under the
single-writer gate, read and write alike so no other writer can change a row between the two):

* a mention whose article has no row for the target yet is repointed to the target;
* a mention whose article already has one is FOLDED into it -- counts summed, the earlier
  first offset kept -- because the unique ``(keyword_id, article_id)`` index allows one row,
  and that is the row extraction would have produced;
* both keywords' ``mention_count`` / ``article_count`` move by the exact deltas;
* the article's own top keyword is recomputed from its mentions and written only if it
  changed;
* the source keyword's USER tags are copied to the target (never its ``baseline`` tags: a
  baseline tag asserts that the curated list named THAT form, and copying it would claim the
  list named the other one).

**WHAT IS NEVER DONE.** No keyword row is deleted: a keyword left with no mentions is exactly
the orphan the existing cleanup already prunes (``prune_orphan_keywords``, every 12 hours),
through the path that already handles its references. A phrase, an entity (``WHO`` is not a
plural) and a keyword that one of the user's families or super-groups names are left as they
are and counted -- the last one because silently emptying a keyword the user curated would
rewrite their structure behind their back. The job refuses to start when lemmatisation at
extraction is off: folding would then file old articles under keys new articles never use.

**THEN THE LANGUAGE.** Once every keyword is folded the job runs
:func:`src.analytics.store.reconcile_keyword_language` (Q413 = a: that pass "runs in the 0.4
gate -- the report is the artifact"), so a target keyword created here takes the majority
language of the mentions it received.

**RESUMABLE.** The cursor is (last keyword finished, keyword in progress, last article id done
inside it), persisted after every page, so a pause, a restart or a crash loses at most one page
of progress and never data: a page is one transaction, and re-running a committed page finds
nothing left to move. The run parks while an import owns the machine, and holds a corpus
lease per page so a restore's file swap waits for it.

**THE REPORT IS THE ARTIFACT.** On completion the tally, the fifty largest folds and the
language pass's own tally are written to ``keyword_fold_report.json`` in the data folder and
served by ``GET /api/insights/keyword-fold-job/report``. Counts only, never a score.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from src.database.corpus_lease import corpus_lease

if TYPE_CHECKING:
    from src.analytics.article_lang_map import ArticleLanguageMap

_LOG = logging.getLogger(__name__)

#: Keyword rows read per classification step.
_KEYWORD_BATCH = 2000
#: Mentions per page -- one transaction under the single-writer gate. Small enough that a
#: live collection waits a fraction of a second for it, large enough to amortise the reads.
_PAGE = 500
#: SQLite bound-variable safety for ``IN (...)``.
_IN_CHUNK = 900
#: The number of largest folds the report names.
_EXAMPLES = 50
#: How many curated keywords the report names (they are counted in full).
_CURATED_SAMPLE = 20
#: The rollup's epoch is bumped at most this often while pages are moving rows (and always
#: once when the fold ends). Every bump forces the columnar rollup to rebuild from scratch.
_EPOCH_BUMP_EVERY_S = 60.0
#: How often a parked job re-checks whether an import still owns the machine.
_EXCLUSIVE_POLL_S = 5.0

_STATE_FILE = "keyword_fold_job.json"
_REPORT_FILE = "keyword_fold_report.json"

#: Why a start was refused. Codes, never exception text: the endpoint maps each one to a
#: fixed sentence, so nothing an exception carries can reach a response.
REFUSED_RUNNING = "already-running"
REFUSED_NO_LEMMATISER = "no-lemmatiser"
REFUSED_LEMMA_OFF = "lemmatisation-off"
REFUSED_NOTHING_PAUSED = "nothing-paused"


class FoldRefused(RuntimeError):
    """A start or resume the job will not do, named by :attr:`code`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --------------------------------------------------------------------------- #
#  The key: which keyword a term's mention belongs to, per language
# --------------------------------------------------------------------------- #


@dataclass
class FoldRules:
    """Everything :func:`lemma_key` needs, built ONCE per run.

    ``_stopset`` builds a frozenset union of several thousand words per call; extraction
    pays that once per document, and this job would pay it once per keyword per language.
    ``segmented`` is always False: it only lowers the length floor for a CJK or Thai word,
    and none of the languages the lemmatiser covers is written in either script.
    """

    stops: dict[str, frozenset[str]]
    code_filter: bool
    curated: frozenset[str]

    @classmethod
    def build(cls, session: Session) -> FoldRules:
        from src.analytics.extract import _stopset, code_token_filter_enabled
        from src.analytics.lemma import LEMMA_LANGS
        from src.database.models import KeywordFamilyOverride, KeywordSuperGroupMember

        curated = {t for (t,) in session.query(KeywordFamilyOverride.normalized_term)} | {
            t for (t,) in session.query(KeywordSuperGroupMember.normalized_term)
        }
        return cls(
            stops={lg: _stopset(lg) for lg in LEMMA_LANGS},
            code_filter=code_token_filter_enabled(),
            curated=frozenset(curated),
        )

    def target(self, term: str, language: str) -> str:
        """The key extraction would file ``term`` under for an article in ``language``."""
        from src.analytics.extract import lemma_key

        stop = self.stops.get(language)
        if stop is None:  # a language the lemmatiser does not cover: always a no-op
            return term
        return lemma_key(term, language, stop=stop, segmented=False, code_filter=self.code_filter)

    def movable(self, term: str) -> dict[str, str]:
        """``{language: target}`` for every covered language under which ``term`` moves."""
        out: dict[str, str] = {}
        for lg in self.stops:
            t = self.target(term, lg)
            if t != term:
                out[lg] = t
        return out


def refusal() -> str | None:
    """Why the fold cannot run in this install, or None. The same probe extraction uses."""
    from src.analytics.lemma import extraction_lemma_enabled, lemmatizer_available

    if not lemmatizer_available():
        return REFUSED_NO_LEMMATISER
    if not extraction_lemma_enabled():
        return REFUSED_LEMMA_OFF
    return None


# --------------------------------------------------------------------------- #
#  One page of one keyword's mentions
# --------------------------------------------------------------------------- #


@dataclass
class _Source:
    id: int
    term: str  # the display form, kept for a target this page has to create
    normalized: str
    extractor: str | None
    targets: dict[str, str]  # language -> target key, only for languages that move


@dataclass
class PageResult:
    last_article_id: int | None  # None: the keyword had no rows after the cursor
    done: bool
    rows: int = 0
    stayed: int = 0
    moved: int = 0  # repointed to a target that had no row in that article
    merged: int = 0  # folded into the target's existing row in that article
    targets_created: int = 0
    tops_updated: int = 0
    tags_copied: int = 0
    by_language: Counter = field(default_factory=Counter)  # language -> mention rows
    by_target: Counter = field(default_factory=Counter)  # "lang\ttarget" -> mention rows


def _chunks(seq: list, n: int = _IN_CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def fold_page(
    session: Session,
    src: _Source,
    *,
    after_article_id: int,
    langs: ArticleLanguageMap,
    page: int = _PAGE,
    copied_pairs: set[tuple[int, int]] | None = None,
) -> PageResult:
    """Fold ONE page of ``src``'s mentions (those with ``article_id > after_article_id``).

    The read and the writes share one transaction under the single-writer gate: the rows
    decided on are the rows written, whatever else is running. Committed before return.
    """
    from src.analytics.extract import ExtractedTerm
    from src.analytics.store import _get_or_create_keyword, _prefetch_keywords, top_keyword_of
    from src.database.models import Article, Keyword, KeywordMention, KeywordTag
    from src.database.writer import write_lock

    with write_lock():
        rows = session.execute(
            text(
                "SELECT id, article_id, language, count, first_offset FROM keyword_mentions "
                "WHERE keyword_id = :k AND article_id > :a ORDER BY article_id LIMIT :n"
            ),
            {"k": src.id, "a": after_article_id, "n": page},
        ).fetchall()
        if not rows:
            session.commit()  # end the read transaction; nothing else to do
            return PageResult(last_article_id=None, done=True)
        res = PageResult(
            last_article_id=int(rows[-1][1]), done=len(rows) < page, rows=len(rows)
        )

        moving: list[tuple[int, int, int, int | None, str, str, str | None]] = []
        for mid, aid, mlang, cnt, off in rows:
            aid = int(aid)
            lang = mlang or langs.extraction_language(aid)
            target = src.targets.get(lang)
            if target is None:
                res.stayed += 1
                continue
            real_lang = mlang or langs.mention_language(aid)
            moving.append((int(mid), aid, int(cnt or 0), off, target, lang, real_lang))
        if not moving:
            session.commit()
            return res

        # 1) the target keyword rows: the lowest id per term, as extraction resolves them,
        # created (with extraction's own get-or-create) when the corpus has none yet.
        wanted = sorted({m[4] for m in moving})
        found = _prefetch_keywords(session, wanted)
        tid: dict[str, int] = {}
        for term in wanted:
            kw = found.get(term)
            if kw is None:
                first_lang = next((m[6] for m in moving if m[4] == term and m[6]), None)
                kw = _get_or_create_keyword(
                    session,
                    ExtractedTerm(term=src.term, normalized=term, kind="term", count=0, first_offset=None),
                    language=first_lang,
                    extractor=src.extractor or "baseline",
                    prefetched=found,
                )
                res.targets_created += 1
            tid[term] = int(kw.id)

        aids = sorted({m[1] for m in moving})
        tids = sorted(set(tid.values()))
        # 2) the targets' existing rows in these articles, and 3) every mention of these
        # articles (the covering article index), for their top keyword before and after.
        existing: dict[tuple[int, int], tuple[int, int, int | None]] = {}
        contrib: dict[int, dict[int, int]] = {a: {} for a in aids}
        for chunk in _chunks(aids):
            for mid, kid, aid, cnt, off in session.query(
                KeywordMention.id,
                KeywordMention.keyword_id,
                KeywordMention.article_id,
                KeywordMention.count,
                KeywordMention.first_offset,
            ).filter(KeywordMention.article_id.in_(chunk), KeywordMention.keyword_id.in_(tids)):
                existing[(int(kid), int(aid))] = (int(mid), int(cnt or 0), off)
            for aid, kid, cnt in session.query(
                KeywordMention.article_id, KeywordMention.keyword_id, KeywordMention.count
            ).filter(KeywordMention.article_id.in_(chunk)):
                c = contrib[int(aid)]
                c[int(kid)] = c.get(int(kid), 0) + int(cnt or 0)
        before = {a: top_keyword_of(contrib[a]) for a in aids}

        plain: dict[int, list[int]] = {}
        folds: list[dict[str, Any]] = []
        drop: list[int] = []
        d_men: Counter = Counter()
        d_art: Counter = Counter()
        for mid, aid, cnt, off, target, lang, _real in moving:
            t = tid[target]
            prev = existing.get((t, aid))
            if prev is not None:
                pmid, pcnt, poff = prev
                offs = [o for o in (poff, off) if o is not None]
                folds.append({"id": pmid, "count": pcnt + cnt, "first_offset": min(offs) if offs else None})
                existing[(t, aid)] = (pmid, pcnt + cnt, min(offs) if offs else None)
                drop.append(mid)
                res.merged += 1
            else:
                plain.setdefault(t, []).append(mid)
                existing[(t, aid)] = (mid, cnt, off)
                d_art[t] += 1
                res.moved += 1
            d_men[t] += cnt
            d_men[src.id] -= cnt
            d_art[src.id] -= 1
            c = contrib[aid]
            c.pop(src.id, None)
            c[t] = c.get(t, 0) + cnt
            res.by_language[lang] += 1
            res.by_target[f"{lang}\t{target}"] += 1

        # 4) the writes. Every one goes through Session.execute or a flush, so the write
        # gate's hooks see it; it is also already held, and it is reentrant.
        for t, ids in plain.items():
            for chunk in _chunks(ids):
                session.query(KeywordMention).filter(KeywordMention.id.in_(chunk)).update(
                    {"keyword_id": t}, synchronize_session=False
                )
        if folds:
            session.execute(update(KeywordMention), folds)
        for chunk in _chunks(drop):
            session.query(KeywordMention).filter(KeywordMention.id.in_(chunk)).delete(
                synchronize_session=False
            )
        for kw in session.query(Keyword).filter(Keyword.id.in_(list(d_men))).all():
            kw.mention_count = max(0, (kw.mention_count or 0) + d_men[kw.id])
            kw.article_count = max(0, (kw.article_count or 0) + d_art[kw.id])
        for aid in aids:
            after = top_keyword_of(contrib[aid])
            if after != before[aid]:
                session.query(Article).filter(Article.id == aid).update(
                    {
                        "top_keyword_id": after[0],
                        "top_keyword_count": after[1],
                        "top_keyword_tied_n": after[2],
                    },
                    synchronize_session=False,
                )
                res.tops_updated += 1
        pairs = {(src.id, t) for t in tids}
        if copied_pairs is not None:
            pairs -= copied_pairs
        if pairs:
            user_tags = session.query(KeywordTag.axis, KeywordTag.tag, KeywordTag.source).filter(
                KeywordTag.keyword_id == src.id, KeywordTag.source != "baseline"
            ).all()
            for _s, t in sorted(pairs):
                if user_tags:
                    have = set(
                        session.query(KeywordTag.axis, KeywordTag.tag, KeywordTag.source).filter(
                            KeywordTag.keyword_id == t
                        )
                    )
                    for axis, tag, source in user_tags:
                        if (axis, tag, source) not in have:
                            session.add(KeywordTag(keyword_id=t, axis=axis, tag=tag, source=source))
                            res.tags_copied += 1
                if copied_pairs is not None:
                    copied_pairs.add((src.id, t))
        session.commit()
    return res


# --------------------------------------------------------------------------- #
#  The job
# --------------------------------------------------------------------------- #


def _default_session():
    from src.database.session import SessionLocal

    return SessionLocal()


def _import_owns_the_machine() -> bool:
    """True while an import holds the exclusive window or a restore holds the machine.
    Best-effort: an unreadable scheduler must never park the job forever."""
    try:
        from src.scheduler.runner import exclusive_window_open, get_scheduler

        if exclusive_window_open():
            return True
        return bool(get_scheduler().holds_exclusive())
    except Exception:  # noqa: BLE001 - a courtesy check is never load-bearing
        return False


def _report_path() -> Path:
    from src.paths import data_dir

    return data_dir() / _REPORT_FILE


def last_report() -> dict | None:
    """The report the last COMPLETED run wrote, or None if no run has completed."""
    try:
        return json.loads(_report_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class KeywordFoldJobManager:
    """ONE pausable, resumable fold at a time: the fold, then the language pass."""

    def __init__(self, *, state_path: Path | None = None, report_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._phase = "fold"  # fold -> language
        self._kw_done = 0  # every keyword id <= this is finished
        self._in_kw = 0  # the keyword in progress (0: none)
        self._in_aid = 0  # the last article id folded inside it
        self._in_folds: dict[str, int] = {}  # its "lang\ttarget" -> mentions so far
        self._in_stayed = 0  # its mentions that stayed so far
        self._total = 0  # keywords at start
        self._done = 0  # keywords finished
        self._done_at_start = 0
        self._tally: dict[str, int] = {}
        self._examples: list[dict] = []
        self._curated_sample: list[str] = []
        self._language: dict | None = None
        self._unbumped = False  # rows moved since the last epoch bump
        self._last_bump = 0.0
        self._parked = False
        self._pending: _Source | None = None  # the keyword in progress, when already read
        self._error: str | None = None
        self._cancelled = False
        self._started_at: float | None = None
        self._session_factory: Callable[[], Any] | None = None  # test seam
        self._page = _PAGE  # test seam
        self._state_path_override = state_path
        self._report_path_override = report_path
        self._load_persisted()

    # -- persistence ------------------------------------------------------- #
    def _state_path(self) -> Path:
        if self._state_path_override is not None:
            return self._state_path_override
        from src.paths import data_dir

        return data_dir() / _STATE_FILE

    def _report_file(self) -> Path:
        return self._report_path_override or _report_path()

    def _snapshot(self) -> dict:
        return {
            "state": self._state,
            "phase": self._phase,
            "kw_done": self._kw_done,
            "in_kw": self._in_kw,
            "in_aid": self._in_aid,
            "in_folds": self._in_folds,
            "in_stayed": self._in_stayed,
            "total": self._total,
            "done": self._done,
            "tally": self._tally,
            "examples": self._examples,
            "curated_sample": self._curated_sample,
            "unbumped": self._unbumped,
        }

    def _save(self) -> None:
        """Persist the cursor (best-effort; a write hiccup never breaks the job)."""
        try:
            p = self._state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._snapshot()), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass

    def _clear_state(self) -> None:
        with contextlib.suppress(OSError):
            self._state_path().unlink(missing_ok=True)

    def _load_persisted(self) -> None:
        """Restore an INTERRUPTED run as PAUSED, never silently lost."""
        try:
            d = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if d.get("state") not in ("running", "paused", "error"):
            return
        try:
            self._phase = "language" if d.get("phase") == "language" else "fold"
            self._kw_done = max(0, int(d.get("kw_done") or 0))
            self._in_kw = max(0, int(d.get("in_kw") or 0))
            self._in_aid = max(0, int(d.get("in_aid") or 0))
            self._in_folds = {str(k): int(v) for k, v in (d.get("in_folds") or {}).items()}
            self._in_stayed = max(0, int(d.get("in_stayed") or 0))
            self._total = max(0, int(d.get("total") or 0))
            self._done = max(0, int(d.get("done") or 0))
            self._tally = {str(k): int(v) for k, v in (d.get("tally") or {}).items()}
            self._examples = [dict(e) for e in (d.get("examples") or [])][:_EXAMPLES]
            self._curated_sample = [str(t) for t in (d.get("curated_sample") or [])][:_CURATED_SAMPLE]
            self._unbumped = bool(d.get("unbumped"))
        except (TypeError, ValueError):
            return
        self._state = "paused"

    # -- lifecycle --------------------------------------------------------- #
    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, _session_factory=None, _page: int | None = None) -> dict:
        """Start a FRESH run, or continue a paused one (a paused run is never discarded
        by a start: that is what the re-index job's field report taught)."""
        with self._lock:
            if self._alive():
                raise FoldRefused(REFUSED_RUNNING)
            why = refusal()
            if why is not None:
                raise FoldRefused(why)
            fresh = self._state not in ("paused", "error")
            if fresh:
                self._phase = "fold"
                self._kw_done = self._in_kw = self._in_aid = self._in_stayed = 0
                self._in_folds = {}
                self._tally = {}
                self._examples = []
                self._curated_sample = []
                self._language = None
                self._done = 0
                self._total = 0
                self._unbumped = False
            self._stop.clear()
            self._cancelled = False
            self._state = "running"
            self._error = None
            self._done_at_start = self._done
            self._started_at = time.monotonic()
            self._session_factory = _session_factory
            if _page is not None:
                self._page = max(1, int(_page))
            self._save()
            self._thread = threading.Thread(target=self._run, daemon=True, name="keyword-fold-job")
            self._thread.start()
            return self.status()

    def resume(self) -> dict:
        with self._lock:
            if self._state not in ("paused", "error"):
                raise FoldRefused(REFUSED_NOTHING_PAUSED)
        return self.start(_session_factory=self._session_factory)

    def pause(self) -> None:
        self._stop.set()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._stop.set()
        if not self._alive():
            with self._lock:
                self._state = "cancelled"
                self._clear_state()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker (tests and shutdown)."""
        t = self._thread
        if t is not None:
            t.join(timeout)

    # -- the worker -------------------------------------------------------- #
    def _park(self) -> None:
        try:
            while not self._stop.is_set() and _import_owns_the_machine():
                with self._lock:
                    self._parked = True
                self._stop.wait(_EXCLUSIVE_POLL_S)
        finally:
            with self._lock:
                self._parked = False

    def _add(self, key: str, n: int) -> None:
        if n:
            self._tally[key] = self._tally.get(key, 0) + int(n)

    def _bump(self, session: Session, *, force: bool = False) -> None:
        if not self._unbumped:
            return
        if not force and time.monotonic() - self._last_bump < _EPOCH_BUMP_EVERY_S:
            return
        from src.analytics.corpus_epoch import bump_corpus_epoch

        bump_corpus_epoch(session, reason="keyword_fold")
        self._last_bump = time.monotonic()
        with self._lock:
            self._unbumped = False

    def _finish_keyword(self, from_term: str | None) -> None:
        """Account for the keyword in progress once its last page is done."""
        moved = sum(self._in_folds.values())
        if moved:
            self._add("keywords_folded", 1)
            if self._in_stayed == 0:
                self._add("keywords_emptied", 1)
            for key, n in self._in_folds.items():
                lang, target = key.split("\t", 1)
                self._examples.append(
                    {"from": from_term, "to": target, "lang": lang, "mentions": n}
                )
            self._examples.sort(key=lambda e: (-int(e["mentions"]), str(e["to"])))
            del self._examples[_EXAMPLES:]
        self._kw_done = self._in_kw
        self._in_kw = self._in_aid = self._in_stayed = 0
        self._in_folds = {}
        self._done += 1

    def _classify_step(self, session: Session, rules: FoldRules) -> bool:
        """Read the next keyword batch; finish every keyword that cannot move, stop at the
        first one that can. Returns True when the keyword table is exhausted."""
        rows = session.execute(
            text(
                "SELECT id, term, normalized_term, is_entity, extractor FROM keywords "
                "WHERE id > :c ORDER BY id LIMIT :n"
            ),
            {"c": self._kw_done, "n": _KEYWORD_BATCH},
        ).fetchall()
        session.commit()  # release the read mark between steps
        if not rows:
            return True
        for kid, term, norm, is_entity, extractor in rows:
            kid = int(kid)
            norm = norm or ""
            with self._lock:
                if " " in norm:
                    self._add("skipped_phrase", 1)
                elif is_entity:
                    self._add("skipped_entity", 1)
                else:
                    targets = rules.movable(norm)
                    if not targets:
                        self._add("unchanged", 1)
                    elif norm in rules.curated:
                        self._add("skipped_curated", 1)
                        if len(self._curated_sample) < _CURATED_SAMPLE:
                            self._curated_sample.append(norm)
                    else:
                        self._add("candidates", 1)
                        self._in_kw = kid
                        self._in_aid = 0
                        self._pending = _Source(
                            id=kid, term=term or norm, normalized=norm,
                            extractor=extractor, targets=targets,
                        )
                        return False
                self._kw_done = kid
                self._done += 1
        return len(rows) < _KEYWORD_BATCH

    def _load_source(self, session: Session, rules: FoldRules) -> _Source | None:
        row = session.execute(
            text("SELECT id, term, normalized_term, extractor FROM keywords WHERE id = :k"),
            {"k": self._in_kw},
        ).fetchone()
        session.commit()
        if row is None:  # deleted since the cursor was saved: nothing left to fold
            return None
        norm = row[2] or ""
        return _Source(
            id=int(row[0]), term=row[1] or norm, normalized=norm,
            extractor=row[3], targets=rules.movable(norm),
        )

    def _bump_leased(self, session: Session, *, force: bool = False) -> None:
        with corpus_lease("keyword-fold"):
            self._bump(session, force=force)

    def _should_yield(self) -> bool:
        """Stop the current unit: a pause, a cancel, or an import claiming the machine."""
        return self._stop.is_set() or _import_owns_the_machine()

    def _fold_phase(self, session: Session) -> bool:
        """Returns True when the fold is complete, False when stopped."""
        from src.analytics.article_lang_map import ArticleLanguageMap

        rules = FoldRules.build(session)
        langs = ArticleLanguageMap(session)
        session.commit()
        copied: set[tuple[int, int]] = set()
        self._pending = None
        if self._unbumped:  # a previous run moved rows and stopped before bumping
            self._bump_leased(session, force=True)
        while not self._stop.is_set():
            self._park()
            if self._stop.is_set():
                break
            with corpus_lease("keyword-fold"):
                if not self._in_kw:
                    exhausted = self._classify_step(session, rules)
                    with self._lock:
                        self._save()
                    if exhausted and not self._in_kw:
                        self._bump(session, force=True)
                        return True
                    continue
                src = self._pending
                if src is None or src.id != self._in_kw:
                    src = self._load_source(session, rules)
                    self._pending = src
                if src is None or not src.targets:
                    with self._lock:
                        self._finish_keyword(src.normalized if src else None)
                        self._save()
                    continue
                r = fold_page(
                    session, src, after_article_id=self._in_aid, langs=langs,
                    page=self._page, copied_pairs=copied,
                )
                with self._lock:
                    self._add("mentions_moved", r.moved)
                    self._add("mentions_merged", r.merged)
                    self._add("targets_created", r.targets_created)
                    self._add("articles_top_updated", r.tops_updated)
                    self._add("tags_copied", r.tags_copied)
                    for lang, n in r.by_language.items():
                        self._add(f"lang:{lang}", n)
                    for key, n in r.by_target.items():
                        self._in_folds[key] = self._in_folds.get(key, 0) + int(n)
                    self._in_stayed += r.stayed
                    if r.moved or r.merged:
                        self._unbumped = True
                    if r.last_article_id is not None:
                        self._in_aid = r.last_article_id
                    if r.done:
                        self._finish_keyword(src.normalized)
                    self._save()
                self._bump(session)
        self._bump_leased(session, force=True)
        return False

    def _language_phase(self, session: Session) -> bool:
        """The language pass, stopped between its chunks by a pause OR by an import
        claiming the machine -- one lease held for a whole pass would make a restore's
        swap wait out every chunk -- and re-run from the start after the import, since a
        majority over part of the table is not a majority."""
        from src.analytics.store import reconcile_keyword_language

        while not self._stop.is_set():
            self._park()
            if self._stop.is_set():
                return False
            with corpus_lease("keyword-fold"):
                out = reconcile_keyword_language(session, should_stop=self._should_yield)
            if out.get("complete", True):
                with self._lock:
                    self._language = out
                return True
        return False

    def _write_report(self) -> None:
        from src.analytics.lemma import LEMMA_LANGS, SIMPLEMMA_AS_OF

        report = {
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "keywords_total": self._total,
            "fold": dict(self._tally),
            "largest_folds": list(self._examples),
            "curated_left_unfolded_sample": list(self._curated_sample),
            "language": self._language,
            "lemmatiser": {"simplemma_as_of": SIMPLEMMA_AS_OF, "languages": sorted(LEMMA_LANGS)},
            "method": (
                "Each single-word term mention is re-keyed with the function extraction "
                "uses, under the language extraction used for its article; a mention "
                "whose key does not change is not touched. No article text is read and no "
                "keyword row is deleted; keywords left without mentions are removed by the "
                "regular keyword cleanup. The language pass then sets each keyword's "
                "language to the majority of its mentions' languages."
            ),
        }
        try:
            p = self._report_file()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            _LOG.warning("could not write the keyword fold report", exc_info=True)

    def _count_keywords(self, session: Session) -> int:
        try:
            n = int(session.execute(text("SELECT COUNT(*) FROM keywords")).scalar() or 0)
            session.commit()
            return n
        except Exception:  # noqa: BLE001 - a count hiccup must never stop the job
            session.rollback()
            return 0

    def _run(self) -> None:
        session = (self._session_factory or _default_session)()
        try:
            if not self._total:
                total = self._count_keywords(session)
                with self._lock:
                    self._total = total
                    self._save()
            finished = False
            if self._phase == "fold" and self._fold_phase(session):
                with self._lock:
                    self._phase = "language"
                    self._save()
            if self._phase == "language" and not self._stop.is_set():
                finished = self._language_phase(session)
            with self._lock:
                if finished:
                    self._state = "done"
                    self._write_report()
                    self._clear_state()
                elif self._cancelled:
                    self._state = "cancelled"
                    self._clear_state()
                else:
                    self._state = "paused"
                    self._save()
        except Exception:  # noqa: BLE001 - surface the failure, never crash the thread
            _LOG.exception("keyword fold job failed")
            with contextlib.suppress(Exception):
                session.rollback()
            with self._lock:
                self._state = "error"
                self._error = "failed"  # a code: the log holds the exception, not the API
                self._save()
        finally:
            session.close()

    # -- status ------------------------------------------------------------ #
    def status(self) -> dict:
        with self._lock:
            total, done = self._total, self._done
            eta_s = None
            recent = done - self._done_at_start
            if self._started_at is not None and recent > 0 and total and done < total and self._alive():
                rate = recent / max(0.001, time.monotonic() - self._started_at)
                if rate > 0:
                    eta_s = round((total - done) / rate)
            return {
                "state": self._state,
                "phase": self._phase,
                "keywords_total": total,
                "keywords_done": done,
                "percent": round(100 * min(done, total) / total, 1) if total else 0.0,
                "tally": dict(self._tally),
                "eta_seconds": eta_s,
                "error": self._error,
                "running": self._alive(),
                "parked_for_exclusive": self._parked,
                "refusal": refusal(),
            }


def refusal_code(mgr: KeywordFoldJobManager) -> str:
    """Why ``mgr`` would refuse a start or resume right now, from its STATE.

    The endpoints answer with this rather than with anything read off the raised
    :class:`FoldRefused`, so no exception object ever flows into a response."""
    status = mgr.status()
    if status["running"]:
        return REFUSED_RUNNING
    return refusal() or REFUSED_NOTHING_PAUSED


_MANAGER: KeywordFoldJobManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_fold_manager() -> KeywordFoldJobManager:
    """Process-wide singleton so the job is visible across requests + in /api/jobs."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = KeywordFoldJobManager()
        return _MANAGER
