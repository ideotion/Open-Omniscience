"""
The OFF-SITE HOLD (R728 A and B, field test 2026-11-14): a source whose pages now come from another site.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FINDING. On the 8-instance field test, ``pakembassykabul.org`` (an embassy's site, found by
Wikidata discovery) was still ``qualified`` while every page it served was Indonesian slot-casino
copy: the article URLs were the embassy's, and the fetch was answered, after its redirects, by
``jayaslotjackpot.com``. Qualification judges EXTRACTION validity only, and a casino page extracts
cleanly, so nothing in the app could see it. ``Article.fetched_host`` already recorded where each
page was really answered from (queue item 61) and the reader marks an off-site page one at a time;
nothing acted on it at the level of the source.

THE RULE (R728 A), local and offline: the newest ``WINDOW`` articles of a source are read, and
those with a known ``fetched_host`` are compared, by registrable domain, with the source's own
site (the ONE normaliser, ``src.ingest.host_mismatch._site``: the ICANN part of the Public Suffix
List, IDNA to punycode). No verdict at all below ``MIN_KNOWN`` known hosts. The source is HELD when
ONE other site answered at least half of the known ones and that pair is neither confirmed by the
operator (R193's ``host_mismatch_confirmed`` table) nor on the small shipped list of legitimate
moves below. One site, deliberately: a takeover is one host answering for the whole site, while a
feed that links out to many publishers spreads its off-site pages over many sites and is not a
takeover.

WHAT A HOLD WRITES. The source becomes ``disqualified`` (so collection stops, through the same
gate as any refused source) with an APPEND-ONLY attempt row whose criteria version is
``CRITERIA_VERSION``; the normal re-check ladder applies, and a re-check is judged by this rule
again. Never a delete. Its already-stored articles answered by the other site (and only those)
get the existing REVERSIBLE quarantine mark with reason ``QUARANTINE_REASON`` (R728 B), which keeps
them out of keyword aggregates (R101); articles stored from the source's own site before the
takeover stay as they are. Nothing is re-extracted.

THE WAY BACK. "This is the same outlet" is ``POST /api/quarantine/host-pairs`` (R193), logged as a
confirmed pair; it re-admits the held source (an attempt row with ``CONFIRMED_CRITERIA_VERSION``
and an admission audit row, so the admission can be undone like any other) and lifts the marks
this hold set. Withdrawing the confirmation (``DELETE``) re-checks the source at once. A CANDIDATE
held while being judged (``CANDIDATE_CRITERIA_VERSION``) was never qualified, so confirming it sends
it back to the qualification queue instead of qualifying it unjudged.

THE MARKS ARE OWED WITH THE HOLD: :func:`hold` queues them (a ``derived_meta`` row) in the hold's own
transaction and :func:`apply_pending_marks` sets them afterwards, so a crash in between leaves them
owed to the next run rather than a hold whose articles still feed the aggregates.

WHAT IT CANNOT SEE, stated rather than implied: a takeover that serves its content from the
source's own address (no redirect); one that spreads its redirects over several sites, so no one
answers half; and a move between tenants of one private suffix (``a.github.io`` to ``b.github.io``),
which the ICANN-only normaliser reads as one site. A listed domain alias (``url_utils.DOMAIN_ALIASES``,
``bbc.com`` and ``bbc.co.uk``) is the source's own site, as the reader's per-article note treats it;
a bare IP address and a trailing-dot host are sites like any other.

No score, no network, no name of any source in this file.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from src.database.models import Source

_LOG = logging.getLogger("catalog.off_site")

#: The criteria version of a hold's attempt row: a LABEL in the history, never a trigger.
CRITERIA_VERSION = "oo-off-site-hold-1"
#: The same, for a CANDIDATE held while it was being judged (never qualified): confirming its pair
#: returns it to the qualification queue rather than qualifying it, because its extraction was never
#: judged (security read 2026-11-16).
CANDIDATE_CRITERIA_VERSION = "oo-off-site-hold-candidate-1"
#: Every hold version: a source whose newest attempt carries one of these is held.
HOLD_VERSIONS = (CRITERIA_VERSION, CANDIDATE_CRITERIA_VERSION)
#: The criteria version of the attempt row an operator's "same outlet" confirmation writes.
CONFIRMED_CRITERIA_VERSION = "oo-off-site-confirmed-1"
#: The quarantine reason a hold stamps on the off-site articles (and the only one its release lifts).
QUARANTINE_REASON = "host:off_site"

#: How many of a source's newest stored articles are read (R728 A).
WINDOW = 20
#: No verdict unless at least this many of them have a known fetched host (R728 A's minimum sample).
MIN_KNOWN = 10


class Move(NamedTuple):
    """A known, legitimate move of a whole publisher from one site to another."""

    from_site: str
    to_site: str
    evidence: str


#: SMALL, REVIEWED, EACH ENTRY WITH ITS EVIDENCE (R728 A). Registrable domains as the normaliser
#: names them. A pair not listed here is confirmed by the operator, per source, on the Sources tab.
LEGITIMATE_MOVES: tuple[Move, ...] = (
    Move(
        "revues.org", "openedition.org",
        "Revues.org is the former name of OpenEdition Journals; its journal URLs redirect to "
        "journals.openedition.org. Field test 2026-11-14 report 5.4: most cross-domain fetched hosts on "
        "the instances with the most were revues.org to openedition.org redirects.",
    ),
)
_MOVES = frozenset((m.from_site, m.to_site) for m in LEGITIMATE_MOVES)

#: States of a finding.
HELD = "held"
CLEAR = "clear"
TOO_FEW = "too_few"          # fewer than MIN_KNOWN known hosts in the window: no verdict
UNKNOWN_SITE = "unknown_site"  # the source's own domain names no comparable site: no verdict


class Finding(NamedTuple):
    source_id: int
    state: str
    source_site: str | None
    other_site: str | None   # the most frequent other site in the window, when there is one
    n_window: int            # articles read (at most WINDOW)
    n_known: int             # of those, with a known fetched host
    n_other: int             # of those, answered by other_site
    confirmed: bool          # other_site is an operator-confirmed pair or a listed move


def site_of(host_or_url: str | None) -> str | None:
    """The registrable site of a host or URL, by the ONE normaliser host_mismatch uses."""
    import ipaddress

    from src.ingest.host_mismatch import _site

    if host_or_url is None:
        return None
    text = str(host_or_url).strip()
    # A trailing dot is the same host (the fetcher's host key keeps it, url_utils strips it before
    # comparing); without this a redirect to "casino.example." would read as an unknown host and
    # hide the takeover.
    if "/" not in text:
        text = text.rstrip(".")
        # A bare IP address is a site of its own: a redirect to one is off-site, never "unknown".
        try:
            return str(ipaddress.ip_address(text.strip("[]")))
        except ValueError:
            pass
    return _site(text)


def confirmed_sites(session: Session, source_id: int) -> set[str]:
    from src.database.models import HostMismatchConfirmed

    return {
        str(s) for (s,) in session.query(HostMismatchConfirmed.article_site)
        .filter(HostMismatchConfirmed.source_id == int(source_id))
    }


def evaluate(session: Session, source_id: int, domain: str | None, *,
             confirmed: set[str] | None = None) -> Finding:
    """Read the source's newest WINDOW articles' fetched hosts and say whether it is held. Read-only."""
    from src.database.models import Article

    sid = int(source_id)
    hosts = [
        h for (h,) in session.query(Article.fetched_host)
        .filter(Article.source_id == sid)
        .order_by(Article.id.desc())
        .limit(WINDOW)
    ]
    own = site_of(domain)
    known = [s for s in (site_of(h) for h in hosts) if s is not None]
    if own is None:
        return Finding(sid, UNKNOWN_SITE, None, None, len(hosts), len(known), 0, False)
    from src.utils.url_utils import is_equivalent_domain

    # A listed alias of the source's own site (bbc.com and bbc.co.uk) is the source's own site, as the
    # reader's per-article "another site" note already treats it.
    others = Counter(s for s in known if s != own and not is_equivalent_domain(s, own))
    other, n_other = (others.most_common(1)[0] if others else (None, 0))
    if confirmed is None:
        confirmed = confirmed_sites(session, sid) if other else set()
    is_confirmed = bool(other) and (other in confirmed or (own, other) in _MOVES)
    if len(known) < MIN_KNOWN:
        return Finding(sid, TOO_FEW, own, other, len(hosts), len(known), n_other, is_confirmed)
    held = other is not None and n_other * 2 >= len(known) and not is_confirmed
    return Finding(sid, HELD if held else CLEAR, own, other, len(hosts), len(known), n_other, is_confirmed)


#: derived_meta key prefix of a hold whose marks are owed: ``off_site_mark:<source id>`` -> the site.
MARK_KEY_PREFIX = "off_site_mark:"
#: Owed marks applied per run (each is one source's articles on one site).
MARKS_PER_RUN = 50


def _queue_marks(session: Session, source_id: int, site: str) -> None:
    from src.database.models import DerivedMeta

    session.merge(DerivedMeta(key=f"{MARK_KEY_PREFIX}{int(source_id)}", value=site[:255]))


def _drop_marks(session: Session, source_id: int) -> None:
    from src.database.models import DerivedMeta

    session.query(DerivedMeta).filter(DerivedMeta.key == f"{MARK_KEY_PREFIX}{int(source_id)}").delete(
        synchronize_session=False)


def pending_marks(session: Session, source_ids: Iterable[int] | None = None) -> list[tuple[int, str]]:
    """The holds whose marks are still owed, as ``(source id, site)``, oldest source id first."""
    from src.database.models import DerivedMeta

    q = session.query(DerivedMeta.key, DerivedMeta.value).filter(DerivedMeta.key.like(f"{MARK_KEY_PREFIX}%"))
    if source_ids is not None:
        keys = [f"{MARK_KEY_PREFIX}{int(i)}" for i in source_ids]
        if not keys:
            return []
        q = q.filter(DerivedMeta.key.in_(keys))
    out = []
    for key, value in q:
        try:
            out.append((int(str(key)[len(MARK_KEY_PREFIX):]), str(value)))
        except ValueError:
            continue
    return sorted(out)[:MARKS_PER_RUN]


def apply_pending_marks(session: Session, *, source_ids: Iterable[int] | None = None,
                        now: datetime | None = None) -> tuple[int, int]:
    """Set the owed marks (R728 B), each under the write gate, and forget each one once it is set.
    A failure is logged and its row stays for the next run. Commits. Returns (articles marked, failures)."""
    from src.monitoring.secret_scrub import log_failure

    marked = failed = 0
    for sid, site in pending_marks(session, source_ids):
        try:
            marked += quarantine_off_site(session, sid, site, now=now)
            _drop_marks(session, sid)
            session.commit()
        except Exception as exc:  # noqa: BLE001 - the owed row stays; the next run tries again
            session.rollback()
            failed += 1
            log_failure(_LOG, f"off-site quarantine failed for source {sid}", exc, level=logging.WARNING)
    return marked, failed


def hold(session: Session, source: Source, finding: Finding, *, now: datetime, candidate: bool = False) -> bool:
    """Stamp the hold on ``source`` (status + an append-only attempt row). Does NOT commit, and does
    not mark articles: :func:`quarantine_off_site` does that after the caller commits, under the
    write gate. ``candidate`` is True for a source held while being judged (it was never qualified),
    which its attempt row records so a confirmation sends it back to judging. Returns False when the
    finding is not a hold."""
    from src.catalog.qualification import STATUS_DISQUALIFIED
    from src.database.models import SourceQualificationAttempt

    if finding.state != HELD:
        return False
    session.add(SourceQualificationAttempt(
        source_id=source.id, attempted_at=now, verdict=STATUS_DISQUALIFIED,
        criteria_version=CANDIDATE_CRITERIA_VERSION if candidate else CRITERIA_VERSION,
    ))
    source.status = STATUS_DISQUALIFIED
    source.qualified_at = None
    source.qualification_criteria_version = None
    # The marks are queued IN THE SAME TRANSACTION as the hold, so a hold can never be committed without
    # its marks owed: apply_pending_marks sets them after the commit, and a crash or a failure there
    # leaves the row for the next run instead of a hold whose articles still feed the aggregates.
    _queue_marks(session, int(source.id), str(finding.other_site))
    _LOG.warning(
        "off-site hold: source %s (%s) -- %d of %d recent pages with a known host were answered by %s",
        source.id, finding.source_site, finding.n_other, finding.n_known, finding.other_site,
    )
    return True


def _article_ids_on_site(session: Session, source_id: int, site: str, *, reason: str | None = None) -> list[int]:
    """Ids of the source's articles whose fetched host is on ``site`` (and, when given, carry ``reason``)."""
    from src.database.models import Article

    q = session.query(Article.id, Article.fetched_host).filter(
        Article.source_id == int(source_id), Article.fetched_host.isnot(None),
    )
    if reason is not None:
        q = q.filter(Article.quarantined.is_(True), Article.quarantine_reason == reason)
    return [int(aid) for aid, h in q.yield_per(1000) if site_of(h) == site]


