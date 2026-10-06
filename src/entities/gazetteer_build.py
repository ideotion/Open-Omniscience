"""The place gazetteer's build, as pure functions (0.5 row C, S05-03 S4, Q805).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``scripts/build_place_gazetteer.py`` is the thin CLI over this. It reads the ``place=*`` objects
of ONE OR MORE complete countries out of row D's ``osm.db``, joins each to Wikidata, and writes
``configs/places_gazetteer.yml`` in the shape :mod:`src.catalog.cities` loads. The loader reads that
file BESIDE the world-city file and merges the two by QID (see its docstring).

WHAT COMES FROM WHERE.

* **Identity** -- the QID is the one OpenStreetMap's own ``wikidata=*`` tag names, exactly as it is
  written. A place with no tag, or with a value that is not a single QID (``Q1;Q2``), gets NO QID,
  never a guess: a wrong QID would make two places one.
* **Where** -- the OSM coordinate. Wikidata's ``P625`` is only CHECKED against it: the distance is
  recorded when the two differ by more than :data:`COORD_CHECK_KM`, and neither is corrected.
* **Names** -- the OSM ``name:xx`` tags first, Wikidata's label as the fallback, each name's source
  recorded; a language neither has is left out, never filled in (Q827).
* **Population** -- Wikidata's ``P1082`` at PREFERRED rank, or, with none, the claim with the
  latest ``P585`` (point in time); its date and rank are recorded and OpenStreetMap's own
  ``population`` is kept BESIDE it. No source is blended into a third number.

WHICH WIKIDATA API, AND AT WHAT PACE. The Action API's ``wbgetentities`` on ``www.wikidata.org`` --
the host ``docs/SECURITY.md`` already lists for the entity spine, so this adds no host -- up to
:data:`~src.entities.wikidata_items.BATCH_MAX` items a request, ONE REQUEST AT A TIME, every request
carrying ``maxlag`` and the descriptive User-Agent below, a ``Retry-After`` honoured. The spacing is
the app's own R8 gate (``RateGate``, one request per 10 s): it protects Wikidata's shared servers --
automated reading is asked to stay at that rate, ``maxlag`` only reacts AFTER the servers are under
load -- and the standing of this User-Agent, which an operator's ban would end for every install.
The query is not SPARQL: it is ``action=wbgetentities&ids=Q1|Q2|...&props=labels|descriptions|claims``,
the same URL :func:`src.entities.wikidata_items.entities_url` builds for the item cache. The run time
is a formula (:func:`plan`), never a guess: ``(requests - 1) x 10 s``.

NOTHING HERE OPENS A SOCKET. The fetch takes an injected ``getter``; only the CLI's ``--online``
passes the guarded one, and the kill switch refuses it by name (:class:`AirplaneRefusal`).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml

from src.analytics.wikidata_rings import LANGS
from src.entities.wikidata_items import BATCH_MAX, batches, entities_url, is_qid, parse_entities

#: The descriptive User-Agent Wikimedia's policy asks for: what it is, where it lives, who to tell.
USER_AGENT = (
    "OpenOmniscience-place-gazetteer/0.5 (+https://github.com/ideotion/Open-Omniscience; "
    "place gazetteer artifact build, one request at a time; contact open-omniscience@ideotion.com)"
)

#: ``maxlag`` (seconds) added to every request: the server answers "maxlag" with a ``Retry-After``
#: instead of the data when its replicas are that far behind, and this run waits and tries again.
MAXLAG_S = 5

#: How often one batch is retried on a 429, a 503 or a ``maxlag`` answer before it is counted
#: ``refused``. 5 protects the run from hammering a server that keeps saying "wait" (each retry is
#: itself spaced by the pace gate) while still riding out a short replication lag.
RETRY_MAX = 5
#: The longest single wait a ``Retry-After`` may impose. 300 s protects the run from hanging for
#: hours on a huge or hostile header value; a server that wants longer than five minutes gets the
#: batch counted ``refused`` and the run stops short of writing an artifact.
RETRY_CAP_S = 300.0

#: After this many batches in a row that the server (or a dead proxy) refused, the run stops asking: a paced
#: run of refusals costs hours at 10 s a request and ends in nothing written, and the operator should hear
#: about a dead transport after a minute, not after the whole run. The rest is counted ``not_asked``.
CONSECUTIVE_REFUSED_MAX = 3

#: A Wikidata coordinate further than this from the OSM point is recorded as a disagreement.
COORD_CHECK_KM = 25.0

SOURCE_BOTH = "osm+wikidata"
SOURCE_OSM = "osm"

LICENSE_LINE = (
    "Place names, coordinates and OSM population: (c) OpenStreetMap contributors, ODbL 1.0 "
    "(https://www.openstreetmap.org/copyright). Wikidata values: CC0."
)

_OSM_TYPE = {"n": "node", "w": "way", "r": "relation"}
_POP_RE = re.compile(r"^\d{1,3}(?:[ ,.  ]\d{3})+$|^\d+$")


class GazetteerBuildError(RuntimeError):
    """A refusal with its reason in words; the CLI prints it and exits 2."""


class AirplaneRefusal(GazetteerBuildError):
    """The kill switch refused the Wikidata join, and says so in as many words."""


class TransportRefusal(GazetteerBuildError):
    """The guarded fetch path refused the join because the operator's transport is unavailable."""


