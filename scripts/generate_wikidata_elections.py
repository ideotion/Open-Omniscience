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
* ``office`` is the English label of ``P541`` (office contested). An election that names no
  office is refused (the converter needs one to layer against curated entries).
* The date is ``P585`` with its OWN precision (11 day, 10 month, 9 year) or a ``P580``/``P582``
  range. Two different ``P585`` values for one election and office are a CONFLICT: the row is
  refused with both values named, never resolved by picking one.
* ``official_url`` is ``P856`` (official website) when the item states one, else empty: the
  converter then degrades a day to a window, which is the point.
* Only upcoming or current elections are asked for (a date or range end on or after the run
  date); the converter refuses a past one again in any case.

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

#: Wikidata time precision -> the converter's vocabulary. Anything coarser than a year is not a date.
PRECISIONS = {"11": "day", "10": "month", "9": "year"}

QUERY_TEMPLATE = """\
SELECT ?election ?iso2 ?officeLabel ?time ?precision ?start ?end ?url WHERE {
  ?election wdt:P31/wdt:P279* wd:Q40231 ;
            wdt:P17 ?country ;
            wdt:P1001 ?country .
  OPTIONAL { ?country wdt:P297 ?iso2 . }
  OPTIONAL { ?election wdt:P541 ?office .
             ?office rdfs:label ?officeLabel . FILTER(LANG(?officeLabel) = "en") }
  OPTIONAL { ?election p:P585 ?st . ?st wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank)
             ?st psv:P585 [ wikibase:timeValue ?time ; wikibase:timePrecision ?precision ] . }
  OPTIONAL { ?election wdt:P580 ?start . }
  OPTIONAL { ?election wdt:P582 ?end . }
  OPTIONAL { ?election wdt:P856 ?url . }
  FILTER( (BOUND(?time) && ?time >= "{year_start}T00:00:00Z"^^xsd:dateTime)
       || (!BOUND(?time) && BOUND(?end) && ?end >= "{year_start}T00:00:00Z"^^xsd:dateTime) )
}
"""


def build_query(today: date) -> str:
    """The cut-off is the 1st of January of ``today``'s year, never ``today`` itself: WDQS writes a
    year-precision date as ``YYYY-01-01`` and a month-precision one as ``YYYY-MM-01``, so a
    ``>= today`` filter would drop an election stated as "this year" or "this month" before it ever
    reached the converter, unrecorded. The converter decides what has passed, at each precision."""
    return QUERY_TEMPLATE.replace("{year_start}", f"{today.year:04d}-01-01")


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


def rows_from_sparql(payload: dict) -> tuple[list[dict], list[dict]]:
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
                refused.append({"qid": qid, "reason": "the election names no office contested (P541)"})
            continue
        row = grouped.setdefault(
            (qid, office),
            {"qid": qid, "country": iso2, "office": office, "points": set(), "start": "", "end": "", "official_url": ""},
        )
        time, precision = _val(b, "time"), _val(b, "precision")
        if time:
            row["points"].add((_day(time), PRECISIONS.get(precision, f"unknown:{precision}")))
        row["start"] = row["start"] or _day(_val(b, "start"))
        row["end"] = row["end"] or _day(_val(b, "end"))
        url = _val(b, "url")
        if url and (not row["official_url"] or url < row["official_url"]):
            row["official_url"] = url  # WDQS order is not stable: the smallest URL, so reruns agree
    rows: list[dict] = []
    for (qid, office), row in sorted(grouped.items()):
        points = sorted(row.pop("points"))
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
    rows, refused = rows_from_sparql(fetch_json(query_url(query), getter))
    return {
        "as_of": today.isoformat(),
        "source": "Wikidata (CC0) via the Wikidata Query Service",
        "query": query,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "n_rows": len(rows),
        "rows": rows,
        "refused": refused,
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
    snap = build_snapshot(date.today())
    args.out.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[wrote {snap['n_rows']} rows, {len(snap['refused'])} refused -> {args.out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