#: Articles changed per write transaction: the write gate is released between chunks, so a large
#: source never holds ingest up for the whole of its articles.
MARK_CHUNK = 2000


def _set_marks(session: Session, ids: list[int], *, mark: bool, now: datetime | None) -> int:
    """Set (``mark``) or lift the off-site mark on ``ids``, chunk by chunk, each chunk one transaction
    under the write gate with the keyword counters moved in it (R101) and the corpus epoch bumped so the
    rollup forgets them. Setting skips an article already quarantined for any reason; lifting touches
    only this hold's own reason. Returns how many articles changed."""
    from src.analytics.corpus_epoch import bump_corpus_epoch
    from src.analytics.store import shift_keyword_counters_for_quarantine
    from src.database.models import Article
    from src.database.writer import connection_first, write_lock

    eligible: Any
    values: dict[Any, Any]
    if mark:
        eligible = Article.quarantined.isnot(True)
        values = {"quarantined": True, "quarantine_reason": QUARANTINE_REASON,
                  "quarantine_criteria_version": CRITERIA_VERSION, "quarantined_at": now}
    else:
        eligible = (Article.quarantined.is_(True)) & (Article.quarantine_reason == QUARANTINE_REASON)
        values = {"quarantined": False, "quarantine_reason": None,
                  "quarantine_criteria_version": None, "quarantined_at": None}
    total = 0
    for i in range(0, len(ids), MARK_CHUNK):
        chunk = ids[i:i + MARK_CHUNK]
        connection_first(session)
        with write_lock():
            try:
                # Read and write inside the gate, so the counters move for exactly the rows changed.
                changed = [int(aid) for (aid,) in session.query(Article.id).filter(Article.id.in_(chunk), eligible)]
                if changed:
                    session.query(Article).filter(Article.id.in_(changed)).update(values, synchronize_session=False)
                    shift_keyword_counters_for_quarantine(session, changed, quarantined=mark)
            except BaseException:
                session.rollback()
                raise
            if changed:
                bump_corpus_epoch(session, reason="quarantine", strict=True)  # commits with the bump
            else:
                session.commit()
        total += len(changed)
    return total