# --------------------------------------------------------------------------- #
#  reading row D's osm.db
# --------------------------------------------------------------------------- #


@dataclass
class OsmPlace:
    osm: str
    kind: str
    name: str | None
    names: dict[str, str]
    lat: float
    lon: float
    qid: str | None
    population: int | None


def clean_wikidata_tag(value: object) -> str | None:
    """The QID an OSM ``wikidata=*`` value names, or None. ``Q1;Q2`` and ``q1`` are None: never repaired."""
    v = str(value or "").strip()
    return v if is_qid(v) else None


def parse_osm_population(value: object) -> int | None:
    """OSM's ``population`` as an integer, or None. ``12 345`` and ``12,345`` read; ``~12k`` does not."""
    v = str(value or "").strip()
    if not v or not _POP_RE.match(v):
        return None
    n = int(re.sub(r"[ ,.  ]", "", v))
    return n if n > 0 else None


def read_places(alpha3: str) -> tuple[dict, list[OsmPlace], dict]:
    """``(country, places, counts)`` for one COMPLETE country of ``osm.db``. Local, read-only.

    A country whose ingest did not finish is refused by name: a half-read country would write a
    gazetteer that looks complete. A ``place`` with no point (a relation) is counted, never given
    a (0, 0).
    """
    from sqlalchemy import text

    from src.versioned.store import lane_exists, lane_session

    if not lane_exists("osm"):
        raise GazetteerBuildError("there is no osm.db in this data directory; ingest a country first")
    with lane_session("osm") as s:
        row = s.execute(
            text("SELECT alpha2, alpha3, name, status, extract_vintage FROM osm_countries WHERE alpha3 = :a"),
            {"a": alpha3},
        ).first()
        if row is None:
            raise GazetteerBuildError(f"{alpha3} has not been ingested into this osm.db")
        if row[3] != "complete":
            raise GazetteerBuildError(
                f"{alpha3}'s ingest is {row[3]!r}, not complete: a partial country would write a gazetteer "
                "that reads as whole"
            )
        vintage = row[4]
        country = {
            "alpha2": row[0],
            "alpha3": row[1],
            "name": row[2],
            "vintage": vintage.date().isoformat() if isinstance(vintage, datetime) else (str(vintage)[:10] if vintage else None),
        }
        counts = {"place_objects": 0, "no_point": 0, "with_wikidata_tag": 0, "bad_wikidata_tag": 0}
        out: list[OsmPlace] = []
        for t, oid, kind, name, names_json, lat, lon, wd, pop in s.execute(
            text(
                "SELECT osm_type, osm_id, t_place, t_name, names, lat, lon, t_wikidata, t_population "
                "FROM osm_objects WHERE country_alpha3 = :a AND kind = 'place' ORDER BY osm_type, osm_id"
            ),
            {"a": alpha3},
        ):
            counts["place_objects"] += 1
            if lat is None or lon is None:
                counts["no_point"] += 1
                continue
            qid = clean_wikidata_tag(wd)
            if wd:
                counts["with_wikidata_tag"] += 1
                if qid is None:
                    counts["bad_wikidata_tag"] += 1
            try:
                names = json.loads(names_json) if names_json else {}
            except ValueError:
                names = {}
            out.append(
                OsmPlace(
                    osm=f"{_OSM_TYPE.get(t, t)}/{oid}",
                    kind=str(kind or ""),
                    name=(name or None),
                    names={str(k).strip().lower(): str(v) for k, v in names.items() if k and v}
                    if isinstance(names, dict) else {},
                    lat=float(lat),
                    lon=float(lon),
                    qid=qid,
                    population=parse_osm_population(pop),
                )
            )
    return country, out, counts


