"""
Bare Wikidata Q-ids as NAMES: resolve at the polite rate, or decline the row (Q1116 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FINDING (institutions C8): 26 of the 267 verified rows — 9.7 % — carry a bare Wikidata
Q-id where their NAME should be, because the export never resolved a label. Spliced as they
stand, the catalogue would gain 26 sources called ``Q133293483``. The docket puts it in the
same family as C7 (identity fields are evidence, not fact) and notes what makes it different:
it is mechanically detectable AND mechanically fixable — by re-querying the label, or by
declining to admit an unlabelled row.

THE RULING TAKES BOTH HALVES: resolve the label at the polite rate, **or decline to admit the
row**. The second half is not a fallback, it is the point. A row whose name could not be
resolved is not admitted under its Q-id and is not admitted under a guess; it is DECLINED,
with the reason recorded, and it stays available to a later pass that can reach the network.

WHAT THE NETWORK HALF OWES, and every one of these is enforced here rather than remembered:

  * THE POLITE RATE. R8 (2026-09-12): automated Wikidata downloads respect <= 1 request per
    10 seconds. The interval is imported from ``src.analytics.wikidata_rings`` rather than
    restated — that module's own comment says why, and it is the reason this one does not
    keep a second copy: "a rate two callers each hold their own copy of is a rate one of them
    will quietly relax."
  * ONE CONSENT FOR THE BATCH, not one per row. The caller gates once; this function never
    asks. Twenty-six consent prompts for one operation is a dialog people learn to dismiss.
  * A REFUSAL NAMED AS ITSELF. Under the kill switch this raises
    :class:`AirplaneRefusal` before any request is built, saying that airplane mode is
    engaged — invariant #14e's corollary, which exists because a probe once reported the kill
    switch as "size check failed" and pointed an operator at somebody else's server for their
    own setting. It is checked again between rows, because an operator can engage airplane
    mode DURING a 26-row run that sleeps ten seconds between requests, and a run that only
    checked at the start would keep fetching for four more minutes.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence

from src.analytics.wikidata_rings import LANGS, POLITE_SLEEP_S, wbentities_url

#: A bare Q-id: the identifier and nothing else. `Q42 Douglas Adams` is a name that happens
#: to start with one and must NOT match -- it already carries the label the ruling is about.
_BARE_QID = re.compile(r"^\s*[Qq]\d+\s*$")

#: Why a row was not admitted. Each is a REASON, never a bare False: "we could not reach
#: Wikidata" and "Wikidata has no label for this item" are different facts, and a later pass
#: can act on the first while the second needs a human.
DECLINED_UNRESOLVED = "label_not_resolved"
DECLINED_NO_LABEL = "wikidata_has_no_label"
DECLINED_REFUSED = "network_refused"


class AirplaneRefusal(RuntimeError):
    """The kill switch refused this run, named as the kill switch.

    A generic failure here would send an operator to look at Wikidata for a setting of their
    own — the exact mis-direction invariant #14e's corollary was written about.
    """


def looks_like_bare_qid(name: str | None) -> bool:
    """Is this NAME just an identifier? Whitespace-tolerant, case-tolerant, nothing else."""
    return bool(name and _BARE_QID.match(name))


def bare_qid_rows(rows: Iterable[tuple[object, str | None]]) -> list[tuple[object, str]]:
    """``(id, name)`` pairs whose name is a bare Q-id, normalised to upper case."""
    return [(rid, (name or "").strip().upper()) for rid, name in rows
            if looks_like_bare_qid(name)]


def _first_label(payload: dict, qid: str, langs: Sequence[str]) -> str | None:
    """The first label present, in the caller's language order.

    English is NOT privileged by the caller's default: ``LANGS`` is alphabetical, so a body
    whose label exists only in Arabic or Bengali resolves to that label rather than being
    declined for having no English one. Naming a Czech municipality in English when Wikidata
    knows it in Czech would be the same anglicising failure the ring builder documents.
    """
    labels = ((payload.get("entities") or {}).get(qid) or {}).get("labels") or {}
    for lang in langs:
        value = (labels.get(lang) or {}).get("value")
        if value and value.strip():
            return value.strip()
    # Anything at all, before giving up: a label in a language nobody asked for is still a
    # name, and "declined for having no label" must mean the item really has none.
    for entry in labels.values():
        value = (entry or {}).get("value")
        if value and value.strip():
            return value.strip()
    return None


def resolve_labels(
    qids: Sequence[str],
    *,
    fetch: Callable[[str], dict],
    langs: Sequence[str] = LANGS,
    sleep: Callable[[float], None] | None = None,
    kill_switch: Callable[[], bool] | None = None,
    interval_s: float = POLITE_SLEEP_S,
) -> dict:
    """Resolve each Q-id to a label at the polite rate. Returns labels AND declines.

    ``fetch`` and ``sleep`` are injected so this is testable WITHOUT a socket and without
    waiting ten seconds per row — the rate is then asserted by counting the sleeps, which is
    a stronger check than watching a clock.
    """
    import time

    from src.ingest import kill_switch_active

    active = kill_switch or kill_switch_active
    napper = sleep if sleep is not None else time.sleep

    if active():
        raise AirplaneRefusal(
            "network refused: airplane mode is engaged, so Wikidata labels cannot be "
            "resolved. Nothing was fetched and no row was declined for it."
        )

    labels: dict[str, str] = {}
    declined: dict[str, str] = {}
    requests = 0
    for i, qid in enumerate(dict.fromkeys(q.strip().upper() for q in qids if q)):
        if active():
            # Checked again BETWEEN rows: an operator can engage airplane mode during a run
            # that sleeps ten seconds per request, and a start-only check would keep going.
            for remaining in list(qids)[i:]:
                declined.setdefault(str(remaining).strip().upper(), DECLINED_REFUSED)
            break
        if i:
            napper(interval_s)  # R8: <= 1 request / 10 s, BEFORE the request, never after
        try:
            payload = fetch(wbentities_url(qid, tuple(langs)))
            requests += 1
        except Exception:  # noqa: BLE001 - a failed lookup declines a row, never crashes a run
            declined[qid] = DECLINED_UNRESOLVED
            continue
        label = _first_label(payload or {}, qid, langs)
        if label:
            labels[qid] = label
        else:
            declined[qid] = DECLINED_NO_LABEL

    return {
        "labels": labels,
        "declined": declined,
        "requests": requests,
        "interval_s": interval_s,
        "method": (
            f"One request per Q-id to www.wikidata.org, at most one per {interval_s:g} "
            "seconds (R8), under a single consent for the whole batch. A label is taken in "
            "the caller's language order and then in any language the item has one in."
        ),
        "caveat": (
            "A row whose label could not be resolved is DECLINED, never admitted under its "
            "Q-id and never under a guess. 'Could not reach Wikidata' and 'Wikidata has no "
            "label' are recorded as different reasons, because a later pass can act on the "
            "first and only a person can act on the second."
        ),
    }


def admit_or_decline(rows: Iterable[tuple[object, str | None]], labels: dict[str, str]) -> dict:
    """Apply the ruling to a candidate set: name the resolvable ones, decline the rest.

    Rows whose name is NOT a bare Q-id pass through untouched — this rule is about
    identifiers standing in for names, and nothing else.
    """
    admitted: list[dict] = []
    declined: list[dict] = []
    for rid, name in rows:
        if not looks_like_bare_qid(name):
            admitted.append({"id": rid, "name": name, "renamed_from": None})
            continue
        qid = (name or "").strip().upper()
        label = labels.get(qid)
        if label:
            admitted.append({"id": rid, "name": label, "renamed_from": qid})
        else:
            declined.append({
                "id": rid, "qid": qid, "reason": DECLINED_UNRESOLVED,
                "detail": (
                    "The name is a bare Wikidata identifier and no label was resolved for "
                    "it, so admitting it would put an identifier in the catalogue where a "
                    "name belongs. The row is left for a later pass, not discarded."
                ),
            })
    return {"admitted": admitted, "declined": declined,
            "admitted_count": len(admitted), "declined_count": len(declined)}