def quarantine_off_site(session: Session, source_id: int, site: str, *, now: datetime | None = None) -> int:
    """R728 B: the reversible quarantine mark on the source's articles answered by ``site``; an article
    already quarantined for any reason is left as it is. Commits. Returns how many articles it marked."""
    now = (now or datetime.now(UTC)).replace(tzinfo=None)
    ids = _article_ids_on_site(session, source_id, site)
    session.commit()  # the read above ends here: each chunk below is a fresh write
    return _set_marks(session, ids, mark=True, now=now) if ids else 0


def release_off_site(session: Session, source_id: int, site: str) -> int:
    """Lift the marks a hold set for ``site`` (only ``QUARANTINE_REASON`` ones; any other quarantine
    stays). Commits. Returns how many articles it released."""
    ids = _article_ids_on_site(session, source_id, site, reason=QUARANTINE_REASON)
    session.commit()
    return _set_marks(session, ids, mark=False, now=None) if ids else 0


def latest_attempt_versions(session: Session, source_ids: Iterable[int]) -> dict[int, str]:
    """The criteria version of each source's newest attempt row (one grouped read)."""
    from sqlalchemy import func

    from src.database.models import SourceQualificationAttempt as A

    ids = sorted({int(i) for i in source_ids})
    out: dict[int, str] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        newest = (
            session.query(A.source_id, func.max(A.id).label("mx"))
            .filter(A.source_id.in_(chunk)).group_by(A.source_id).subquery()
        )
        for sid, ver in session.query(A.source_id, A.criteria_version).join(newest, A.id == newest.c.mx):
            out[int(sid)] = str(ver)
    return out


