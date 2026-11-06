"""A country's CURRENT places, summarised once (v0.6.0, R439): a CACHE of one function of ``osm_objects``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE PROBLEM, MEASURED. After R435 the planet's past is a few hundred stored rows; what is left in every OSM read is the SNAPSHOT of the places as they
are now: scans of ``osm_objects`` for one country (the table is 394 MB at 2.0 million places, and the (country, kind) index cannot answer a question
about tag columns). On a synthetic lane of 2.0 million places the Brands tab reads for 3.2 s, Contact channels for 2.9 s, Data freshness for 2.4 s, and
the geography view runs one scan per cut country on every open: the cost is linear in places, about 1.5 s per million places per tab.

WHAT THIS MODULE DOES. When a country is cut, and again after each daily apply, ONE pass over its places computes the counts the four readers
(``profile`` brands / channels / freshness, ``geography``) derive their answers from, and stores them (``osm_places_*``, headed by
``osm_places_summaries``). A reader then selects a few thousand rows. A country that already exists gets the same pass on request
(:func:`start_build`), because a GET never writes.

WHAT MUST STAY TRUE.

* A CACHE, NEVER A SECOND SOURCE OF TRUTH. :func:`compute_part` is the ONE definition of what is counted; the reader's fallback runs it on the
  request and the builder runs it for every part, and the stored rows are exactly its output (``{"counts", "values", "days"}``). Both paths then
  go through the same derivation in ``profile`` / ``geography``, so the parity test compares two things that differ only in where the counts
  came from.
* STALE IS SAID, NEVER SERVED. A summary is used only when its rule digest equals the code's (:func:`rule_version`: the key sets and a revision
  number for the SQL) AND its ``cut_finished_at`` and ``diff_sequence`` equal the country row's now (a re-cut or a daily apply moves one of
  them). Otherwise the reader computes from the places and the answer carries ``source: "computed"`` with the reason (``summary.state``).
* THE LAST EDIT IS STORED BY DAY, never as age buckets: the buckets are cut from a reference date that moves with every change file.
* NO CAP. Every distinct brand, brand:wikidata and check_date value is kept; the reader applies its own ``limit`` (the page says how many exist).
* READ-ONLY READERS STAY READ-ONLY. Only the cut job, the apply job and the POST route write; the build is local work, makes no request, never
  fails a cut or an apply (it is logged and the readers compute), and a pass that was overtaken by an apply or a re-cut stores nothing.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger(__name__)

#: Bump when the SQL that produces the counts changes in a way the key sets below do not show.
RULE_REVISION = 1

#: The readers: ``profile.SURFACES`` and the geography view.
PARTS = ("brands", "channels", "freshness", "geography")

_RUN_LOCK = threading.Lock()
_RUNNING: set[str] = set()
#: One pass at a time across countries: each scans a whole country, so several at once only compete for the same disk.
_SERIAL = threading.Lock()


def rule_version() -> str:
    """A digest of everything that decides WHAT is counted: adding a key to a group makes every stored summary stale, by construction."""
    from src.osm.completeness import KEYS
    from src.osm.profile import BRAND_GROUPS, SOCIAL_SERVICES

    return hashlib.sha256(repr((RULE_REVISION, PARTS, BRAND_GROUPS, SOCIAL_SERVICES, KEYS)).encode()).hexdigest()[:12]


def is_building(alpha3: str) -> bool:
    with _RUN_LOCK:
        return alpha3 in _RUNNING


# --------------------------------------------------------------------------- #
#  THE definition of what is counted                                           #
# --------------------------------------------------------------------------- #


def _poi(alpha3: str):
    from src.osm.lane_models import osm_objects_table as t

    return (t.c.country_alpha3 == alpha3) & (t.c.kind == "poi")


def _values(s, alpha3: str, key: str) -> list[list]:
    """Every distinct non-empty text of one curated tag with the number of places carrying exactly it, most first, then by the text."""
    from sqlalchemy import func, select

    from src.osm.lane_models import osm_objects_table as t
    from src.osm.profile import _filled
    from src.osm.tags import column_name

    col = t.c[column_name(key)]
    rows = s.execute(select(col, func.count()).where(_poi(alpha3), _filled(key)).group_by(col).order_by(func.count().desc(), col)).all()
    return [[v, int(n)] for v, n in rows]


def _days(s, alpha3: str) -> list[list]:
    """The last-edit histogram: places by the day of their current version's timestamp (a place with no timestamp is in no day)."""
    from sqlalchemy import func, select

    from src.osm.lane_models import osm_objects_table as t
    from src.osm.trends import _day

    day = _day(t.c.timestamp)
    rows = s.execute(select(day, func.count()).where(_poi(alpha3), t.c.timestamp.is_not(None)).group_by(day).order_by(day)).all()
    return [[d, int(n)] for d, n in rows]


