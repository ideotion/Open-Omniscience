#!/usr/bin/env python3
"""Propose dated rosters for the political blocs the registry holds EMPTY, for a reviewer to confirm (row 123; 0.6 gate row A, RC08.4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. ``src/catalog/blocs.py`` lists thirteen political blocs (BRICS, NATO, the EU ...) as known but EMPTY: accession and
departure dates are sourced facts, and ruling 45 forbids guessing one to make a series continuous. Register ruling G3 adds that
the roster stays empty until a networked session returns dated, sourced rows, because a partial roster is more dangerous than
none. This script is that session's first half, run by the operator. It PROPOSES; it never writes ``blocs.py``. A lane reads the
report, checks each row against the organisation's own membership page, and writes only what it confirmed, in a reviewed pull
request. Until then the registry stays empty and the World map's group picker says "membership not held" (×12).

WHAT IT ASKS. One read of the Wikidata Query Service per bloc, the bloc named by its English Wikipedia article title
(``BLOCS``; a title that resolves to no item is reported unresolved, never guessed). It asks for every member that carries an
ISO 3166-1 code (``P297``), through either direction Wikidata uses: the member's ``member of`` (``P463``) statement or the bloc's
``has part`` (``P527``) statement, with each statement's own start (``P580``) and end (``P582``) qualifiers at their stated
precision. A deprecated statement is not asked for. What it does NOT ask for is listed in every report (``NOT_ASKED_FOR``).

WHY WIKIDATA, AND WHAT IT IS NOT. It is the one source that answers all thirteen blocs in one shape, with a statement address
per date, so a reviewer can open exactly what a row came from. It is a SECONDARY source: a date there can be wrong, missing or a
year where the treaty gives a day. So every proposed row carries its statement address and the time it was read, and the
report says beside every bloc that a row is a lead for a reviewer, not a roster.

THE CONSENT AND THE TRANSPORT. It asks the network only with ``--online``. Before that check it prints the one host it would ask
(``query.wikidata.org``) and how requests would leave (``direct``, ``proxy`` or ``pool``, read from the app's safety settings);
``unknown`` or ``refused`` stops the run before anything is sent. Requests go through ``guarded_session``, the session the app
itself uses for this endpoint (``src/catalog/discover.py``): the protected-mode proxy, never a silent downgrade, the descriptive
Wikimedia user agent, and a host list that refuses any redirect off ``query.wikidata.org``. One second between reads. On an
encrypted install the settings read as ``unknown`` unless the passphrase is in the environment
(``read -rs OO_DB_PASSPHRASE && export OO_DB_PASSPHRASE``, never on the command line).

THE REPORT (``--out``, JSON, at most ``MAX_REPORT_BYTES`` so it can be sent back): per bloc the title asked, the item and label it
resolved to, the proposed rows and the refusals; then the counts. Exit 0 when the report is written, 2 refused, 1 the run failed.

    python scripts/bloc_roster_check.py --online --out bloc-roster-check.json
    python scripts/bloc_roster_check.py --online --only nato,brics --out bloc-roster-check.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
WDQS_HOST = "query.wikidata.org"

#: The report the operator sends back stays under this, whatever the answers hold.
MAX_REPORT_BYTES = 200_000
#: A single answer larger than this is refused rather than parsed (a bloc has at most a few hundred member statements).
MAX_ANSWER_BYTES = 5_000_000
#: Seconds between two reads of the endpoint.
PAUSE_S = 1.0

#: The blocs ``src/catalog/blocs.py`` holds empty, keyed as there, each with its English Wikipedia article title. The title is
#: how the bloc is FOUND, so no item id is typed from memory; the report shows the item and label it resolved to.
BLOCS: tuple[tuple[str, str], ...] = (
    ("brics", "BRICS"),
    ("g7", "Group of Seven"),
    ("g20", "G20"),
    ("nato", "NATO"),
    ("african-union", "African Union"),
    ("asean", "ASEAN"),
    ("mercosur", "Mercosur"),
    ("caricom", "Caribbean Community"),
    ("gcc", "Gulf Cooperation Council"),
    ("opec", "OPEC"),
    ("commonwealth", "Commonwealth of Nations"),
    ("francophonie", "Organisation internationale de la Francophonie"),
    ("european-union", "European Union"),
)

#: Wikidata time precision -> the date kept. Coarser than a year is not a date.
_PRECISION = {"14": 10, "13": 10, "12": 10, "11": 10, "10": 7, "9": 4}

NOT_ASKED_FOR = [
    "members with no ISO 3166-1 alpha-2 code (P297): former states, territories and organisations that are members",
    "suspensions: Wikidata has no common shape for them; the reviewer reads them from the organisation's own page",
    "deprecated statements",
    "observer, associate and partner status, unless Wikidata records it as P463 or P527 like a membership (the row then says "
    "only what the statement says: check it)",
]

QUERY_TEMPLATE = """\
SELECT ?bloc ?blocLabel ?member ?iso2 ?via ?start ?sp ?end ?ep WHERE {
  ?article schema:about ?bloc ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name "{title}"@en .
  OPTIONAL { ?bloc rdfs:label ?blocLabel . FILTER(LANG(?blocLabel) = "en") }
  OPTIONAL {
    { ?member p:P463 ?stmt . ?stmt ps:P463 ?bloc . BIND("P463" AS ?via) }
    UNION
    { ?bloc p:P527 ?stmt . ?stmt ps:P527 ?member . BIND("P527" AS ?via) }
    ?stmt wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank)
    ?member wdt:P297 ?iso2 .
    OPTIONAL { ?stmt pqv:P580 [ wikibase:timeValue ?start ; wikibase:timePrecision ?sp ] . }
    OPTIONAL { ?stmt pqv:P582 [ wikibase:timeValue ?end ; wikibase:timePrecision ?ep ] . }
  }
}
"""


def build_query(title: str) -> str:
    if '"' in title or "\\" in title or "\n" in title:
        raise ValueError("a bloc title is plain text")
    return QUERY_TEMPLATE.replace("{title}", title)


def query_url(query: str) -> str:
    return f"{WDQS_ENDPOINT}?{urllib.parse.urlencode({'query': query, 'format': 'json'})}"


def _val(binding: dict[str, Any], key: str) -> str:
    cell = binding.get(key)
    return str(cell.get("value", "")).strip() if isinstance(cell, dict) else ""


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if uri.startswith("http") else uri


def stated_date(value: str, precision: str) -> tuple[str | None, str | None]:
    """A WDQS time at its stated precision: ``("2023-04-04", None)``, ``("1949", None)``, or ``(None, reason)``. A year is kept as
    a year, never written as 1 January."""
    if not value:
        return None, None
    keep = _PRECISION.get(precision)
    if keep is None:
        return None, f"precision {precision or 'unstated'} is coarser than a year"
    day = value.split("T", 1)[0]
    if day.startswith(("+", "-")):
        if day.startswith("-"):
            return None, "a date before the common era"
        day = day[1:]
    if len(day) < keep:
        return None, "the time value is shorter than its precision"
    return day[:keep], None


def rows_from_answer(payload: dict[str, Any], *, bloc_key: str, fetched_at: str) -> dict[str, Any]:
    """One bloc's proposal from one WDQS answer: the item and label the title resolved to, and the proposed rows."""
    bindings = (payload.get("results") or {}).get("bindings") or []
    items = sorted({_qid(_val(b, "bloc")) for b in bindings if _val(b, "bloc")})
    out: dict[str, Any] = {"key": bloc_key, "resolved_items": items, "proposed": [], "refused": []}
    if not items:
        out["verdict"] = "unresolved"
        return out
    labels = sorted({_val(b, "blocLabel") for b in bindings if _val(b, "blocLabel")})
    out["resolved_labels"] = labels
    seen: set[tuple[str, ...]] = set()
    for b in bindings:
        iso2, member, via = _val(b, "iso2").lower(), _qid(_val(b, "member")), _val(b, "via")
        if not member:
            continue
        if len(iso2) != 2 or not iso2.isascii() or not iso2.isalpha():
            out["refused"].append({"member": member, "reason": "no two-letter ISO code"})
            continue
        joined, jwhy = stated_date(_val(b, "start"), _val(b, "sp"))
        left, lwhy = stated_date(_val(b, "end"), _val(b, "ep"))
        key = (iso2, via, joined or "", left or "", _qid(_val(b, "bloc")))
        if key in seen:
            continue
        seen.add(key)
        subject = member if via == "P463" else _qid(_val(b, "bloc"))
        row: dict[str, Any] = {
            "area": iso2,
            "member_item": member,
            "joined": joined,
            "left": left,
            "via": via,
            "source": f"https://www.wikidata.org/wiki/{subject}#{via}",
            "fetched_at": fetched_at,
        }
        notes = [w for w in (jwhy and f"start: {jwhy}", lwhy and f"end: {lwhy}") if w]
        if joined is None and not jwhy:
            notes.append("no start date stated")
        if notes:
            row["notes"] = notes
        out["proposed"].append(row)
    out["proposed"].sort(key=lambda r: (r["area"], r["joined"] or "", r["left"] or ""))
    out["verdict"] = "proposed" if out["proposed"] else "no_member_rows"
    if len(items) > 1:
        out["verdict"] = "ambiguous"  # one title, several items: the reviewer must pick, so nothing is proposed as one bloc's
    return out


