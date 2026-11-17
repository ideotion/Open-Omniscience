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
import re
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
#: Seconds between two reads of the endpoint, and the most one answer may take to arrive in total.
PAUSE_S = 1.0
READ_DEADLINE_S = 180.0

#: The blocs ``src/catalog/blocs.py`` holds empty, keyed as there, each with its English Wikipedia article title. The title is
#: how the bloc is FOUND, so no item id is typed from memory; the report shows the item and label it resolved to.
BLOCS: tuple[tuple[str, str], ...] = (
    ("brics", "BRICS"),
    ("g7", "G7"),
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
SELECT ?bloc ?blocLabel ?member ?iso2 ?via ?stmt ?start ?sp ?end ?ep WHERE {
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

_QID = re.compile(r"^Q[1-9]\d{0,11}$")
#: A statement's id as WDQS writes it (``Q33-0A1B...``); on the item's page it is the anchor ``Q33$0A1B...``.
_STMT = re.compile(r"^(Q[1-9]\d{0,11})-([0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})$")
_DATE_SHAPE = {10: re.compile(r"^\d{4}-\d{2}-\d{2}$"), 7: re.compile(r"^\d{4}-\d{2}$"), 4: re.compile(r"^\d{4}$")}
_VIAS = ("P463", "P527")
#: Labels and items kept per bloc, and the length any string from the answer is cut to.
MAX_LISTED = 5
MAX_TEXT = 200


def build_query(title: str) -> str:
    if any(c in title for c in '"\\\r\n'):
        raise ValueError("a bloc title is plain text")
    return QUERY_TEMPLATE.replace("{title}", title)


def query_url(query: str) -> str:
    return f"{WDQS_ENDPOINT}?{urllib.parse.urlencode({'query': query, 'format': 'json'})}"


def _val(binding: Any, key: str) -> str:
    cell = binding.get(key) if isinstance(binding, dict) else None
    value = cell.get("value", "") if isinstance(cell, dict) else ""
    return value.strip()[:MAX_TEXT] if isinstance(value, str) else ""


def _qid(uri: str) -> str | None:
    """``http://www.wikidata.org/entity/Q33`` -> ``Q33``; anything that is not an item id -> None."""
    tail = uri.rsplit("/", 1)[-1]
    return tail if _QID.match(tail) else None


def _statement_anchor(uri: str) -> str | None:
    """The statement's anchor on its item's page (``Q33$0A1B...``), or None when WDQS did not give a well-formed one."""
    m = _STMT.match(uri.rsplit("/", 1)[-1])
    return f"{m.group(1)}${m.group(2)}" if m else None


def stated_date(value: str, precision: str) -> tuple[str | None, str | None]:
    """A WDQS time at its stated precision: ``("2023-04-04", None)``, ``("1949", None)``, or ``(None, reason)``. A year is kept as
    a year, never written as 1 January; anything that does not read as a date is refused, never cut to length."""
    if not value:
        return None, None
    keep = _PRECISION.get(precision)
    if keep is None:
        return None, f"precision {precision or 'unstated'} is coarser than a year"
    day = value.split("T", 1)[0]
    if day.startswith("-"):
        return None, "a date before the common era"
    day = day.removeprefix("+")
    if not _DATE_SHAPE[keep].match(day[:keep]):
        return None, "the time value does not read as a date"
    return day[:keep], None


def rows_from_answer(payload: Any, *, bloc_key: str, fetched_at: str) -> dict[str, Any]:
    """One bloc's proposal from one WDQS answer: the item and label the title resolved to, and the proposed rows.
    An answer of the wrong shape is a verdict, never an exception."""
    results = payload.get("results") if isinstance(payload, dict) else None
    bindings = results.get("bindings") if isinstance(results, dict) else None
    if not isinstance(bindings, list):
        return {"key": bloc_key, "verdict": "bad_shape", "resolved_items": [], "proposed": [], "refused": {}}
    bindings = [b for b in bindings if isinstance(b, dict)]
    items = sorted({q for q in (_qid(_val(b, "bloc")) for b in bindings) if q})
    out: dict[str, Any] = {"key": bloc_key, "resolved_items": items[:MAX_LISTED], "proposed": [], "refused": {}}
    if not items:
        out["verdict"] = "unresolved"
        return out
    if len(items) > 1:
        # One title, several items: the reviewer must pick, so no row is proposed as this bloc's.
        out.update(verdict="ambiguous", n_items=len(items))
        return out
    bloc_item = items[0]
    out["resolved_labels"] = sorted({_val(b, "blocLabel") for b in bindings if _val(b, "blocLabel")})[:MAX_LISTED]

    def refuse(reason: str) -> None:
        out["refused"][reason] = out["refused"].get(reason, 0) + 1

    seen: set[str] = set()
    for b in bindings:
        if not _val(b, "member"):
            continue  # the title row, with no member statement joined to it
        member, via, iso2 = _qid(_val(b, "member")), _val(b, "via"), _val(b, "iso2").lower()
        if member is None:
            refuse("the member is not an item id")
            continue
        if via not in _VIAS:
            refuse("the statement is neither P463 nor P527")
            continue
        if len(iso2) != 2 or not iso2.isascii() or not iso2.isalpha():
            refuse("no two-letter ISO code")
            continue
        anchor = _statement_anchor(_val(b, "stmt"))
        joined, jwhy = stated_date(_val(b, "start"), _val(b, "sp"))
        left, lwhy = stated_date(_val(b, "end"), _val(b, "ep"))
        identity = anchor or f"{member}|{via}|{iso2}|{joined}|{left}|{jwhy}|{lwhy}"
        if identity in seen:
            continue  # one statement met twice through the joins
        seen.add(identity)
        subject = member if via == "P463" else bloc_item
        row: dict[str, Any] = {
            "area": iso2,
            "member_item": member,
            "joined": joined,
            "left": left,
            "via": via,
            "source": f"https://www.wikidata.org/wiki/{subject}#{anchor or via}",
            "fetched_at": fetched_at,
        }
        notes = [w for w in (jwhy and f"start: {jwhy}", lwhy and f"end: {lwhy}") if w]
        if joined is None and not jwhy:
            notes.append("no start date stated")
        if left is None and not lwhy:
            notes.append("no end date stated: a member that left may read as current")
        if anchor is None:
            notes.append("the statement id was not given: the link opens the property, not the statement")
        row["notes"] = notes
        out["proposed"].append(row)
    out["proposed"].sort(key=lambda r: (r["area"], r["joined"] or "", r["left"] or "", r["member_item"]))
    out["verdict"] = "proposed" if out["proposed"] else "no_member_rows"
    return out


def build_report(blocs: list[dict[str, Any]], *, transport: str, queries: dict[str, str], interrupted: bool = False) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for b in blocs:
        counts[b["verdict"]] = counts.get(b["verdict"], 0) + 1
    report = {
        "schema": "oo-bloc-roster-check-1",
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": WDQS_ENDPOINT,
        "transport": transport,
        "interrupted": interrupted,
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


def _size(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")) + 1  # the trailing newline the file gets


def fit(report: dict[str, Any], limit: int = MAX_REPORT_BYTES) -> dict[str, Any]:
    """Keep the report within ``limit`` bytes, in linear time. The template text goes first (its sha256 stays), then rows from
    the end of the largest blocs, each row measured once and every cut counted. Raises when even a report with no rows does not
    fit, so an oversized report is never written."""
    report["rows_dropped_to_fit"] = {}
    if _size(report) > limit:
        report["query_template"] = None
    excess = _size(report) - limit
    if excess > 0:
        # a row costs more inside the report than alone (its lines are indented there), so each bloc's rows are scaled to
        # what the bloc really adds, measured once per bloc
        cuts: list[tuple[int, int, dict[str, Any], float]] = []
        for b in report["blocs"]:
            rows = b["proposed"]
            if not rows:
                continue
            alone = [_size(r) for r in rows]
            b["proposed"] = []
            scale = (excess + limit - _size(report)) / sum(alone)
            b["proposed"] = rows
            cuts.extend((i, len(rows), b, alone[i] * scale) for i in range(len(rows)))
        cuts.sort(key=lambda t: (-t[0], -t[1]))
        drop: dict[str, int] = {}
        for _i, _n, b, cost in cuts:  # the deepest row first, so the cut levels the largest blocs down before a small one loses a row
            if excess <= 0:
                break
            drop[b["key"]] = drop.get(b["key"], 0) + 1
            excess -= cost
        for b in report["blocs"]:
            n = drop.get(b["key"], 0)
            if n:
                del b["proposed"][len(b["proposed"]) - n:]
        report["rows_dropped_to_fit"] = drop
    while _size(report) > limit:  # the per-row estimate fell short: drop one more row each pass from the largest
        biggest = max(report["blocs"], key=lambda b: len(b["proposed"]), default=None)
        if biggest is None or not biggest["proposed"]:
            raise ValueError("the report does not fit the send-back size even with no rows")
        biggest["proposed"].pop()
        report["rows_dropped_to_fit"][biggest["key"]] = report["rows_dropped_to_fit"].get(biggest["key"], 0) + 1
    return report


class AnswerTooLarge(Exception):
    """The answer passed MAX_ANSWER_BYTES, or the read passed its deadline, before it was complete."""


class HttpStatus(Exception):
    def __init__(self, status: int) -> None:
        super().__init__("HTTP status")
        self.status = status


def check_bloc(key: str, title: str, get: Callable[[str], bytes]) -> dict[str, Any]:
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    base = {"key": key, "title": title, "fetched_at": fetched_at, "proposed": [], "refused": {}}
    try:
        body = get(query_url(build_query(title)))
    except AnswerTooLarge:
        return {**base, "verdict": "answer_too_large"}
    except HttpStatus as exc:
        return {**base, "verdict": "refused", "error_class": "HttpStatus", "http_status": exc.status}
    except Exception as exc:  # noqa: BLE001 - a refusal is this bloc's verdict, recorded by class, never by its text
        return {**base, "verdict": "refused", "error_class": type(exc).__name__}
    if len(body) > MAX_ANSWER_BYTES:
        return {**base, "verdict": "answer_too_large"}
    try:
        payload = json.loads(body)
        return {**base, **rows_from_answer(payload, bloc_key=key, fetched_at=fetched_at)}
    except Exception as exc:  # noqa: BLE001 - not JSON, nested past the parser's depth, any shape surprise: this bloc only
        return {**base, "verdict": "bad_answer", "error_class": type(exc).__name__}


def _settings_once() -> Any:
    """The app's safety settings, read ONCE, so the transport printed is the transport used. None when unreadable."""
    from src.safety.settings import load_settings

    try:
        return load_settings()
    except Exception:  # noqa: BLE001 - an unreadable settings store reads as "unknown", which refuses
        return None


def _transport(settings: Any = None) -> str:
    """How the requests would leave: ``direct``, ``proxy``, ``pool``, ``refused`` or ``unknown``. A token, never an address."""
    from src.safety.fetcher import transport_summary

    if settings is None:
        return "unknown"
    try:
        kind = str(transport_summary(settings).get("kind", "unknown"))
    except Exception:  # noqa: BLE001
        return "unknown"
    return kind if kind in ("direct", "proxy", "pool", "refused") else "unknown"


def _getter(settings: Any) -> Callable[[str], bytes]:
    """The app's own session for this endpoint, built from the SAME settings the transport was read from: protected-mode proxy,
    no silent downgrade, only ``query.wikidata.org``. The answer is streamed: refused past MAX_ANSWER_BYTES (decoded) or past
    READ_DEADLINE_S in total, never held whole first."""
    from src.ingest import DEFAULT_USER_AGENT
    from src.safety.fetcher import _session_for

    session = _session_for(settings, user_agent=DEFAULT_USER_AGENT, allowed_hosts=(WDQS_HOST,))

    def get(url: str) -> bytes:
        if not url.startswith(WDQS_ENDPOINT + "?"):
            raise ValueError("only the Wikidata Query Service endpoint is asked")
        resp = session.get(url, stream=True, timeout=(10, 30), headers={"Accept": "application/sparql-results+json"})
        try:
            if resp.status_code != 200:
                raise HttpStatus(int(resp.status_code))
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_ANSWER_BYTES:
                raise AnswerTooLarge()
            deadline = time.monotonic() + READ_DEADLINE_S
            chunks, total = [], 0
            for chunk in resp.iter_content(65536):
                total += len(chunk)
                if total > MAX_ANSWER_BYTES or time.monotonic() > deadline:
                    raise AnswerTooLarge()
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            resp.close()

    return get


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--online", action="store_true",
                    help="your consent for this run to ask query.wikidata.org (the app's airplane mode lives in the app and "
                         "cannot be seen from here, so this flag is the only gate)")
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
    settings = _settings_once()
    transport = _transport(settings)
    print(f"transport: {transport} (from the app's safety settings in this data folder)")
    if transport in ("refused", "unknown"):
        print(f"refused: the transport is {transport}, so nothing would leave as your settings say. Nothing was sent.", file=sys.stderr)
        return 2
    if not args.online:
        print("refused: add --online to consent to these requests. Nothing was sent.", file=sys.stderr)
        return 2
    try:
        get = _getter(settings)
    except Exception as exc:  # noqa: BLE001 - protected mode with no proxy, an unreadable settings file
        print(f"refused before any request: the session could not be built ({type(exc).__name__})", file=sys.stderr)
        return 2
    rows: list[dict[str, Any]] = []
    interrupted = False
    try:
        for n, (key, title) in enumerate(blocs, 1):
            if n > 1:
                time.sleep(PAUSE_S)
            row = check_bloc(key, title, get)
            print(f"[{n}/{len(blocs)}] {key}: {row['verdict']} ({len(row.get('proposed') or [])} rows)")
            rows.append(row)
    except KeyboardInterrupt:
        interrupted = True  # the blocs already read are still written
        print("interrupted: writing the blocs read so far", file=sys.stderr)
    try:
        report = build_report(rows, transport=transport, queries=dict(blocs), interrupted=interrupted)
    except ValueError:
        print("refused: the report would not fit the 200 KB send-back size. Nothing was written.", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes): {report['verdicts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