def compute_part(s, alpha3: str, part: str, *, days: list[list] | None = None) -> dict[str, Any]:
    """THE definition of what one reader counts, from ``osm_objects`` now: ``{"counts": {name: n}, "values": {key: [[text, n]]}, "days": [[day, n]]}``.

    ``days`` lets the builder hand over the histogram it already computed for the freshness part, so the geography part does not scan for it again.
    """
    from sqlalchemy import case, func, or_, select

    from src.osm.completeness import KEYS, _has
    from src.osm.profile import BRAND_GROUPS, SOCIAL_SERVICES, _contact_filled, _filled, _sum_if

    poi = _poi(alpha3)
    counts: dict[str, int] = {}
    values: dict[str, list[list]] = {}
    out_days: list[list] = []
    if part == "brands":
        n, *present = s.execute(select(func.count(), *(_sum_if(_filled(name)) for name, _ in BRAND_GROUPS)).where(poi)).one()
        counts["n"] = int(n)
        for (name, _), p in zip(BRAND_GROUPS, present, strict=True):
            counts[f"present:{name}"] = int(p or 0)
        values = {"brand": _values(s, alpha3, "brand"), "brand:wikidata": _values(s, alpha3, "brand:wikidata")}
    elif part == "channels":
        twins = dict(KEYS)   # site, phone and e-mail are analytic 1's definition (opening hours is not a contact channel)
        base = {k: _has(k, twins[k]) for k in ("website", "phone", "email")}
        social_any = case((or_(*[_contact_filled(sv) for sv in SOCIAL_SERVICES]), 1), else_=0)
        n, *rest = s.execute(
            select(func.count(), *(func.sum(e) for e in base.values()), func.sum(social_any), *(_sum_if(_contact_filled(sv)) for sv in SOCIAL_SERVICES)).where(poi)
        ).one()
        counts["n"] = int(n)
        for name, c in zip([*base.keys(), "social"], rest[: len(base) + 1], strict=True):
            counts[name] = int(c or 0)
        for sv, c in zip(SOCIAL_SERVICES, rest[len(base) + 1 :], strict=True):
            counts[f"social:{sv}"] = int(c or 0)
        carried = (sum(base.values()) + social_any).label("c")
        for c, k in s.execute(select(carried, func.count()).where(poi).group_by(carried)).all():
            counts[f"mix:{int(c)}"] = int(k)
    elif part == "freshness":
        counts["n"] = int(s.execute(select(func.count()).where(poi)).scalar() or 0)
        counts["check_date"] = int(s.execute(select(func.count()).where(poi, _filled("check_date"))).scalar() or 0)
        out_days = days if days is not None else _days(s, alpha3)
        values = {"check_date": _values(s, alpha3, "check_date")}
    elif part == "geography":
        from src.osm.geography import brand_filled, check_date_filled

        n, brand, checked = s.execute(select(func.count(), _sum_if(brand_filled()), _sum_if(check_date_filled())).where(poi)).one()
        counts.update(n=int(n), brand_any=int(brand or 0), checked=int(checked or 0))
        out_days = days if days is not None else _days(s, alpha3)
    else:
        raise ValueError(f"unknown part {part!r}")
    return {"counts": counts, "values": values, "days": out_days}


# --------------------------------------------------------------------------- #
#  Reading                                                                     #
# --------------------------------------------------------------------------- #


def _head_state(head, country) -> str:
    """``current``, or why a stored header may not be served: ``not-built``, ``stale-rule`` (another rule wrote it) or ``stale-cut`` (the country was cut or updated since)."""
    if head is None:
        return "not-built"
    if head.rule_version != rule_version():
        return "stale-rule"
    if head.cut_finished_at != country.finished_at or head.diff_sequence != country.diff_sequence:
        return "stale-cut"
    return "current"