# --------------------------------------------------------------------------- #
#  the Wikidata side: parsing
# --------------------------------------------------------------------------- #


@dataclass
class WikiItem:
    qid: str
    status: str  # "ok" | "missing"
    resolved_qid: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    coord: tuple[float, float] | None = None
    population: dict | None = None  # {"value", "date", "rank"}


def _wd_time(value: object, precision: object) -> str | None:
    """A Wikidata time as far as its precision goes: ``+2019-00-00T..`` at year precision is ``2019``."""
    if not isinstance(value, str):
        return None
    m = re.match(r"^[+-]?(\d{1,4})-(\d{2})-(\d{2})", value)
    if not m:
        return None
    year, month, day = m.groups()
    year = year.zfill(4)
    p = precision if isinstance(precision, int) else 11
    if p <= 9:
        return year
    if p == 10:
        return f"{year}-{month}"
    return f"{year}-{month}-{day}"


def pick_population(claims: object) -> dict | None:
    """The one P1082 claim the gazetteer takes: preferred rank, else the latest ``P585``.

    Deprecated claims never count. Among several preferred claims (or, with none, several normal
    ones) the latest point in time wins; a claim with no date sorts before every dated one, and a
    tie keeps the first listed. The chosen claim's date and rank are returned beside its value.
    """
    if not isinstance(claims, list):
        return None
    cands: list[dict] = []
    for i, c in enumerate(claims):
        if not isinstance(c, dict) or c.get("rank") == "deprecated":
            continue
        dv = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        amount = dv.get("amount") if isinstance(dv, dict) else None
        try:
            n = int(Decimal(str(amount)))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if n <= 0:
            continue
        when = None
        for q in ((c.get("qualifiers") or {}).get("P585") or []):
            tv = (q.get("datavalue") or {}).get("value") if isinstance(q, dict) else None
            if isinstance(tv, dict):
                when = _wd_time(tv.get("time"), tv.get("precision"))
                break
        cands.append({"value": n, "date": when, "rank": c.get("rank") or "normal", "_i": i})
    if not cands:
        return None
    preferred = [c for c in cands if c["rank"] == "preferred"]
    pool = preferred or cands
    best = max(pool, key=lambda c: (c["date"] or "", -c["_i"]))
    return {"value": best["value"], "date": best["date"], "rank": best["rank"]}


def parse_wikidata(payload: dict, asked: list[str]) -> dict[str, WikiItem]:
    """Every asked id the answer mentions, as :class:`WikiItem`; the rest are simply absent."""
    entities = (payload or {}).get("entities") or {}
    out: dict[str, WikiItem] = {}
    for p in parse_entities(payload, asked):
        item = WikiItem(qid=p.qid, status=p.status, resolved_qid=p.resolved_qid, labels=dict(p.labels))
        if p.status == "ok":
            pts = (p.claims or {}).get("P625") or []
            if pts:
                item.coord = (pts[0]["lat"], pts[0]["lon"])
            ent = entities.get(p.resolved_qid or p.qid)
            if isinstance(ent, dict):
                item.population = pick_population((ent.get("claims") or {}).get("P1082"))
        out[p.qid] = item
    return out


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres (haversine, mean Earth radius 6371.0088 km)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------- #
#  the pace and the fetch
# --------------------------------------------------------------------------- #


