"""S04-06 S6 — the consented, refusing, in-app Wikidata ring load (Q406 = b, Q407, Q408, R8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Until now the only way to grow the ring table was ``scripts/generate_wikidata_rings.py``
on a networked machine, spliced in by hand. Q406 = b rules that the app may load rings
ITSELF, without a review step. This is that job, and almost all of it is refusals.

**WHAT IT DOES.** Takes the ring GAP -- the keywords this corpus actually shows a reader
that no ring covers, worst-covered language first (Q407 = a) -- and for each one asks
Wikidata for an item in the TERM'S OWN language, then for that item's labels and aliases
in all twelve (Q408 = a). What comes back becomes a ring in the operator's OWN local ring
file, where ``equivalence.load_rings`` reads it FIRST and therefore at the LOWEST
precedence: a curated ring still wins, which is the whole reason auto-loading without
review is safe to do at all.

**THE RATE IS A GATE, NOT A SLEEP (R8).** R8 says "<= 1 request per 10 seconds", and a
``sleep(10)`` at the bottom of a loop does not say that -- it says "10 s per ITEM", which
is 2 requests per 10 s here, because Q408's pattern is two calls per concept.
:class:`RateGate` spaces successive REQUESTS instead, so the guarantee is the one R8
states however many calls an item turns out to need. (``generate_wikidata_rings.py``
still sleeps per seed; that is the script's own recorded shape and its wall-time estimate
rests on it, so it is not silently changed from here.)

**EVERY REFUSAL IS NAMED.** Airplane mode refuses before a session is even constructed and
says airplane mode did it -- invariant #14e's corollary, written after a probe reported a
kill-switch refusal as "size check failed" and pointed an operator at someone else's
server. A term with no item, an item with fewer than two languages, a request that
raises: each is counted under its own name and none of them aborts the batch.

**IT FABRICATES NOTHING.** No ring is written from a term we could not resolve, no QID is
invented (a ring here always has one -- that is what distinguishes it from a curated ring,
which honestly has none), and the counts this returns are counts, never a coverage score.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.analytics import equivalence
from src.analytics.wikidata_rings import (
    LANGS,
    POLITE_SLEEP_S,
    build_ring,
    parse_entity,
    parse_search,
    wbentities_url,
    wbsearch_url,
)

_LOG = logging.getLogger(__name__)

#: The bot User-Agent. Wikimedia's API policy mandates a descriptive one, and the honest
#: bot UA is a non-negotiable of this project besides -- the same string family the
#: generator script sends, so the operator's two paths are recognisable as one app.
USER_AGENT = "OpenOmniscience-ring-loader/0.1 (local-first research app)"

_TIMEOUT_S = 20

#: How many keywords one gap read will look at, most-cited first.
#:
#: THE RECORDED DEATH-SPIRAL (field test 2026-07-08, Item 8): on a large encrypted corpus
#: an ungated whole-table scan is what makes a request never return, and this one rides an
#: endpoint the Advanced panel calls on open. The cap does not distort the ANSWER's head --
#: the rows are ordered by article spread, which is the order Q407 asks for, so the top
#: `_SCAN_CAP` rows ARE the most-frequent untranslated keywords. It bounds the tail, and
#: :func:`gap_summary` reports whether the cap bit rather than leaving a capped count to
#: read as a complete one.
_SCAN_CAP = 20_000

#: WHAT COUNTS AS A RING CANDIDATE -- one definition, read by both consumers.
#:
#: These began in ``src/api/diagnostics/keywords.py``, where the gap digest was their only
#: reader. This job is the second, and the first draft imported them FROM there: an
#: ``src/analytics/`` module reaching up into ``src/api/``, which would have been the only
#: such import in the package. Layering is the reason they live here instead -- the API
#: layer imports the analytics layer everywhere in this tree, and nothing imports back --
#: and one definition is the reason they are not simply retyped: two copies would let this
#: job work a different list from the one the digest shows the operator.
RING_CAND_PER_LANG = 60     # top gap concepts surfaced per language
RING_CAND_MIN_ARTICLES = 3  # enough spread to be worth a Wikidata QID resolution


def _digest_thresholds() -> tuple[int, int]:
    return RING_CAND_MIN_ARTICLES, RING_CAND_PER_LANG


#: What a SKIP is called. Strings, because they are counted and reported to a surface that
#: must be able to say which one happened without re-deriving it from a message. The
#: airplane refusal is deliberately NOT one of these: it raises rather than being tallied,
#: because it stops the whole load instead of costing it one candidate, and a constant here
#: for it would have claimed a place in a tally it never reaches.
SKIP_NO_ITEM = "no_item"
SKIP_ONE_LANGUAGE = "one_language"
SKIP_ERROR = "error"


class AirplaneRefusal(RuntimeError):
    """The kill switch refused this load, and says so in as many words."""


@dataclass
class RateGate:
    """At most one request per :attr:`min_interval_s`, measured between REQUESTS.

    The clock and the sleeper are injectable because the alternative is a test that
    proves the spacing by taking ten real seconds -- which is a test nobody runs, so it
    is a guarantee nobody checks. ``stop`` lets a cancel interrupt the wait instead of
    making the operator watch a Cancel button do nothing for ten seconds.
    """

    min_interval_s: float = POLITE_SLEEP_S
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Any] = time.sleep
    stop: Callable[[], bool] | None = None
    _last: float | None = field(default=None, init=False)
    #: Every interval this gate actually enforced, for the test that proves R8 rather
    #: than trusting it. Bounded: a long run must not grow a list forever.
    waits: list[float] = field(default_factory=list, init=False)

    def wait(self) -> float:
        """Block until the next request is allowed. Returns the seconds waited."""
        now = self.clock()
        if self._last is None:
            # The first request waits for nothing, and that zero is RECORDED like every
            # other interval: a list that starts at the second call reports n-1 waits for
            # n requests, which is an off-by-one in the only evidence the rate has.
            self._last = now
            self._note(0.0)
            return 0.0
        due = self._last + self.min_interval_s
        waited = 0.0
        while now < due:
            if self.stop is not None and self.stop():
                break
            step = min(0.25, due - now)
            self.sleep(step)
            waited += step
            now = self.clock()
        # ALWAYS the later of the two, and never a second `stop()` call. The previous form
        # was `max(now, due) if not (self.stop and self.stop()) else now`, which asked the
        # caller's predicate again -- a predicate that may count its invocations -- and
        # whose two branches both evaluated to `now`: the loop exits only when `now >= due`
        # (so the max is `now`) or on a cancel break (where the else gave `now`). Taking
        # the max unconditionally also means a wait cut short by a cancel cannot let the
        # next request leave early, which is the safe direction for a politeness rate.
        self._last = max(now, due)
        self._note(waited)
        return waited

    def _note(self, waited: float) -> None:
        # Bounded: a 67-hour run must not grow a list forever. It stops recording rather
        # than dropping the oldest, so what is there is always the run's OPENING intervals
        # -- the ones a reader checks -- never a window that quietly slid.
        if len(self.waits) < 5000:
            self.waits.append(waited)


@dataclass(frozen=True)
class Candidate:
    """One gap concept: what to search, and in which language."""

    term: str
    normalized: str
    language: str
    articles: int
    mentions: int


def gap_candidates(
    session,
    *,
    limit: int = 50,
    languages: Iterable[str] | None = None,
    stats: dict | None = None,
) -> list[Candidate]:
    """Q407 = a: the keywords with no ring, worst-covered language first.

    THE SAME RULE AS THE DIAGNOSTICS DIGEST, and not the same code: ``_ring_candidates``
    is a pure function over the keyword LOG's intermediates, reachable only by building
    that whole export (every keyword, the families, the language signatures), which is
    minutes of work to answer a question this job asks in one query. So the ordering rule
    is reproduced against the database and the thresholds are IMPORTED from it, so the two
    cannot disagree about what counts as a candidate.

    Excluded, each for its own reason: entities (an acronym resolves ambiguously on
    Wikidata -- the homograph garbage vetting had to drop), hidden terms (the operator
    already said these are not keywords), terms below the article floor (not enough
    spread to be worth an item), and terms already in a ring (the point is to resolve
    NEW concepts, not re-resolve the table we have).

    Bounded at :data:`_SCAN_CAP` keywords, most-cited first -- see that constant for why
    the bound cannot move the head of the answer. ``stats`` is filled with ``{"scanned"}``,
    the number of rows the query actually returned, because NOTHING ABOVE THIS FUNCTION CAN
    SEE IT: the returned list is bounded by the per-language cap (60 x the languages
    present), so ``len(result) >= _SCAN_CAP`` is a comparison that can never be true and a
    "capped" flag built on it would report nothing while reading like a measurement.
    """
    from sqlalchemy import func, select

    from src.analytics.queries import _hidden_predicate
    from src.database.models import Keyword

    min_articles, per_lang = _digest_thresholds()
    is_hidden = _hidden_predicate()
    want = {str(x).strip().casefold() for x in languages} if languages else None

    rows = session.execute(
        select(
            Keyword.term,
            Keyword.normalized_term,
            Keyword.language,
            Keyword.article_count,
            Keyword.mention_count,
        )
        .where(
            Keyword.is_entity.is_(False),
            Keyword.language.is_not(None),
            func.coalesce(Keyword.article_count, 0) >= min_articles,
        )
        .order_by(func.coalesce(Keyword.article_count, 0).desc(),
                  func.coalesce(Keyword.mention_count, 0).desc())
        .limit(_SCAN_CAP)
    ).all()
    if stats is not None:
        stats["scanned"] = len(rows)

    by_lang: dict[str, list[Candidate]] = {}
    gated: dict[str, int] = {}
    covered: dict[str, int] = {}
    for term, norm, lang, articles, mentions in rows:
        code = (lang or "").strip().casefold()
        if not code or not norm or is_hidden(norm):
            continue
        if want is not None and code not in want:
            continue
        gated[code] = gated.get(code, 0) + 1
        if equivalence.ring_of(code, norm) is not None:
            covered[code] = covered.get(code, 0) + 1
            continue
        bucket = by_lang.setdefault(code, [])
        if len(bucket) < per_lang:
            bucket.append(
                Candidate(term=term, normalized=norm, language=code,
                          articles=int(articles or 0), mentions=int(mentions or 0))
            )

    # Lowest coverage first (where a ring helps most), then the larger gap -- the digest's
    # own ordering, so the operator's worklist and this job's worklist agree.
    def _coverage(code: str) -> float:
        g = gated.get(code, 0)
        return (covered.get(code, 0) / g) if g else 0.0

    ordered = sorted(by_lang, key=lambda c: (_coverage(c), -len(by_lang[c])))
    out: list[Candidate] = []
    # Round-robin across languages rather than draining the worst one first: a `limit` of
    # 20 against one enormous gap would otherwise spend the whole budget on a single
    # language and report, truthfully, that it improved nothing anywhere else.
    depth = 0
    while len(out) < limit and any(len(by_lang[c]) > depth for c in ordered):
        for code in ordered:
            if len(out) >= limit:
                break
            if len(by_lang[code]) > depth:
                out.append(by_lang[code][depth])
        depth += 1
    return out[:limit]


def gap_summary(session, *, languages: Iterable[str] | None = None) -> dict:
    """What a load WOULD ask for, computed entirely from the local index.

    Deliberately NOT gated by ``ensureOnline`` and the only preview in this slice that is
    not: invariant #14e says to gate every estimate that runs BEFORE an action *because
    those egress first*, and this one does not egress -- it reads keywords and rings off
    the disk. The rule is about egress, not about the word "preview", so the honest thing
    is to say here, at the function, that nothing leaves the machine.
    """
    scan: dict = {}
    cands = gap_candidates(session, limit=_SCAN_CAP, languages=languages, stats=scan)
    per_lang: dict[str, int] = {}
    for c in cands:
        per_lang[c.language] = per_lang.get(c.language, 0) + 1
    return {
        "candidates": len(cands),
        "per_language": dict(sorted(per_lang.items(), key=lambda kv: -kv[1])),
        "rings_held": len(equivalence.load_rings()),
        "seconds_per_candidate": POLITE_SLEEP_S * 2,
        "scan_cap": _SCAN_CAP,
        "scanned": int(scan.get("scanned") or 0),
        # Read off the SCAN, not off the returned list: the list is bounded by the
        # per-language cap long before the scan cap, so `len(cands) >= _SCAN_CAP` was a
        # comparison that could never be true -- a flag that reads like a measurement and
        # measures nothing, which is worse than not having one.
        "capped": int(scan.get("scanned") or 0) >= _SCAN_CAP,
        "method": (
            "Keywords in this corpus that no ring covers, worst-covered language first "
            "(the ring-gap digest's own rule and thresholds), over the "
            f"{_SCAN_CAP:,} most-cited keywords. Counts only -- never a coverage score. "
            "No network call was made to produce this: it reads the local keyword index "
            "and the local ring files. Each candidate costs two Wikidata requests at one "
            "request per 10 seconds, the rate Wikidata's automated-access policy is "
            "honoured at."
        ),
    }


def _default_getter(url: str) -> dict:
    """A guarded GET returning parsed JSON.

    ``guarded_session`` is the one fetch path: it refuses under the kill switch, routes
    through the operator's proxy when protected mode is on (never a silent Tor -> clearnet
    downgrade, Q1014) and carries the honest bot UA. A per-URL isolation token gives each
    lookup its own circuit, so two lookups are unlinkable over Tor.
    """
    import json

    from src.safety.fetcher import guarded_session

    resp = guarded_session(user_agent=USER_AGENT, isolation_token=url).get(url, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    return json.loads(resp.text)


def load_rings_from_wikidata(
    candidates: list[Candidate],
    *,
    get: Callable[[str], dict] | None = None,
    gate: RateGate | None = None,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    write: bool = True,
) -> dict:
    """Resolve ``candidates`` into rings and merge them into the LOCAL ring file.

    **NOT** ``equivalence.load_rings``, which parses the ring FILES and is what every
    read path calls. The first draft of this module named it ``load_rings`` too, and two
    functions of one name in one package is the recorded shape where a reader -- or a
    later edit -- reaches for the wrong one; the qualified call below (``equivalence.
    load_rings()``, three lines into the same file) is exactly how close the two came.

    Refuses up front under airplane mode, by name. One candidate's failure never aborts
    the batch. Returns counts with the method stated -- never a success rate, because the
    denominator ("concepts Wikidata should have had") is not a number anyone has.
    """
    from src.ingest import kill_switch_active

    # Before a session exists, so the refusal is testable with no socket anywhere near it.
    if kill_switch_active():
        raise AirplaneRefusal(
            "network refused: airplane mode is engaged (the Wikidata ring load makes no "
            "request while the kill switch is on)"
        )

    getter = get or _default_getter
    rg = gate or RateGate(stop=should_stop)
    rings: list[dict] = []
    skipped: dict[str, int] = {}
    total = len(candidates)
    stopped = False

    for i, cand in enumerate(candidates):
        if should_stop is not None and should_stop():
            stopped = True
            break
        if progress is not None:
            progress(i, total, cand.term)
        try:
            rg.wait()
            qid = parse_search(getter(wbsearch_url(cand.normalized, cand.language)))
            if not qid:
                skipped[SKIP_NO_ITEM] = skipped.get(SKIP_NO_ITEM, 0) + 1
                continue
            rg.wait()
            lang_terms = parse_entity(getter(wbentities_url(qid)), qid, LANGS)
            ring = build_ring(cand.normalized, qid, lang_terms)
            if ring is None:
                skipped[SKIP_ONE_LANGUAGE] = skipped.get(SKIP_ONE_LANGUAGE, 0) + 1
                continue
            rings.append(ring)
        except Exception as exc:  # noqa: BLE001 - per-candidate resilience, counted and logged
            skipped[SKIP_ERROR] = skipped.get(SKIP_ERROR, 0) + 1
            _LOG.info("ring load: %s (%s) failed: %s", cand.normalized, cand.language, exc)

    written = merge_local_rings(rings) if (write and rings) else 0
    if written:
        equivalence.invalidate_ring_caches()
    return {
        "requested": total,
        "resolved": len(rings),
        "written": written,
        "skipped": dict(sorted(skipped.items())),
        "stopped": stopped,
        "rings": [r["id"] for r in rings],
        "method": (
            "Each candidate was searched on Wikidata in its own language and, when an "
            "item was found, that item's labels and aliases were read in the app's twelve "
            "languages; a concept resolving to fewer than two languages is not written, "
            "because a one-language ring merges nothing. Requests are spaced at one per "
            f"{POLITE_SLEEP_S:.0f} seconds. Counts only -- the share of candidates that "
            "resolve is not a quality measure of anything."
        ),
        "caveat": (
            "These rings come from Wikidata and were NOT reviewed by anyone. They are "
            "written to this install's own ring file, which is read at the LOWEST "
            "precedence: a hand-curated ring always wins. Edit or delete the file to "
            "undo a load."
        ),
    }


#: One writer at a time. Two loads racing on the same YAML file is the classic
#: read-modify-write loss, and this file is the operator's own data.
_WRITE_LOCK = threading.RLock()


def merge_local_rings(rings: list[dict], path: Path | None = None) -> int:
    """MERGE ``rings`` into the local ring file. Returns how many rows were added/updated.

    **Merge, never replace.** The generator script overwrites its ``-o`` target, which is
    correct for a file the operator then splices by hand and catastrophic for this one:
    the local file is where a RESTORED backup's rings also land (Q409 = b), so a load that
    truncated it would delete rings this app did not create. The recorded near-miss is the
    script's own docstring, which said "augments" for months while the code overwrote.

    Written through a temporary file and one rename, so an interrupted write leaves the
    previous file intact rather than a half-parsed one.
    """
    import yaml

    target = path or equivalence.local_rings_path()
    with _WRITE_LOCK:
        existing: dict[str, dict] = {}
        if target.exists():
            try:
                doc = yaml.safe_load(target.read_text("utf-8")) or {}
                for r in doc.get("rings") or []:
                    rid = str(r.get("id") or "").strip()
                    if rid:
                        existing[rid] = r
            except (OSError, yaml.YAMLError):
                # An unreadable local file is not a reason to destroy it. Refuse the
                # merge instead: the operator keeps whatever is there to repair.
                _LOG.warning("local ring file is unreadable; refusing to merge over it: %s", target)
                return 0
        added = 0
        for ring in rings:
            rid = str(ring.get("id") or "").strip()
            if not rid or len(ring.get("members") or []) < 2:
                continue
            row = dict(ring)
            row["source"] = "wikidata"
            row["note"] = "loaded from Wikidata, unreviewed"
            existing[rid] = row
            added += 1
        if not added:
            return 0
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump(
                {"rings": [existing[k] for k in sorted(existing)]},
                allow_unicode=True, sort_keys=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(target)
        return added