def _load(s, alpha3: str, part: str) -> dict[str, Any]:
    from sqlalchemy import select

    from src.osm.lane_models import OsmPlacesCount, OsmPlacesDay, OsmPlacesValue

    c, v, d = OsmPlacesCount.__table__, OsmPlacesValue.__table__, OsmPlacesDay.__table__
    counts = {name: int(n) for name, n in s.execute(select(c.c.name, c.c.n).where(c.c.alpha3 == alpha3, c.c.part == part))}
    values: dict[str, list[list]] = {}
    for key, value, n in s.execute(select(v.c.key, v.c.value, v.c.n).where(v.c.alpha3 == alpha3, v.c.part == part).order_by(v.c.key, v.c.n.desc(), v.c.value)):
        values.setdefault(key, []).append([value, int(n)])
    days = [[day, int(n)] for day, n in s.execute(select(d.c.day, d.c.n).where(d.c.alpha3 == alpha3, d.c.part == part).order_by(d.c.day))]
    return {"counts": counts, "values": values, "days": days}


def part_for(s, alpha3: str, part: str, country, have: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(the part's counts, how they were got)``: from the stored summary when it is current, else computed from the places, saying why.

    ``country`` is the ``OsmCountry`` row the caller already read, so the header is compared with the very row the answer is stamped with.
    """
    from src.osm.lane_models import OsmPlacesCount, OsmPlacesDay, OsmPlacesSummary, OsmPlacesValue

    info: dict[str, Any] = {"source": "computed", "state": "not-built", "building": is_building(alpha3)}
    if not all(m.__tablename__ in have for m in (OsmPlacesSummary, OsmPlacesCount, OsmPlacesValue, OsmPlacesDay)):
        info["state"] = "no-summary-table"
    else:
        head = s.query(OsmPlacesSummary).filter_by(alpha3=alpha3).one_or_none()
        state = _head_state(head, country)
        if state != "current":
            info["state"] = state
        else:
            info.update(source="summary", state="current", built_at=head.built_at.isoformat() if head.built_at else None, seconds=head.seconds)
            return _load(s, alpha3, part), info
    return compute_part(s, alpha3, part), info


def summary_state(alpha3: str) -> dict[str, Any]:
    """What the page asks while a build runs: the country's summary state, from the header alone (milliseconds, read-only, never raises)."""
    from sqlalchemy import inspect

    from src.osm.lane_models import (
        OsmCountry,
        OsmPlacesCount,
        OsmPlacesDay,
        OsmPlacesSummary,
        OsmPlacesValue,
    )
    from src.versioned import store

    out: dict[str, Any] = {"country": alpha3, "building": is_building(alpha3)}
    try:
        if not store.lane_exists("osm"):
            return {**out, "state": "lane-never-run"}
        with store.lane_session("osm") as s:
            have = set(inspect(s.get_bind()).get_table_names())
            country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
            if country is None or country.status != "complete":
                return {**out, "state": "not-cut"}
            if not all(m.__tablename__ in have for m in (OsmPlacesSummary, OsmPlacesCount, OsmPlacesValue, OsmPlacesDay)):
                return {**out, "state": "no-summary-table"}
            head = s.query(OsmPlacesSummary).filter_by(alpha3=alpha3).one_or_none()
            state = _head_state(head, country)
            return {**out, "state": state, "built_at": head.built_at.isoformat() if head is not None and state == "current" and head.built_at else None}
    except Exception as exc:  # noqa: BLE001 - the page keeps the computed answer it has
        log_failure(_LOG, f"osm: the {alpha3} places summary state could not be read", exc, level=logging.WARNING)
        return {**out, "state": "unreadable"}


# --------------------------------------------------------------------------- #
#  Writing                                                                     #
# --------------------------------------------------------------------------- #


def build_summary(alpha3: str, *, only_if_missing: bool = False) -> dict[str, Any]:
    """Compute and store every part for one country in one pass over its places. Raises only on a lane failure.

    The read and the write are two sessions on purpose: the pass can take minutes, and a write after a long read in the same transaction can be
    refused by a writer that committed meanwhile. The country row's ``finished_at`` and ``diff_sequence`` are read FIRST and stored with the
    rows, and read AGAIN before the write: a daily apply or a re-cut that landed during the pass makes it ``superseded`` and stores nothing, so a
    summary computed across two states of the places can never carry the key of either.
    """
    from sqlalchemy import delete, insert, inspect

    from src.osm.lane_models import (
        OsmCountry,
        OsmPlacesCount,
        OsmPlacesDay,
        OsmPlacesSummary,
        OsmPlacesValue,
    )
    from src.versioned import store

    if not store.lane_exists("osm"):
        return {"status": "lane-never-run"}
    # A lane file cut by an older build lacks the tables, and only a writer may add them: ``create_lane`` is idempotent and additive.
    store.create_lane("osm")
    rule = rule_version()
    with _SERIAL:
        t0 = time.monotonic()
        with store.lane_session("osm") as s:
            have = set(inspect(s.get_bind()).get_table_names())
            country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
            if country is None or country.status != "complete":
                return {"status": "not-cut"}
            finished, seq = country.finished_at, country.diff_sequence
            if only_if_missing and OsmPlacesSummary.__tablename__ in have:
                head = s.query(OsmPlacesSummary).filter_by(alpha3=alpha3).one_or_none()
                if _head_state(head, country) == "current":
                    return {"status": "current"}
            parts: dict[str, dict[str, Any]] = {}
            parts["freshness"] = compute_part(s, alpha3, "freshness")
            for part in PARTS:
                if part != "freshness":
                    parts[part] = compute_part(s, alpha3, part, days=parts["freshness"]["days"] if part == "geography" else None)
        seconds = round(time.monotonic() - t0, 3)
        with store.lane_session("osm") as s:
            now = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
            if now is None or now.status != "complete" or now.finished_at != finished or now.diff_sequence != seq:
                return {"status": "superseded"}
            for model in (OsmPlacesCount, OsmPlacesValue, OsmPlacesDay, OsmPlacesSummary):
                s.execute(delete(model).where(model.alpha3 == alpha3))
            counts = [{"alpha3": alpha3, "part": p, "name": k, "n": int(v)} for p, d in parts.items() for k, v in d["counts"].items()]
            vals = [{"alpha3": alpha3, "part": p, "key": k, "value": text, "n": int(n)} for p, d in parts.items() for k, rows in d["values"].items() for text, n in rows]
            days = [{"alpha3": alpha3, "part": p, "day": day, "n": int(n)} for p, d in parts.items() for day, n in d["days"]]
            for model, rows in ((OsmPlacesCount, counts), (OsmPlacesValue, vals), (OsmPlacesDay, days)):
                for i in range(0, len(rows), 50_000):
                    s.execute(insert(model), rows[i : i + 50_000])
            total = len(counts) + len(vals) + len(days)
            s.add(OsmPlacesSummary(alpha3=alpha3, rule_version=rule, cut_finished_at=finished, diff_sequence=seq, seconds=seconds, rows=total))
    return {"status": "built", "rows": total, "seconds": seconds}


def build_quietly(alpha3: str) -> None:
    """The cut and apply jobs' hook: a failed summary must never fail (or hide) a finished cut or apply; the readers compute until it is rebuilt."""
    with _RUN_LOCK:
        if alpha3 in _RUNNING:
            return
        _RUNNING.add(alpha3)
    try:
        res = build_summary(alpha3)
        _LOG.info("osm: the %s places summary: %s", alpha3, res.get("status"))
    except Exception as exc:  # noqa: BLE001 - recorded in the log; the computed path stays in place
        log_failure(_LOG, f"osm: the {alpha3} places summary could not be built", exc, level=logging.WARNING)
    finally:
        with _RUN_LOCK:
            _RUNNING.discard(alpha3)


def start_build(alpha3: str) -> dict[str, Any]:
    """Start :func:`build_summary` on a thread of its own, for a country that already exists; ``{"started": bool, "status": ...}``.

    Nothing that can refuse needs the lane, so this answers at once; the thread skips a country whose summary is already current.
    """
    with _RUN_LOCK:
        if alpha3 in _RUNNING:
            return {"started": False, "status": "building"}
        _RUNNING.add(alpha3)

    def run() -> None:
        try:
            res = build_summary(alpha3, only_if_missing=True)
            _LOG.info("osm: the %s places summary: %s", alpha3, res.get("status"))
        except Exception as exc:  # noqa: BLE001 - logged; the readers keep computing
            log_failure(_LOG, f"osm: the {alpha3} places summary could not be built", exc, level=logging.WARNING)
        finally:
            with _RUN_LOCK:
                _RUNNING.discard(alpha3)

    threading.Thread(target=run, name=f"osm-places-summary-{alpha3}", daemon=True).start()
    return {"started": True, "status": "building"}
