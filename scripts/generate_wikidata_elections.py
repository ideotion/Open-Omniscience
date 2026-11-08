#!/usr/bin/env python3
"""Generate the national-election SNAPSHOT from Wikidata (S06-04 slice S1, v0.6 plan row A2).

Wikidata is CC0. This runs on a NETWORKED machine, like ``generate_wikidata_rings.py``: the
offline app only READS the file it writes, through ``src.civic.calendar_report.snapshot_to_events``
(which refuses, degrades and labels every row; nothing here decides a tier). ONE SPARQL request
to the Wikidata Query Service, then a pure, offline-tested conversion.

WHAT A ROW IS, and the refusals that keep it honest:

* An election item (``P31/P279*`` of Q40231 "election") whose jurisdiction (``P1001``) is the
  SAME country item as its ``P17``, so a regional or municipal vote is not read as national.
  The country must carry an ISO 3166-1 alpha-2 code (``P297``); one that does not is refused
  with the reason, never guessed from a label.
* Primaries, caucuses, party-leadership contests, nominations and by-elections are NOT asked for:
  an item any of whose classes has an English label matching ``EXCLUDED_CLASS_PATTERN`` is left
  out (matched on the class LABEL, not on a hand-copied QID list, because this sandbox cannot look
  a QID up and a wrong QID would exclude the wrong thing silently). A "2028 Democratic
  presidential primaries" item otherwise passes P17 = P1001 = USA and reads as a national vote.
* ``office`` is the English label of ``P541`` (office contested). An election that names no
  office is refused, and so is one whose office has no English label, each with its own reason
  (the converter needs an office to layer against curated entries).
* The date is ``P585`` with its OWN precision (11 day, 10 month, 9 year; finer than a day is
  read as a day) or a ``P580``/``P582`` range. Deprecated-rank ``P585`` statements are ignored.
  Two different ``P585`` values for one election and office are a CONFLICT, refused with both
  values named and never resolved by picking one, with ONE exception: when EVERY value carries an
  ``applies to part`` (``P518``) qualifier, they are the ROUNDS of one election (France, Brazil,
  Portugal...), and the row takes the earliest upcoming round and lists them all under ``rounds``.
  A range end is the LATEST stated ``P582`` and its start the EARLIEST ``P580``, so reruns agree.
* ``official_url`` is ``P856`` (official website) when the item states one, else empty: the
  converter then degrades a day to a window, which is the point.
* Only upcoming or current elections are asked for: a date, a range end or (with no end) a range
  start on or after 1 January of the run year, because WDQS writes "this year" as ``YYYY-01-01``
  and "this month" as ``YYYY-MM-01``; the converter decides, per precision, what has passed.
  What the query does NOT ask for (no ``P1001``, the excluded classes, an item with no date at
  all) is named in the snapshot's ``not_asked_for``, so an absence is never mistaken for a refusal
  the file forgot.

The output is a COMPLETE REPLACEMENT of ``-o`` and refuses to overwrite a non-empty file without
``--force``. It carries ``as_of``, the query text and its sha256, the row count and every refusal.
Bundling it (a dated config, the ``*_AS_OF`` constant, its registry entry and freshness test in
the same commit) is the operator's reviewed step after a real run; this build sandbox cannot reach
query.wikidata.org, so the query is documented, not verified live.

Usage:
    python scripts/generate_wikidata_elections.py -o /tmp/election_snapshot.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
_UA = "OpenOmniscience-election-snapshot/0.1 (local-first research app)"

#: Wikidata time precision -> the converter's vocabulary. Anything coarser than a year is not a date;
#: anything finer than a day (12 hour, 13 minute, 14 second) still names a day.
PRECISIONS = {"14": "day", "13": "day", "12": "day", "11": "day", "10": "month", "9": "year"}

#: Classes whose items are not the national vote for an office (case-insensitive, on English labels).
EXCLUDED_CLASS_PATTERN = "primar|caucus|leadership|nominat|by-election|by election"

#: What the query deliberately leaves out, stated in every snapshot.
NOT_ASKED_FOR = [
    "elections whose jurisdiction (P1001) is not the country item itself, or that state none",
    f"items with a class whose English label matches /{EXCLUDED_CLASS_PATTERN}/i",
    "items with no P585 date and no P580/P582 range at all (nothing tells upcoming from past)",
    "items whose every date or range end is before 1 January of the run year",
]

QUERY_TEMPLATE = """\
SELECT ?election ?iso2 ?office ?officeLabel ?time ?precision ?part ?start ?end ?url WHERE {
  ?election wdt:P31/wdt:P279* wd:Q40231 ;
            wdt:P17 ?country ;
            wdt:P1001 ?country .
  FILTER NOT EXISTS { ?election wdt:P31 ?cls . ?cls rdfs:label ?clsLabel .
                      FILTER(LANG(?clsLabel) = "en" && REGEX(?clsLabel, "{excluded}", "i")) }
  OPTIONAL { ?country wdt:P297 ?iso2 . }
  OPTIONAL { ?election wdt:P541 ?office .
             OPTIONAL { ?office rdfs:label ?officeLabel . FILTER(LANG(?officeLabel) = "en") } }
  OPTIONAL { ?election p:P585 ?st . ?st wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank)
             ?st psv:P585 [ wikibase:timeValue ?time ; wikibase:timePrecision ?precision ] .
             OPTIONAL { ?st pq:P518 ?part . } }
  OPTIONAL { ?election wdt:P580 ?start . }
  OPTIONAL { ?election wdt:P582 ?end . }
  OPTIONAL { ?election wdt:P856 ?url . }
  FILTER( (BOUND(?time) && ?time >= "{year_start}T00:00:00Z"^^xsd:dateTime)
       || (!BOUND(?time) && BOUND(?end) && ?end >= "{year_start}T00:00:00Z"^^xsd:dateTime)
       || (!BOUND(?time) && !BOUND(?end) && BOUND(?start) && ?start >= "{year_start}T00:00:00Z"^^xsd:dateTime) )
}
"""


def build_query(today: date) -> str:
    """The cut-off is the 1st of January of ``today``'s year, never ``today`` itself: WDQS writes a
    year-precision date as ``YYYY-01-01`` and a month-precision one as ``YYYY-MM-01``, so a
    ``>= today`` filter would drop an election stated as "this year" or "this month" before it ever
    reached the converter, unrecorded. The converter decides what has passed, at each precision."""
    return QUERY_TEMPLATE.replace("{year_start}", f"{today.year:04d}-01-01").replace(
        "{excluded}", EXCLUDED_CLASS_PATTERN
    )


def query_url(query: str) -> str:
    return f"{WDQS_ENDPOINT}?{urllib.parse.urlencode({'query': query, 'format': 'json'})}"


def fetch_json(url: str, getter: Callable[[str], bytes] | None = None) -> dict:
    """GET + parse JSON. ``getter`` is injectable so tests never touch the network."""
    if getter is not None:
        return json.loads(getter(url))
    if not url.startswith(WDQS_ENDPOINT + "?"):
        raise ValueError("only the Wikidata Query Service endpoint is fetched")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/sparql-results+json"})
    # The URL is the fixed https WDQS endpoint, checked just above, so no file: or custom scheme is opened.
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310  # nosec B310
        return json.loads(r.read())


def _val(binding: dict, key: str) -> str:
    cell = binding.get(key)
    return str(cell.get("value", "")).strip() if isinstance(cell, dict) else ""


def _day(value: str) -> str:
    """``2027-04-10T00:00:00Z`` -> ``2027-04-10``: a WDQS time is midnight UTC plus a precision, so
    the time part says nothing; the date part is what the converter reads."""
    return value.split("T", 1)[0].lstrip("+") if value else ""


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if uri.startswith("http") else uri


def _not_passed(point: tuple[str, str], today: date | None) -> bool:
    """Has this (ISO day, precision) not passed by ``today``? The current month or year has not."""
    if today is None:
        return True
    day, precision = point
    if precision == "year":
        return day[:4] >= f"{today.year:04d}"
    if precision == "month":
        return day[:7] >= today.isoformat()[:7]
    return day >= today.isoformat()


def rows_from_sparql(payload: dict, today: date | None = None) -> tuple[list[dict], list[dict]]:
    """WDQS JSON -> ``(rows, refused)``; one row per (election, office). Pure and offline.

    Raises ``ValueError`` when the payload is not a SPARQL JSON result at all (an error page),
    so an unreadable answer is never written as an empty snapshot.
    """
    try:
        bindings = payload["results"]["bindings"]
    except (KeyError, TypeError):
        raise ValueError("not a SPARQL JSON result (no results.bindings)") from None
    if not isinstance(bindings, list):
        raise ValueError("not a SPARQL JSON result (results.bindings is not a list)")
    grouped: dict[tuple[str, str], dict] = {}
    refused: list[dict] = []
    refused_keys: set[tuple[str, str]] = set()
    for b in bindings:
        qid = _qid(_val(b, "election"))
        if not qid:
            continue
        iso2 = _val(b, "iso2").lower()
        office = _val(b, "officeLabel")
        if len(iso2) != 2 or not iso2.isalpha():
            key = (qid, "")
            if key not in refused_keys:
                refused_keys.add(key)
                refused.append({"qid": qid, "reason": "the country carries no ISO 3166-1 alpha-2 code (P297)"})
            continue
        if not office:
            key = (qid, "")
            if key not in refused_keys:
                refused_keys.add(key)
                why = (
                    "the office contested (P541) has no English label"
                    if _val(b, "office")
                    else "the election names no office contested (P541)"
                )
                refused.append({"qid": qid, "reason": why})
            continue
        row = grouped.setdefault(
            (qid, office),
            {"qid": qid, "country": iso2, "office": office, "points": set(), "start": "", "end": "", "official_url": ""},
        )
        time, precision = _val(b, "time"), _val(b, "precision")
        if time:
            point = (_day(time), PRECISIONS.get(precision, f"unknown:{precision}"))
            row["points"].add(point)
            if _val(b, "part"):
                row.setdefault("parted", set()).add(point)
        # Several P580/P582 values: the widest range, so the answer does not hang on WDQS order.
        start, end = _day(_val(b, "start")), _day(_val(b, "end"))
        if start and (not row["start"] or start < row["start"]):
            row["start"] = start
        if end and end > row["end"]:
            row["end"] = end
        url = _val(b, "url")
        if url and (not row["official_url"] or url < row["official_url"]):
            row["official_url"] = url  # WDQS order is not stable: the smallest URL, so reruns agree
    rows: list[dict] = []
    for (qid, office), row in sorted(grouped.items()):
        points = sorted(row.pop("points"))
        parted = row.pop("parted", set())
        if len(points) > 1 and parted == set(points):
            # Every value is qualified "applies to part": the rounds of ONE election. The earliest
            # round not yet passed is the date (else the last, which the converter refuses as past);
            # all of them are named.
            row["rounds"] = [f"{t} ({p})" for t, p in points]
            upcoming = [pt for pt in points if _not_passed(pt, today)]
            points = (upcoming or points)[:1]
        if len(points) > 1:
            refused.append(
                {"qid": qid, "reason": f"conflicting P585 values for office {office!r}: "
                 + ", ".join(f"{t} ({p})" for t, p in points)}
            )
            continue
        if points:
            row["point_in_time"], row["precision"] = points[0]
        rows.append({k: v for k, v in row.items() if v != ""})
    return rows, refused


def build_snapshot(today: date, getter: Callable[[str], bytes] | None = None) -> dict:
    query = build_query(today)
    rows, refused = rows_from_sparql(fetch_json(query_url(query), getter), today)
    return {
        "as_of": today.isoformat(),
        "source": "Wikidata (CC0) via the Wikidata Query Service",
        "query": query,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "n_rows": len(rows),
        "rows": rows,
        "refused": refused,
        "not_asked_for": NOT_ASKED_FOR,
    }


def _refuse_overwrite(out: Path, force: bool) -> str | None:
    if force or not out.exists():
        return None
    try:
        if out.stat().st_size == 0:
            return None
    except OSError:
        return None
    return f"refusing to overwrite {out}: this script REPLACES its output; write to a fresh path or pass --force"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", type=Path, required=True, help="output JSON path (a full replacement)")
    ap.add_argument("--force", action="store_true", help="allow replacing an existing non-empty file")
    args = ap.parse_args(argv)
    if (msg := _refuse_overwrite(args.out, args.force)):
        print(msg, file=sys.stderr)
        return 2
    if not args.out.parent.is_dir():  # checked before the query, so a typo costs no WDQS call
        print(f"refusing: the directory {args.out.parent} does not exist", file=sys.stderr)
        return 2
    snap = build_snapshot(date.today())
    args.out.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[wrote {snap['n_rows']} rows, {len(snap['refused'])} refused -> {args.out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
