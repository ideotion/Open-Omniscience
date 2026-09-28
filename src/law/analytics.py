"""Law analytics 1–2 (Q914 = a, brief S04-10 S4): counts, never a verdict.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q914 confirms five analytics and puts the first two in 0.4:

1. **the per-provision diff timeline** — which sections of one Act actually changed, and
   when, rather than a whole-document byte figure that says a document moved;
2. **amendment velocity per jurisdiction over time** — how often tracked law changed,
   per jurisdiction, per period.

EVERY FIGURE HERE IS A COUNT OF SOMETHING THIS INSTANCE OBSERVED, and each carries its
``method``, its ``caveat`` and its ``n``. That is the app's honesty contract and it is
load-bearing on this surface in a way it is not on most: "amendment velocity" reads like
a property of a legislature, and it is not. It is a property of *what this install
happened to poll, and how often*. A jurisdiction with two tracked documents polled weekly
will show a lower velocity than one with two hundred polled daily, and neither number is
about the law. The caveats say so in the payload rather than in a UI that may or may not
render them.

**NO RATES, NO TRENDS, NO NORMALISATION.** There is deliberately no "amendments per
document per month" and no comparison between jurisdictions: dividing by a
tracked-document count would produce a figure that looks like a legislative rate and is
in fact a statement about this operator's watch list (Q921's whole rail, one level up).
The consumer gets counts and the denominators it would need, and this module refuses to
do the division for it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from src.database.models import LawDocument, LawRevision
from src.law.lane_models import LawProvision

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

#: Below this many datapoints a series renders as BARS, not a line — invariant #16's
#: app-wide sparse rule, amended 2026-06-15 ("n<10 datapoints -> a BAR graph").
#:
#: THE VALUE LIVES IN THE RENDERER, WHICH IS JAVASCRIPT: ``_SPARSE_BAR_MAX`` in
#: ``src/static/app-markets.js``, shared by ``ooChart`` and ``dashChartSvg``. There is no
#: Python constant to import, so this is a DECLARED COPY rather than a pretend one — an
#: earlier draft wrapped an import of a name that does not exist in a try/except and fell
#: back to 10, which looks like it reads the shared value and never does. A test asserts
#: the two are equal, so the copy cannot drift in silence.
SPARSE_BAR_MAX = 10


def provision_timeline(
    lane: Session,
    document_lane_key: str,
    *,
    revision_order: Sequence[str] | None = None,
) -> dict:
    """Analytic 1: which PROVISIONS of one document changed, version by version.

    ``revision_order`` is the document's revision lane keys OLDEST FIRST, because the
    lane holds no revision ordering of its own — the order is a fact about
    ``law_revisions`` in ``corpus.db``, and inferring it here from a provision's
    ``created_at`` would order by when this app happened to write the rows.

    THE CHANGE TEST IS THE CONTENT HASH, NOT THE TEXT. Two provisions with the same words
    and different whitespace are the same provision saying the same thing; the hash is
    computed over the text the adapter produced, so this measures what the adapter read
    rather than how the publisher indented it.

    THREE STATES PER PROVISION PER VERSION, and they are not collapsible:

    * ``changed``  — present in both, different hash;
    * ``added``    — absent from the previous version, present in this one;
    * ``removed``  — present in the previous, absent from this one.

    A provision that is simply unchanged produces NO entry, because a timeline of
    everything that did not happen is not a timeline.
    """
    rows = (
        lane.query(LawProvision)
        .filter_by(document_lane_key=document_lane_key)
        .order_by(LawProvision.ordinal, LawProvision.id)
        .all()
    )
    by_revision: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        by_revision[row.revision_lane_key][row.address] = row.content_hash

    order = [k for k in (revision_order or []) if k in by_revision]
    unordered = sorted(set(by_revision) - set(order))
    # A version whose key the caller did not supply is REPORTED, never appended to the
    # end: appending would place it in an order nobody measured, and a timeline's whole
    # value is the order.
    events: list[dict] = []
    for index in range(1, len(order)):
        before, after = by_revision[order[index - 1]], by_revision[order[index]]
        for address in sorted(set(before) | set(after)):
            if address in before and address in after:
                if before[address] != after[address]:
                    events.append({"address": address, "change": "changed", "version": order[index]})
            elif address in after:
                events.append({"address": address, "change": "added", "version": order[index]})
            else:
                events.append({"address": address, "change": "removed", "version": order[index]})

    per_address = Counter(e["address"] for e in events)
    return {
        "document_lane_key": document_lane_key,
        "versions_compared": max(len(order) - 1, 0),
        "versions_ordered": len(order),
        "versions_without_a_known_position": unordered,
        "provisions_seen": len({row.address for row in rows}),
        "events": events,
        "changes_per_provision": dict(per_address.most_common()),
        "n": len(events),
        "sparse": len(events) < SPARSE_BAR_MAX,
        "method": (
            "each consecutive pair of stored versions is compared by PROVISION ADDRESS "
            "and content hash; a provision present in both with a different hash is "
            "'changed', one that appears is 'added', one that disappears is 'removed'. "
            "Version order comes from the document's own revision history, never from "
            "the order rows were written here."
        ),
        "caveat": (
            "This counts the versions THIS INSTANCE captured, not the amendments the "
            "legislature made: two amendments between one poll and the next arrive as "
            "one change. Addresses are per LANGUAGE — a translation's provisions carry "
            "its own container names, so they do not line up with the original's."
        ),
    }


def amendment_velocity(
    session: Session,
    *,
    period: str = "month",
    jurisdictions: Sequence[str] | None = None,
) -> dict:
    """Analytic 2: how many tracked-law versions were captured, per jurisdiction, per period.

    IT IS NOT A LEGISLATIVE RATE, and the payload says so twice — in ``caveat`` and in the
    per-jurisdiction ``tracked_documents`` figure, which is the denominator a reader would
    need and which this function deliberately does NOT divide by. A jurisdiction with two
    tracked documents polled weekly cannot be compared with one with two hundred polled
    daily, and producing a single number would invite exactly that comparison.

    The BASELINE capture is excluded: it is the first sighting of a document, not a change
    to it, and counting it would give every newly-tracked jurisdiction a spike on the day
    the operator added it.
    """
    bucket = period if period in ("month", "year") else "month"
    query = (
        session.query(LawDocument.jurisdiction, LawRevision.observed_at, LawRevision.diff_basis)
        .join(LawRevision, LawRevision.document_id == LawDocument.id)
        .filter(LawRevision.observed_at.isnot(None))
    )
    if jurisdictions:
        query = query.filter(LawDocument.jurisdiction.in_(list(jurisdictions)))

    counts: dict[str, Counter] = defaultdict(Counter)
    excluded_baselines = 0
    for jurisdiction, observed_at, basis in query.all():
        if basis == "first":
            excluded_baselines += 1
            continue
        if observed_at is None:  # excluded by the filter above; narrows the Optional column
            continue
        key = observed_at.strftime("%Y-%m" if bucket == "month" else "%Y")
        counts[(jurisdiction or "").lower() or "unknown"][key] += 1

    # The denominator a reader needs, counted the same way the keys above are built so
    # the two cannot disagree about which jurisdiction a document belongs to.
    tracked = Counter(
        (j or "").lower() or "unknown"
        for (j,) in session.query(LawDocument.jurisdiction).all()
    )

    series = []
    for jurisdiction in sorted(counts):
        points = [{"period": p, "count": c} for p, c in sorted(counts[jurisdiction].items())]
        series.append(
            {
                "jurisdiction": jurisdiction,
                "points": points,
                "n": len(points),
                # Invariant #16, app-wide: under the shared threshold a series renders as
                # BARS with n shown, never as a line through points nobody measured.
                "sparse": len(points) < SPARSE_BAR_MAX,
                "tracked_documents": tracked.get(jurisdiction, 0),
            }
        )

    return {
        "period": bucket,
        "series": series,
        "n": sum(s["n"] for s in series),
        "excluded_baseline_captures": excluded_baselines,
        "method": (
            "one count per stored version per period, from this instance's own capture "
            "timestamps. The first capture of a document is EXCLUDED — it is a first "
            "sighting, not a change — and the count of those exclusions is reported."
        ),
        "caveat": (
            "This is a property of what this install polls and how often, NOT of a "
            "legislature. Two amendments between consecutive polls arrive as one "
            "version. `tracked_documents` is given per jurisdiction as the denominator a "
            "reader needs; no rate is computed here, because dividing would produce a "
            "figure that reads as a legislative rate and is a statement about a watch list."
        ),
    }


# ---------------------------------------------------------------------------
# Analytics 3–5 (Q914 = a, placed in 0.5 by the gate row; brief S05-07 S5)
# ---------------------------------------------------------------------------


def _place(jurisdiction: str | None) -> str | None:
    """The ISO 3166-1 alpha-2 a map can draw for one jurisdiction, or ``None``.

    ``None`` for the EU, an international instrument, the synthetic ``ZZZ`` and anything
    unreadable: those are not countries, and drawing the EU's activity over its member
    states would put one body's amendments on twenty-seven countries' fills.
    """
    from src.catalog.countries import ISO_3166_1_ALPHA2, normalize_country

    code = normalize_country(jurisdiction or "")
    return code if code in ISO_3166_1_ALPHA2 else None


def topic_by_jurisdiction(session: Session, query: str) -> dict:
    """Analytic 3: which jurisdictions' tracked laws mention a topic — counts per jurisdiction.

    Three counts and the denominator, never a ratio: the versions containing the words,
    the documents with any such version, and the documents whose NEWEST held version
    contains them (a topic a later amendment removed is counted in the first two and not
    the third, which is the comparison worth making). Read through the point-in-time
    index, so it searches every held version and nothing else.
    """
    from src.law.pit_search import search

    found = search(session, query, limit=10**6)
    tracked = Counter(
        (j or "").lower() or "unknown" for (j,) in session.query(LawDocument.jurisdiction).all()
    )
    per: dict[str, dict] = {}
    for hit in found.get("hits", []):
        j = (hit["jurisdiction"] or "").lower() or "unknown"
        row = per.setdefault(j, {"versions": 0, "documents": set(), "current": set()})
        row["versions"] += 1
        row["documents"].add(hit["document_id"])
        if hit["current"]:
            row["current"].add(hit["document_id"])
    rows = [
        {
            "jurisdiction": j,
            "versions_matching": v["versions"],
            "documents_matching": len(v["documents"]),
            "documents_current_matching": len(v["current"]),
            "tracked_documents": tracked.get(j, 0),
        }
        for j, v in sorted(per.items())
    ]
    return {
        "query": query,
        "status": found.get("status"),
        "reason": found.get("reason"),
        "rows": rows,
        "n": len(rows),
        "coverage": found.get("coverage"),
        "method": (
            "For each jurisdiction: the stored versions containing every word, the "
            "documents with at least one such version, and the documents whose newest "
            "held version contains them — beside how many documents this instance tracks "
            "there. Counts only; no ratio is computed."
        ),
        "caveat": (
            "A comparison of what this install tracks, not of the jurisdictions' law: a "
            "jurisdiction with few tracked documents will show few matches. Words are "
            "matched in the language each document is written in; a topic phrased in "
            "English does not find a French text."
        ),
    }


def amendment_map(session: Session, *, days: int = 365, now: datetime | None = None) -> dict:
    """Analytic 4: captured amendments per country over a window, for an equal-area map.

    The same count as analytic 2 (a stored version that is not the first capture), summed
    over one window. The VINTAGE is part of the payload — the window's two ends and the
    newest capture the counts include — because a map without a date reads as the
    present, and this one is only ever as recent as the last poll.
    """
    end = now or datetime.now(UTC)
    start = end - timedelta(days=max(1, int(days)))
    rows = (
        session.query(LawDocument.jurisdiction, LawRevision.observed_at, LawRevision.diff_basis)
        .join(LawRevision, LawRevision.document_id == LawDocument.id)
        .filter(LawRevision.observed_at.isnot(None))
        .all()
    )
    placed: Counter = Counter()
    unplaced: Counter = Counter()
    newest: datetime | None = None
    excluded = 0
    for jurisdiction, observed, basis in rows:
        if observed is None:
            continue
        stamp = observed if observed.tzinfo else observed.replace(tzinfo=UTC)
        if not (start <= stamp <= end):
            continue
        if basis == "first":
            excluded += 1
            continue
        newest = stamp if newest is None or stamp > newest else newest
        iso2 = _place(jurisdiction)
        if iso2:
            placed[iso2] += 1
        else:
            unplaced[(jurisdiction or "").lower() or "unknown"] += 1
    tracked: Counter = Counter()
    tracked_unplaced: Counter = Counter()
    for (j,) in session.query(LawDocument.jurisdiction).all():
        iso2 = _place(j)
        if iso2:
            tracked[iso2] += 1
        else:
            tracked_unplaced[(j or "").lower() or "unknown"] += 1
    return {
        "values": dict(sorted(placed.items())),
        "tracked_documents": dict(sorted(tracked.items())),
        "not_on_the_map": [
            {"jurisdiction": j, "amendments": unplaced.get(j, 0), "tracked_documents": n}
            for j, n in sorted(tracked_unplaced.items())
        ],
        "window_days": max(1, int(days)),
        "window_from": start.date().isoformat(),
        "window_to": end.date().isoformat(),
        "newest_capture": newest.isoformat() if newest else None,
        "excluded_first_captures": excluded,
        "n": sum(placed.values()),
        "method": (
            "One count per stored version that is not a document's first capture, "
            "captured inside the window, by the jurisdiction of its document. Drawn on an "
            "equal-area projection."
        ),
        "caveat": (
            "What this install captured, not what the legislatures did: it depends on "
            "which documents are tracked and how often they are polled. The EU and "
            "international instruments are not countries and are listed beside the map, "
            "never spread over their members."
        ),
    }


def changed_this_week(session: Session, *, days: int = 7, now: datetime | None = None) -> dict:
    """Analytic 5: what changed in the laws I follow, over the last ``days``.

    "The laws I follow" is the watch list — the documents whose ``watched`` flag is set —
    and "changed" is a stored version captured in the window that is not a first capture.
    Listed per document, newest first, with the count and the reader link; the words of
    the change are the reader's, never summarised here.
    """
    end = now or datetime.now(UTC)
    start = end - timedelta(days=max(1, int(days)))
    rows = (
        session.query(LawDocument, LawRevision)
        .join(LawRevision, LawRevision.document_id == LawDocument.id)
        .filter(LawDocument.watched.is_(True), LawRevision.observed_at.isnot(None))
        .all()
    )
    per: dict[int, dict] = {}
    for doc, rev in rows:
        stamp = rev.observed_at if rev.observed_at.tzinfo else rev.observed_at.replace(tzinfo=UTC)
        if not (start <= stamp <= end) or rev.diff_basis == "first":
            continue
        item = per.setdefault(
            doc.id,
            {
                "document_id": doc.id,
                "title": doc.title,
                "jurisdiction": doc.jurisdiction,
                "language": doc.language,
                "changes": 0,
                "newest": None,
                "newest_version": None,
                "reader_url": f"/api/law/documents/{doc.id}/view",
            },
        )
        item["changes"] += 1
        if item["newest"] is None or stamp.isoformat() > item["newest"]:
            item["newest"] = stamp.isoformat()
            item["newest_version"] = rev.id
    followed = session.query(LawDocument.id).filter(LawDocument.watched.is_(True)).count()
    items = sorted(per.values(), key=lambda x: x["newest"] or "", reverse=True)
    return {
        "items": items,
        "n": len(items),
        "followed_documents": followed,
        "window_days": max(1, int(days)),
        "window_from": start.date().isoformat(),
        "window_to": end.date().isoformat(),
        "method": (
            "The documents you track whose text this instance saw change inside the "
            "window, with how many new versions were captured; a document's first "
            "capture is not a change."
        ),
        "caveat": (
            "A change is seen only when a poll finds it: a law amended this week and not "
            "polled since is not listed, and two amendments between polls arrive as one."
        ),
    }