def held_payloads(session: Session, sources: Iterable[Source]) -> dict[int, dict]:
    """For a page of sources: the hold each currently held one carries, as the Sources tab shows it.

    Held = ``disqualified`` and its newest attempt is an off-site hold. The two sites and the counts
    are read again now (they are a fact about the stored articles, not a stored copy)."""
    from src.catalog.qualification import STATUS_DISQUALIFIED

    rows = [s for s in sources if getattr(s, "status", None) == STATUS_DISQUALIFIED]
    if not rows:
        return {}
    versions = latest_attempt_versions(session, (s.id for s in rows))
    out: dict[int, dict] = {}
    for s in rows:
        if versions.get(int(s.id)) not in HOLD_VERSIONS:
            continue
        f = evaluate(session, int(s.id), s.domain)
        out[int(s.id)] = {
            "source_site": f.source_site, "other_site": f.other_site,
            "n_window": f.n_window, "n_known": f.n_known, "n_other": f.n_other,
            "still_off_site": f.state == HELD,
        }
    return out


def readmit(session: Session, source: Source, *, now: datetime | None = None) -> str | None:
    """The operator confirmed the pair: lift the hold. Does not commit. Returns what happened:

    * ``"qualified"``: a held QUALIFIED source is re-admitted, with an attempt row carrying
      ``CONFIRMED_CRITERIA_VERSION`` and an admission audit row (undoable like any other admission);
    * ``"requeued"``: a CANDIDATE held while being judged goes back to ``unqualified``, so the next
      qualification pass judges its extraction like any other candidate (no attempt row: nothing was
      judged; the confirmed pair is the record);
    * ``None``: the source is not currently held.
    """
    from src.catalog.qualification import (
        STATUS_DISQUALIFIED,
        STATUS_QUALIFIED,
        STATUS_UNQUALIFIED,
        record_admission,
    )
    from src.database.models import SourceQualificationAttempt

    if source.status != STATUS_DISQUALIFIED:
        return None
    version = latest_attempt_versions(session, [source.id]).get(int(source.id))
    # CONFIRMED with status disqualified: an earlier re-admission was undone; confirming again re-admits.
    if version not in (*HOLD_VERSIONS, CONFIRMED_CRITERIA_VERSION):
        return None
    _drop_marks(session, int(source.id))  # confirmed before its marks were set: none are owed now
    if version == CANDIDATE_CRITERIA_VERSION:
        source.status = STATUS_UNQUALIFIED
        source.qualified_at = None
        source.qualification_criteria_version = None
        return "requeued"
    now = (now or datetime.now(UTC)).replace(tzinfo=None)
    prior_enabled, prior_status = source.enabled, source.status
    session.add(SourceQualificationAttempt(
        source_id=source.id, attempted_at=now, verdict=STATUS_QUALIFIED,
        criteria_version=CONFIRMED_CRITERIA_VERSION,
    ))
    source.status = STATUS_QUALIFIED
    source.qualified_at = now
    source.qualification_criteria_version = CONFIRMED_CRITERIA_VERSION
    record_admission(
        session, source, prior_enabled=prior_enabled, prior_status=prior_status,
        now=now, verdict=STATUS_QUALIFIED, criteria_version=CONFIRMED_CRITERIA_VERSION,
    )
    return "qualified"