def plan(n_qids: int, *, seconds_per_request: float | None = None) -> dict:
    """What a Wikidata join of ``n_qids`` costs, by arithmetic only. No network, no measurement."""
    if seconds_per_request is None:
        from src.analytics.wikidata_rings import POLITE_SLEEP_S

        seconds_per_request = POLITE_SLEEP_S
    requests = (max(0, n_qids) + BATCH_MAX - 1) // BATCH_MAX
    secs = max(0, requests - 1) * seconds_per_request
    return {
        "qids_expected": n_qids,
        "batch_size": BATCH_MAX,
        "requests": requests,
        "seconds_per_request": seconds_per_request,
        "min_seconds": secs,
        "min_hours": round(secs / 3600, 2),
        "formula": "requests = ceil(qids / 50); minimum run time = (requests - 1) x seconds_per_request",
        "endpoint": "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=<up to 50 QIDs>&props=labels|descriptions|claims",
    }


@dataclass
class GetResult:
    """What one guarded GET answered, reduced to what the loop decides on."""

    status: int
    body: dict | None = None
    retry_after: float | None = None


def _retry_after_seconds(value: object) -> float | None:
    """Seconds from a ``Retry-After`` header: the delta-seconds form or the HTTP-date form."""
    if value is None:
        return None
    try:
        v = float(str(value))
    except (TypeError, ValueError):
        from email.utils import parsedate_to_datetime

        try:
            when = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        v = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, v) if v == v else None  # a negative date is "now"; NaN is no answer


def guarded_getter(url: str) -> GetResult:
    """One GET on the app's one fetch path (kill switch, the operator's transport, the honest UA)."""
    from src.safety.fetcher import guarded_session

    resp = guarded_session(user_agent=USER_AGENT, isolation_token=url).get(url, timeout=30)
    body = None
    if resp.status_code == 200:
        try:
            body = json.loads(resp.text)
        except ValueError:
            body = None
    return GetResult(resp.status_code, body, _retry_after_seconds(resp.headers.get("Retry-After")))


