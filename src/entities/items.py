"""The local Wikidata item cache and its consented, rate-gated fetch (Q724 = a, R8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

**WHAT IS ASKED FOR: ONLY WHAT THE CORPUS MENTIONS.** Q724 bounds the cache to «per QID the
corpus mentions». Two things in the corpus name a QID today, and :func:`mentioned_qids` reads
both, locally: the Places the corpus's mentioned places resolved into (their gazetteer QID),
and the people and organisations the corpus mentions whose name a ring resolves to an item
(the ladder of :mod:`src.entities.spine`). Nothing else is ever sent.

**THE RATE IS THE RING LOAD'S GATE (R8).** «Automated Wikidata downloads respect <= 1 request
per 10 seconds.» :class:`src.analytics.ring_loader.RateGate` spaces REQUESTS, with an
injectable clock so a test proves the spacing without waiting for it; this module owns no
second rate.

**EVERY REFUSAL IS NAMED.** Airplane mode refuses before a session is constructed and is
re-checked between batches, because an operator can engage it during a fetch that sleeps ten
seconds between requests (``src/catalog/qid_labels.py`` records the same reasoning). The
refusal says the kill switch did it -- invariant #14e's corollary.

**THE FETCH PATH IS THE ONE FETCH PATH.** ``guarded_session``: the kill switch, the operator's
transport (never a silent Tor -> clearnet downgrade, Q1014), the honest bot UA.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from src.analytics.ring_loader import RateGate
from src.analytics.wikidata_rings import POLITE_SLEEP_S
from src.entities.wikidata_items import BATCH_MAX, CLAIMS, batches, entities_url, is_qid, parse_entities

_LOG = logging.getLogger(__name__)

USER_AGENT = "OpenOmniscience-entity-spine/0.1 (local-first research app)"
_TIMEOUT_S = 30

#: How many entity names the pending read looks at, most-cited first. A bound on the scan,
#: stated in the payload, never a silent truncation.
_ENTITY_SCAN_CAP = 5_000

#: The refusal, in the words every surface shows (the UI keys its own ×12 twin).
REFUSAL = (
    "network refused: airplane mode is engaged (the Wikidata item fetch makes no request "
    "while the kill switch is on)"
)


class AirplaneRefusal(RuntimeError):
    """The kill switch refused the item fetch, and says so in as many words."""


def _kill_switch_active() -> bool:
    from src.ingest import kill_switch_active

    return bool(kill_switch_active())


def cached_item(session, qid: str | None):
    """The cache row for ``qid``, or None when this machine has never read it."""
    if not is_qid(qid):
        return None
    from src.database.models import WikidataItem

    return session.get(WikidataItem, qid)


def item_payload(row) -> dict | None:
    """A cache row as the surfaces read it, or None for an absent row."""
    if row is None:
        return None

    def _load(raw: str | None) -> dict:
        try:
            v = json.loads(raw) if raw else {}
        except ValueError:
            v = {}
        return v if isinstance(v, dict) else {}

    return {
        "qid": row.qid,
        "status": row.status,
        "resolved_qid": row.resolved_qid,
        "labels": _load(row.labels_json),
        "descriptions": _load(row.descriptions_json),
        "claims": _load(row.claims_json),
        "lastrevid": row.lastrevid,
        "as_of": row.fetched_at.isoformat() if row.fetched_at else None,
    }


def mentioned_qids(session, *, stats: dict | None = None) -> list[str]:
    """Every QID the corpus mentions, in the order a fetch should ask for them. Local only.

    Places first (they are what a Place card needs a name and a description for), then the
    people and organisations, most-cited first. ``stats`` is filled with where each came from.
    """
    from sqlalchemy import func, select

    from src.database.models import ArticleEntity, Place

    out: list[str] = []
    seen: set[str] = set()
    place_n = 0
    for (qid,) in session.execute(
        select(Place.qid).where(Place.qid.is_not(None)).order_by(Place.population.desc().nullslast(), Place.id)
    ):
        if is_qid(qid) and qid not in seen:
            seen.add(qid)
            out.append(qid)
            place_n += 1

    entity_n = 0
    scanned = 0
    arts = func.count(func.distinct(ArticleEntity.article_id))
    rows = session.execute(
        select(ArticleEntity.name, arts.label("a"))
        .group_by(ArticleEntity.name)
        .order_by(arts.desc(), ArticleEntity.name)
        .limit(_ENTITY_SCAN_CAP)
    ).all()
    scanned = len(rows)
    from src.entities.spine import entity_qid

    for name, _a in rows:
        q, _declined = entity_qid(name or "")
        if q is not None and q not in seen:
            seen.add(q)
            out.append(q)
            entity_n += 1
    if stats is not None:
        stats.update(
            {"from_places": place_n, "from_entities": entity_n,
             "entities_scanned": scanned, "entity_scan_cap": _ENTITY_SCAN_CAP}
        )
    return out


def pending_summary(session) -> dict:
    """What a fetch WOULD ask for, computed entirely on this machine. No network call.

    Not gated by the network consent, for the reason ``ring_loader.gap_summary`` gives:
    invariant #14e gates a pre-action estimate BECAUSE estimates egress first, and this one
    reads the local tables only.
    """
    from src.database.models import WikidataItem

    stats: dict = {}
    qids = mentioned_qids(session, stats=stats)
    cached = {
        q for (q,) in session.query(WikidataItem.qid).filter(WikidataItem.qid.in_(qids)).all()
    } if qids else set()
    missing = sum(
        1 for (s,) in session.query(WikidataItem.status).filter(WikidataItem.status == "missing").all()
    )
    pending = [q for q in qids if q not in cached]
    return {
        "mentioned": len(qids),
        "cached": len(cached),
        "pending": len(pending),
        "missing_on_wikidata": missing,
        "requests_needed": (len(pending) + BATCH_MAX - 1) // BATCH_MAX,
        "seconds_per_request": POLITE_SLEEP_S,
        "sources": stats,
        "claims": list(CLAIMS),
        "method": (
            "QIDs this corpus mentions: the Places its mentioned places resolved into, then "
            "the people and organisations whose name a ring resolves to a Wikidata item, "
            "most-cited first. Counts only. No network call was made to produce this: it "
            f"reads the local tables. A fetch asks for up to {BATCH_MAX} items per request, "
            f"one request every {POLITE_SLEEP_S:.0f} seconds."
        ),
    }


def _default_getter(url: str) -> dict:
    """A guarded GET returning parsed JSON (the one fetch path; see the module docstring)."""
    from src.safety.fetcher import guarded_session

    resp = guarded_session(user_agent=USER_AGENT, isolation_token=url).get(url, timeout=_TIMEOUT_S)
    resp.raise_for_status()
    return json.loads(resp.text)


def store_items(session, parsed) -> int:
    """Upsert parsed items into the cache. Returns how many rows were written."""
    from src.database.models import WikidataItem

    now = datetime.now(UTC)
    n = 0
    for it in parsed:
        row = session.get(WikidataItem, it.qid) or WikidataItem(qid=it.qid)
        row.status = it.status
        row.resolved_qid = it.resolved_qid
        if it.status == "ok":
            f = it.json_fields()
            row.labels_json = f["labels_json"]
            row.descriptions_json = f["descriptions_json"]
            row.claims_json = f["claims_json"]
            row.lastrevid = it.lastrevid
        else:
            row.labels_json = row.descriptions_json = row.claims_json = None
            row.lastrevid = None
        row.fetched_at = now
        session.add(row)
        n += 1
    session.commit()
    return n


def fetch_items(
    qids: list[str],
    *,
    session_factory: Callable,
    get: Callable[[str], dict] | None = None,
    gate: RateGate | None = None,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Fetch ``qids`` into the cache, one batch per request, R8-spaced. Returns counts.

    Refuses up front under airplane mode, by name, before any request is built. One batch's
    failure never aborts the run; it is counted under ``refused`` with no guess about why.
    """
    if _kill_switch_active():
        raise AirplaneRefusal(REFUSAL)

    getter = get or _default_getter
    rg = gate or RateGate(stop=should_stop)
    todo = batches(list(qids))
    total = sum(len(b) for b in todo)
    fetched = missing = refused = 0
    stopped = airplane = False
    done = 0
    for batch in todo:
        if should_stop is not None and should_stop():
            stopped = True
            break
        if _kill_switch_active():
            # Engaged DURING the run: stop, and say which of the two stops it was.
            airplane = True
            break
        if progress is not None:
            progress(done, total, batch[0])
        try:
            rg.wait()
            if should_stop is not None and should_stop():
                stopped = True
                break
            parsed = parse_entities(getter(entities_url(batch)), batch)
        except Exception as exc:  # noqa: BLE001 - one failed batch is counted, never fatal
            refused += len(batch)
            done += len(batch)
            _LOG.info("wikidata item batch of %d failed: %s", len(batch), exc)
            continue
        with session_factory() as s:
            store_items(s, parsed)
        fetched += sum(1 for p in parsed if p.status == "ok")
        missing += sum(1 for p in parsed if p.status == "missing")
        # An id the answer did not mention at all is neither fetched nor missing: it is
        # counted as refused, so the three counts always add up to what was asked.
        refused += len(batch) - len(parsed)
        done += len(batch)
    return {
        "requested": total,
        "fetched": fetched,
        "missing_on_wikidata": missing,
        "refused": refused,
        "pending": max(0, total - done),
        "stopped": stopped,
        "stopped_by_airplane_mode": airplane,
        "requests_spacing_s": POLITE_SLEEP_S,
        "method": (
            f"wbgetentities on www.wikidata.org, up to {BATCH_MAX} items per request, one "
            f"request every {POLITE_SLEEP_S:.0f} seconds, through the app's one fetch path "
            "and your transport setting. Labels and descriptions in the twelve interface "
            "languages, and the claims P31, P17, P625 and P571 only. Counts only."
        ),
    }
