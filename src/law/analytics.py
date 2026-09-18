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