# --------------------------------------------------------------------------------------------- #
# THE SWEEP, run by the collection pass's housekeeping lane (R728 A: "after each collection pass").
# --------------------------------------------------------------------------------------------- #

#: derived_meta key holding the sweep's place: {"a": last article id looked at, "s": next source id
#: of the first full sweep, or null once it has gone through every qualified source}.
STATE_KEY = "off_site_sweep"
#: Article ids taken per run (the sources they belong to are checked), and qualified sources taken
#: per run by the first full sweep. Both bound one run; what is left is taken next run.
ARTICLE_STEP = 50_000
FIRST_SWEEP_STEP = 500


def _load_state(session: Session) -> dict:
    from src.database.models import DerivedMeta

    row = session.get(DerivedMeta, STATE_KEY)
    if row is None:
        return {"a": None, "s": 0}
    try:
        d = json.loads(row.value)
        return {"a": d.get("a"), "s": d.get("s")}
    except (ValueError, TypeError, AttributeError):
        return {"a": None, "s": 0}


def _save_state(session: Session, state: dict) -> None:
    from src.database.models import DerivedMeta

    value = json.dumps({"a": state.get("a"), "s": state.get("s")}, separators=(",", ":"))
    row = session.get(DerivedMeta, STATE_KEY)
    if row is None:
        session.add(DerivedMeta(key=STATE_KEY, value=value))
    else:
        row.value = value
        row.updated_at = datetime.now(UTC)