def transport_state() -> dict:
    """The transport an ``--online`` join would use, and whether the operator CHOSE it.

    ``explicit`` is True when this data directory holds persisted safety settings or the environment
    names one (``OO_FETCH_MODE``, ``OO_HTTP_PROXY``, ``OO_HTTP_PROXIES``). A build run against a
    throwaway or fresh store has neither, so the default (clearnet) would apply SILENTLY -- on an
    install whose operator chose Tor, that is a deanonymisation rather than a default. The CLI therefore
    refuses ``--online`` unless the transport is explicit or the operator says ``--clearnet``.
    """
    import os

    from src.safety import settings as safety

    st = safety.load_settings()
    named = any(os.getenv(k) is not None for k in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"))
    try:
        persisted = safety._read_raw() is not None  # read-only; a missing or locked store reads as absent
    except Exception:  # noqa: BLE001
        persisted = False
    return {"mode": st.fetch_mode, "protected": st.is_protected, "explicit": persisted or named}


def _kill_switch_active() -> bool:
    from src.ingest import kill_switch_active

    return bool(kill_switch_active())


def _reraise_refusal(exc: BaseException) -> None:
    """Turn the guarded path's refusals into the named ones; any other failure returns to be counted."""
    from src.safety.fetcher import NetworkBlocked, TransportUnavailable

    if isinstance(exc, NetworkBlocked):
        raise AirplaneRefusal(f"network refused: {exc}") from None
    if isinstance(exc, TransportUnavailable):
        raise TransportRefusal(f"the operator's transport is unavailable: {exc}") from None


def _asks_to_wait(res: GetResult) -> bool:
    if res.status in (429, 503):
        return True
    err = (res.body or {}).get("error") if isinstance(res.body, dict) else None
    return isinstance(err, dict) and err.get("code") == "maxlag"


def fetch_wikidata(
    qids: Iterable[str],
    *,
    getter: Callable[[str], GetResult],
    gate=None,
    sleep: Callable[[float], object] = time.sleep,
    kill_switch: Callable[[], bool] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[dict[str, WikiItem], dict]:
    """Ask Wikidata for ``qids``, one request at a time, and parse the answers.

    Refuses by name under the kill switch, before the first request and before every request (this
    process's own switch: a build run from a shell cannot see another process's airplane state, so the
    ``--online`` flag is the operator's consent). An unavailable transport or a kill-switch refusal from
    the guarded fetch path stops the run with a named refusal; it is never counted as a batch's
    failure. The pace gate is waited on before EVERY request, retries included. A
    ``Retry-After`` (or the ``maxlag`` answer's) is waited out, at most :data:`RETRY_CAP_S` per
    wait and :data:`RETRY_MAX` waits per batch; a batch that still fails is counted ``refused`` and
    the run goes on. The three counts add up to what was asked.
    """
    from src.analytics.ring_loader import RateGate

    if kill_switch is None:
        kill_switch = _kill_switch_active  # looked up now, so a test (or a caller) can replace it
    if kill_switch():
        raise AirplaneRefusal(
            "network refused: airplane mode is engaged (the gazetteer's Wikidata join makes no request "
            "while the kill switch is on)"
        )
    rg = gate or RateGate(stop=should_stop)
    todo = batches(list(qids))
    asked = sum(len(b) for b in todo)
    items: dict[str, WikiItem] = {}
    ok = missing = refused = waited_for_server = 0
    requests_made = 0
    stopped = airplane = gave_up = False
    refused_in_a_row = done = 0
    for batch in todo:
        if should_stop is not None and should_stop():
            stopped = True
            break
        url = f"{entities_url(batch)}&maxlag={MAXLAG_S}"
        parsed: dict[str, WikiItem] | None = None
        for attempt in range(RETRY_MAX + 1):
            # The gate spaces EVERY request, a retry included: a retry that skipped it would leave the
            # next batch due immediately, two requests back to back.
            rg.wait()
            if should_stop is not None and should_stop():  # the gate's wait ends early on a stop
                stopped = True
                break
            if kill_switch():
                airplane = True
                break
            requests_made += 1
            try:
                res = getter(url)
            except Exception as exc:  # noqa: BLE001 - one failed batch is counted, never fatal ...
                _reraise_refusal(exc)  # ... except a refusal by the transport or the kill switch
                break
            if res.status == 200 and res.body is not None and not _asks_to_wait(res):
                parsed = parse_wikidata(res.body, batch)
                break
            if not _asks_to_wait(res) or attempt == RETRY_MAX:
                break
            # The server asked us to wait: honour it, but never less than the gate's own spacing.
            wait = min(RETRY_CAP_S, max(res.retry_after or 0.0, float(rg.min_interval_s)))
            waited_for_server += 1
            sleep(wait)
            if should_stop is not None and should_stop():
                stopped = True
                break
            if kill_switch():
                airplane = True
                break
        if parsed is None and (stopped or airplane):
            break  # interrupted mid-wait: this batch was neither answered nor refused, it is `not_asked`
        done += len(batch)
        if parsed is None:
            refused += len(batch)
            refused_in_a_row += 1
            if refused_in_a_row >= CONSECUTIVE_REFUSED_MAX:
                gave_up = True  # the rest stays `not_asked`: the run stops asking a server that keeps refusing
                break
            continue
        refused_in_a_row = 0
        items.update(parsed)
        ok += sum(1 for p in parsed.values() if p.status == "ok")
        missing += sum(1 for p in parsed.values() if p.status == "missing")
        refused += len(batch) - len(parsed)
    return items, {
        "asked": asked,
        "ok": ok,
        "missing_on_wikidata": missing,
        "refused": refused,
        "not_asked": max(0, asked - done),
        "requests_made": requests_made,
        "waited_for_server": waited_for_server,
        "stopped": stopped,
        "stopped_by_airplane_mode": airplane,
        "gave_up_after_refusals": gave_up,
    }


def items_from_fixture(path: Path) -> dict[str, WikiItem]:
    """A recorded ``wbgetentities`` answer (or a list of them) read as the live path would parse it."""
    raw = json.loads(Path(path).read_text("utf-8"))
    payloads = raw if isinstance(raw, list) else [raw]
    items: dict[str, WikiItem] = {}
    for pl in payloads:
        ents = pl.get("entities") or {}
        ids = [q for q in ents if is_qid(q)]
        for e in ents.values():
            red = e.get("redirects") if isinstance(e, dict) else None
            if isinstance(red, dict) and is_qid(red.get("from")):
                ids.append(red["from"])
        items.update(parse_wikidata(pl, ids))
    return items


# --------------------------------------------------------------------------- #
#  building the entries
# --------------------------------------------------------------------------- #


def build_entries(
    places: list[OsmPlace],
    items: dict[str, WikiItem] | None,
    *,
    country_alpha2: str,
    langs: tuple[str, ...] = LANGS,
) -> tuple[list[dict], dict]:
    """The gazetteer entries for ``places`` and what happened to each place, counted.

    ``items`` is None when Wikidata was not joined at all (the OSM-only build): every entry then
    says ``source: osm`` and carries no Wikidata-derived value.
    """
    cc = country_alpha2.lower()
    stats = {
        "places": len(places), "entries": 0, "unnamed_skipped": 0,
        "with_qid": 0, "qid_missing_on_wikidata": 0, "qid_redirected": 0,
        "name_from_wikidata": 0, "names_from_osm": 0, "names_from_wikidata": 0,
        "population_from_wikidata": 0, "population_from_osm": 0, "population_unknown": 0,
        "population_disagree": 0, "coord_differs": 0,
    }
    entries: list[dict] = []
    for pl in places:
        item = items.get(pl.qid) if (items is not None and pl.qid) else None
        usable = item if (item is not None and item.status == "ok") else None

        name, name_source = pl.name, "osm"
        if not name and pl.names.get("en"):
            name, name_source = pl.names["en"], "osm:name:en"
        if not name and usable is not None and usable.labels.get("en"):
            name, name_source = usable.labels["en"], "wikidata"
            stats["name_from_wikidata"] += 1
        if not name:
            stats["unnamed_skipped"] += 1
            continue

        names: dict[str, str] = {}
        names_source: dict[str, str] = {}
        for lg in langs:
            if pl.names.get(lg):
                names[lg], names_source[lg] = pl.names[lg], "osm"
                stats["names_from_osm"] += 1
            elif usable is not None and usable.labels.get(lg):
                names[lg], names_source[lg] = usable.labels[lg], "wikidata"
                stats["names_from_wikidata"] += 1

        e: dict = {
            "name": name,
            "lat": round(pl.lat, 7),
            "lon": round(pl.lon, 7),
            "country": cc,
            "osm": pl.osm,
            "kind": pl.kind,
            "source": SOURCE_BOTH if usable is not None else SOURCE_OSM,
        }
        if name_source != "osm":
            e["name_source"] = name_source
        if names:
            e["names"] = names
            e["names_source"] = names_source
        if pl.qid:
            e["qid"] = pl.qid
            stats["with_qid"] += 1
            if item is not None and item.status == "missing":
                e["qid_status"] = "missing-on-wikidata"
                stats["qid_missing_on_wikidata"] += 1
            if item is not None and item.resolved_qid:
                e["qid_resolved"] = item.resolved_qid
                stats["qid_redirected"] += 1

        wd_pop = usable.population if usable is not None else None
        if wd_pop is not None:
            e["population"] = wd_pop["value"]
            e["population_source"] = "wikidata:P1082"
            e["population_rank"] = wd_pop["rank"]
            if wd_pop["date"]:
                e["population_date"] = wd_pop["date"]
            stats["population_from_wikidata"] += 1
            if pl.population is not None:
                e["population_osm"] = pl.population
                if pl.population != wd_pop["value"]:
                    stats["population_disagree"] += 1
        elif pl.population is not None:
            e["population"] = pl.population
            e["population_source"] = "osm"
            stats["population_from_osm"] += 1
        else:
            stats["population_unknown"] += 1

        if usable is not None and usable.coord is not None:
            d = km_between((pl.lat, pl.lon), usable.coord)
            if d > COORD_CHECK_KM:
                e["coord_check"] = {"wikidata_differs_km": round(d, 1)}
                stats["coord_differs"] += 1
        entries.append(e)
    entries.sort(key=lambda x: (x["country"], x["name"].casefold(), x["osm"]))
    stats["entries"] = len(entries)
    return entries, stats


# --------------------------------------------------------------------------- #
#  the artifact
# --------------------------------------------------------------------------- #

_HEADER = (
    "# Open Omniscience -- place gazetteer (0.5 row C, S05-03 S4). GENERATED by\n"
    "# scripts/build_place_gazetteer.py from ingested OpenStreetMap place=* objects joined to Wikidata.\n"
    "# Do not edit by hand: the next build overwrites it. Read BESIDE configs/cities.yml, merged by QID.\n"
)


def render_yaml(entries: list[dict], *, countries: list[dict], wikidata: dict, built: date) -> str:
    """The artifact's bytes. Sorted at every level, so the same input is the same file."""
    vintages = [c["vintage"] for c in countries]
    doc: dict = {
        "built": built.isoformat(),
        "cities": entries,
        "countries": [{"alpha2": c["alpha2"], "alpha3": c["alpha3"], "extract_vintage": c["vintage"]} for c in countries],
        "license": LICENSE_LINE,
        "source": SOURCE_BOTH if wikidata.get("joined") else SOURCE_OSM,
        "wikidata": wikidata,
    }
    # The vintage is as old as the OLDEST extract, and absent when any extract does not say.
    if vintages and all(vintages):
        doc["as_of"] = min(vintages)
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=True, default_flow_style=False, width=4096)
    return _HEADER + body


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def registry_entry(*, path: str, sha256: str, vintage: str | None, built: date) -> str:
    """The ``configs/external_artifacts.yml`` entry to add in the artifact's own PR (printed, never written)."""
    return (
        "  - id: place-gazetteer\n"
        "    title: Place gazetteer (OSM place=* joined to Wikidata)\n"
        "    kind: vendored-data\n"
        "    description: >-\n"
        "      The place artifact scripts/build_place_gazetteer.py builds from ingested OpenStreetMap place=*\n"
        "      objects joined to Wikidata (population, names x12, QID). Read beside configs/cities.yml and\n"
        "      merged by QID; the extract's own date is its vintage.\n"
        "    upstream: https://www.openstreetmap.org/copyright\n"
        "    fetched_from: the operator's own osm.db (row D's ingest) + www.wikidata.org wbgetentities\n"
        '    check_upstream: "rebuild after a new ingest of the country; the vintage is the extract\'s date"\n'
        "    license: ODbL 1.0 (OSM-derived; credit (c) OpenStreetMap contributors) + CC0 (Wikidata)\n"
        f'    pin: {{path: {path}, sha256: "{sha256}"}}\n'
        '    refresh: "python scripts/build_place_gazetteer.py --country <CC> --online"\n'
        "    freshness: {max_age_months: 12}\n"
        f'    last_verified: "{built.isoformat()}"  # extract vintage: {vintage or "not stated by the file"}\n'
    )


def write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` without ever leaving a half-written artifact beside it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def today() -> date:
    return datetime.now(UTC).date()