def build_report(blocs: list[dict[str, Any]], *, transport: str, queries: dict[str, str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for b in blocs:
        counts[b["verdict"]] = counts.get(b["verdict"], 0) + 1
    report = {
        "schema": "oo-bloc-roster-check-1",
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": WDQS_ENDPOINT,
        "transport": transport,
        "query_template_sha256": hashlib.sha256(QUERY_TEMPLATE.encode("utf-8")).hexdigest(),
        "query_template": QUERY_TEMPLATE,
        "method": (
            "per bloc, one Wikidata Query Service read: the item behind its English Wikipedia title, then every member with an "
            "ISO 3166-1 code through P463 (member of) or P527 (has part), each statement's P580/P582 at its stated precision"
        ),
        "caveat": (
            "Every row is a LEAD for a reviewer, not a roster: Wikidata is a secondary source, and a date there can be wrong, "
            "missing, or a year where the treaty gives a day. Nothing enters src/catalog/blocs.py until a lane has checked the "
            "row against the organisation's own membership page; until then the bloc stays empty and says so."
        ),
        "not_asked_for": NOT_ASKED_FOR,
        "n_blocs": len(blocs),
        "verdicts": dict(sorted(counts.items())),
        "titles": queries,
        "blocs": blocs,
    }
    return fit(report)


def fit(report: dict[str, Any], limit: int = MAX_REPORT_BYTES) -> dict[str, Any]:
    """Keep the report within ``limit`` bytes: the template text goes first, then rows from the largest bloc, each cut counted."""
    def size() -> int:
        return len(json.dumps(report, ensure_ascii=False, indent=1).encode("utf-8"))

    report["rows_dropped_to_fit"] = {}
    if size() > limit:
        report["query_template"] = None  # its sha256 stays, and the template is in this script
    while size() > limit:
        biggest = max(report["blocs"], key=lambda b: len(b.get("proposed") or []), default=None)
        if not biggest or not biggest.get("proposed"):
            break
        biggest["proposed"].pop()
        report["rows_dropped_to_fit"][biggest["key"]] = report["rows_dropped_to_fit"].get(biggest["key"], 0) + 1
    return report


def check_bloc(key: str, title: str, get: Callable[[str], bytes]) -> dict[str, Any]:
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    base = {"key": key, "title": title, "fetched_at": fetched_at}
    try:
        body = get(query_url(build_query(title)))
    except Exception as exc:  # noqa: BLE001 - a refusal is this bloc's verdict, recorded by class, never by its text
        return {**base, "verdict": "refused", "error_class": type(exc).__name__, "proposed": [], "refused": []}
    if len(body) > MAX_ANSWER_BYTES:
        return {**base, "verdict": "answer_too_large", "proposed": [], "refused": []}
    try:
        payload = json.loads(body)
    except ValueError:
        return {**base, "verdict": "not_json", "proposed": [], "refused": []}
    return {**base, **rows_from_answer(payload, bloc_key=key, fetched_at=fetched_at)}


def _transport() -> str:
    """How the requests would leave, read from the app's safety settings before anything is sent: ``direct``, ``proxy``,
    ``pool``, ``refused`` or ``unknown`` (the settings could not be read). A token, never an address."""
    from src.safety.fetcher import transport_summary
    from src.safety.settings import load_settings

    try:
        kind = str(transport_summary(load_settings()).get("kind", "unknown"))
    except Exception:  # noqa: BLE001 - an unreadable settings store is "unknown", which refuses below
        return "unknown"
    return kind if kind in ("direct", "proxy", "pool", "refused") else "unknown"


def _getter() -> Callable[[str], bytes]:
    """The app's own session for this endpoint: protected-mode proxy, no silent downgrade, only ``query.wikidata.org``."""
    from src.ingest import DEFAULT_USER_AGENT
    from src.safety.fetcher import guarded_session

    session = guarded_session(user_agent=DEFAULT_USER_AGENT, allowed_hosts=(WDQS_HOST,))

    def get(url: str) -> bytes:
        if not url.startswith(WDQS_ENDPOINT + "?"):
            raise ValueError("only the Wikidata Query Service endpoint is asked")
        resp = session.get(url, timeout=120, headers={"Accept": "application/sparql-results+json"})
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        return resp.content

    return get


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--online", action="store_true", help="your consent for this run to ask query.wikidata.org")
    ap.add_argument("--out", type=Path, required=True, help="the JSON report to write")
    ap.add_argument("--only", default="", help="comma-separated bloc keys (default: all thirteen)")
    args = ap.parse_args(argv)

    only = {c.strip() for c in args.only.split(",") if c.strip()}
    blocs = [(k, t) for k, t in BLOCS if not only or k in only]
    unknown = sorted(only - {k for k, _ in BLOCS})
    if unknown:
        print(f"unknown bloc key(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    print(f"{len(blocs)} blocs; this run asks one host, {len(blocs)} times:")
    print(f"  {WDQS_HOST}")
    transport = _transport()
    print(f"transport: {transport} (from the app's safety settings in this data folder)")
    if transport in ("refused", "unknown"):
        print(f"refused: the transport is {transport}, so nothing would leave as your settings say. Nothing was sent.", file=sys.stderr)
        return 2
    if not args.online:
        print("refused: add --online to consent to these requests. Nothing was sent.", file=sys.stderr)
        return 2
    try:
        get = _getter()
    except Exception as exc:  # noqa: BLE001 - protected mode with no proxy, an unreadable settings file
        print(f"refused before any request: the session could not be built ({type(exc).__name__})", file=sys.stderr)
        return 2
    rows = []
    for n, (key, title) in enumerate(blocs, 1):
        if n > 1:
            time.sleep(PAUSE_S)
        row = check_bloc(key, title, get)
        print(f"[{n}/{len(blocs)}] {key}: {row['verdict']} ({len(row.get('proposed') or [])} rows)")
        rows.append(row)
    report = build_report(rows, transport=transport, queries=dict(blocs))
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes): {report['verdicts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