def sweep(session: Session, *, now: datetime | None = None) -> dict:
    """Check the qualified sources that stored articles since the last run (plus, until it has gone
    through all of them once, the next slice of every qualified source), and hold the ones the rule
    names. Offline. Commits. Returns counts."""
    from sqlalchemy import func

    from src.catalog.qualification import STATUS_QUALIFIED
    from src.database.models import Article, Source
    from src.database.stand_in import not_a_stand_in_source

    now = (now or datetime.now(UTC)).replace(tzinfo=None)
    state = _load_state(session)
    top = int(session.query(func.max(Article.id)).scalar() or 0)
    start = state["a"]
    candidates: set[int] = set()
    if start is None:
        start = top  # the first full sweep below covers everything stored before now
    upto = min(top, int(start) + ARTICLE_STEP)
    if upto > int(start):
        candidates.update(
            int(sid) for (sid,) in session.query(Article.source_id)
            .filter(Article.id > int(start), Article.id <= upto).distinct()
            if sid is not None
        )
    first = state["s"]
    if first is not None:
        nxt = [
            int(sid) for (sid,) in session.query(Source.id)
            .filter(Source.id >= int(first), Source.status == STATUS_QUALIFIED)
            .order_by(Source.id).limit(FIRST_SWEEP_STEP)
        ]
        candidates.update(nxt)
        first = (nxt[-1] + 1) if len(nxt) == FIRST_SWEEP_STEP else None
    checked = held = 0
    ids = sorted(candidates)
    for i in range(0, len(ids), 500):
        for src in (
            session.query(Source)
            .filter(Source.id.in_(ids[i:i + 500]), Source.status == STATUS_QUALIFIED, not_a_stand_in_source())
        ):
            checked += 1
            f = evaluate(session, int(src.id), src.domain)
            if hold(session, src, f, now=now):
                held += 1
    state["a"], state["s"] = upto, first
    _save_state(session, state)
    session.commit()
    # This run's holds and any a failed earlier run still owes.
    marked, failed = apply_pending_marks(session, now=now)
    return {"checked": checked, "held": held, "articles_marked": marked, "marks_failed": failed,
            "first_sweep_done": first is None}
