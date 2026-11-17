#!/usr/bin/env python3
"""Build the city coordinate gazetteer (configs/cities.yml) from Wikidata, on your transport, with your consent.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IT ASKS. ONE request to the Wikidata Query Service (``query.wikidata.org``, CC0) for cities with coordinates (P625),
country (P17 -> ISO P297) and population (P1082) above a threshold. It writes ``configs/cities.yml``, which the Map prefers
over the shipped sample. Pure parsing lives in ``src/catalog/cities.py`` (unit-tested).

THE CONSENT AND THE TRANSPORT (row 132; the same rules as ``scripts/build_place_gazetteer.py``). Before anything is sent it
prints the one host it would ask and how the request would leave (``direct``, ``proxy`` or ``pool``), read from the app's
safety settings in this data folder. Then:

  * ``refused`` (protected mode with no usable proxy) or ``unknown`` (settings unreadable, for example an encrypted store
    without ``OO_DB_PASSPHRASE``) stops the run: nothing is sent.
  * Without ``--online`` nothing is sent. The flag IS your consent to the request.
  * If neither this data folder nor your environment names a transport (no persisted safety settings, no ``OO_FETCH_MODE``,
    ``OO_HTTP_PROXY`` or ``OO_HTTP_PROXIES``), the default would be clearnet, SILENTLY; on an install whose operator chose
    Tor that is a deanonymisation rather than a default. So it refuses unless you also pass ``--clearnet``.

The request goes through the app's own guarded session, built from the SAME settings the transport was read from: the
protected-mode proxy (never a silent downgrade), the kill switch, and a host list that refuses any redirect off
``query.wikidata.org``. This script is its own process: it checks its own kill switch, which only this process can engage,
and cannot see the airplane state of a running app; the flag is your consent. The answer is streamed against a byte cap
and a deadline. A run that fails, or that parses no city, writes nothing, so an existing ``configs/cities.yml`` is never
replaced by a broken or empty one; a successful run replaces it atomically.

On an encrypted install, give the passphrase through the environment, never on the command line:

    read -rs OO_DB_PASSPHRASE && export OO_DB_PASSPHRASE
    python scripts/build_city_gazetteer.py --online                     # >= 100,000 population
    python scripts/build_city_gazetteer.py --online --min-pop 50000 --dry-run
    unset OO_DB_PASSPHRASE

Exit 0 when the file is written (or the dry run parsed), 2 refused before or by the request, 1 the run failed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WDQS_HOST = "query.wikidata.org"
WDQS_ENDPOINT = f"https://{WDQS_HOST}/sparql"
_OUT = Path(__file__).resolve().parents[1] / "configs" / "cities.yml"
MAX_ANSWER_BYTES = 64_000_000  # about 15,000 cities at 50,000 people read ~5 MB; a far larger answer is not a city list
READ_DEADLINE_S = 360.0  # the whole read, not one socket wait; WDQS stops its own queries after 60 s


class AnswerTooLarge(Exception):
    """The answer passed MAX_ANSWER_BYTES, or the read passed READ_DEADLINE_S, before it was complete."""


class HttpStatus(Exception):
    def __init__(self, status: int) -> None:
        super().__init__("HTTP status")
        self.status = status


def build_query(min_pop: int) -> str:
    # Human settlements (city Q515 and its subclasses) with coordinates, country and population.
    return f"""
SELECT ?cityLabel ?coord ?cc ?population WHERE {{
  ?city wdt:P31/wdt:P279* wd:Q515 ;
        wdt:P625 ?coord ;
        wdt:P1082 ?population .
  FILTER(?population >= {int(min_pop)})
  OPTIONAL {{ ?city wdt:P17 ?country . ?country wdt:P297 ?cc . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
"""


def query_url(min_pop: int) -> str:
    return WDQS_ENDPOINT + "?" + urlencode({"query": build_query(min_pop), "format": "json"})


def _settings_once() -> Any:
    """The app's safety settings, read ONCE, so the transport printed is the transport used. None when unreadable."""
    from src.safety.settings import load_settings

    try:
        return load_settings()
    except Exception:  # noqa: BLE001 - an unreadable settings store reads as "unknown", which refuses
        return None


def _transport(settings: Any = None) -> str:
    """How the request would leave: ``direct``, ``proxy``, ``pool``, ``refused`` or ``unknown``. A token, never an address."""
    from src.safety.fetcher import transport_summary

    if settings is None:
        return "unknown"
    try:
        kind = str(transport_summary(settings).get("kind", "unknown"))
    except Exception:  # noqa: BLE001
        return "unknown"
    return kind if kind in ("direct", "proxy", "pool", "refused") else "unknown"


def _transport_named() -> bool:
    """Did the operator NAME a transport (persisted safety settings in this data folder, or the environment)? The same
    reading ``build_place_gazetteer.py`` makes; an unreadable store reads as not named, which refuses without --clearnet."""
    try:
        from src.entities.gazetteer_build import transport_state

        return bool(transport_state()["explicit"])
    except Exception:  # noqa: BLE001
        return any(os.getenv(k) is not None for k in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"))


def _getter(settings: Any) -> Callable[[str], bytes]:
    """The app's own session for this endpoint, built from the SAME settings the transport was read from: protected-mode
    proxy, kill switch, no silent downgrade, only ``query.wikidata.org``. Streamed against a byte cap and a deadline."""
    from src.ingest import DEFAULT_USER_AGENT
    from src.safety.fetcher import _session_for

    session = _session_for(settings, user_agent=DEFAULT_USER_AGENT, allowed_hosts=(WDQS_HOST,))

    def get(url: str) -> bytes:
        if not url.startswith(WDQS_ENDPOINT + "?"):
            raise ValueError("only the Wikidata Query Service endpoint is asked")
        resp = session.get(url, stream=True, timeout=(10, 90), headers={"Accept": "application/sparql-results+json"})
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


def cities_from_answer(body: bytes) -> list[dict[str, Any]]:
    """Parse the answer into the rows the file holds, one per (name, country), the most populous kept. Raises ValueError on
    an answer that is not the SPARQL JSON shape, so a page of HTML or a truncated body never becomes an empty gazetteer."""
    from src.catalog.cities import parse_cities_sparql

    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("the answer is not a JSON object")
    results = payload.get("results")
    if not isinstance(results, dict) or not isinstance(results.get("bindings"), list):
        raise ValueError("the answer has no results.bindings list")
    results["bindings"] = [b for b in results["bindings"] if isinstance(b, dict)]
    best: dict[tuple[str, str | None], Any] = {}
    for c in parse_cities_sparql(payload):
        k = (c.name.lower(), c.country)
        if k not in best or (c.population or 0) > (best[k].population or 0):
            best[k] = c
    return [c.to_dict() for c in best.values()]


def write_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    import yaml

    text = "# Generated by scripts/build_city_gazetteer.py from Wikidata (CC0).\n\n" + yaml.safe_dump(
        {"cities": rows}, allow_unicode=True, sort_keys=False, width=4096
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cities-", suffix=".yml.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    ap.add_argument("--online", action="store_true",
                    help="your consent for this run to ask query.wikidata.org once")
    ap.add_argument("--clearnet", action="store_true",
                    help="with --online: accept the clearnet transport when this data folder and your environment name "
                         "none (OO_FETCH_MODE / OO_HTTP_PROXY, or persisted safety settings)")
    ap.add_argument("--min-pop", type=int, default=100000, help="minimum population (default 100000)")
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument("--dry-run", action="store_true", help="ask and parse, write nothing")
    args = ap.parse_args(argv)
    if args.min_pop < 1:
        print("refused: --min-pop must be 1 or more", file=sys.stderr)
        return 2

    print("this run asks one host, once:")
    print(f"  {WDQS_HOST}")
    settings = _settings_once()
    transport = _transport(settings)
    print(f"transport: {transport} (from the app's safety settings in this data folder)")
    if transport in ("refused", "unknown"):
        print(f"refused: the transport is {transport}, so nothing would leave as your settings say. Nothing was sent.",
              file=sys.stderr)
        return 2
    if not args.online:
        print("refused: add --online to consent to this request. Nothing was sent.", file=sys.stderr)
        return 2
    if not _transport_named() and not args.clearnet:
        print("refused: this data folder and your environment name no transport, so the request would go out on clearnet "
              "by default. If you use Tor or a proxy, set OO_FETCH_MODE=protected and OO_HTTP_PROXY (or run this from the "
              "data folder that holds your settings); if clearnet is what you want, say so with --clearnet. Nothing was "
              "sent.", file=sys.stderr)
        return 2
    try:
        get = _getter(settings)
    except Exception as exc:  # noqa: BLE001 - protected mode with no proxy, an unreadable settings file
        print(f"refused before any request: the session could not be built ({type(exc).__name__})", file=sys.stderr)
        return 2

    print(f"asking Wikidata for cities of {args.min_pop} people or more...", file=sys.stderr)
    try:
        body = get(query_url(args.min_pop))
    except HttpStatus as exc:
        print(f"refused: the server answered HTTP {exc.status}. Nothing was written.", file=sys.stderr)
        return 2
    except AnswerTooLarge:
        print("failed: the answer passed the size cap or the read deadline. Nothing was written.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted. Nothing was written.", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - airplane mode, a refused transport or redirect, a dropped connection
        print(f"refused: the request did not complete ({type(exc).__name__}). Nothing was written.", file=sys.stderr)
        return 2
    try:
        rows = cities_from_answer(body)
    except Exception as exc:  # noqa: BLE001 - a page that is not the SPARQL JSON shape
        print(f"failed: the answer could not be read ({type(exc).__name__}). Nothing was written.", file=sys.stderr)
        return 1
    print(f"parsed {len(rows)} cities.", file=sys.stderr)
    if not rows:
        print("failed: the answer held no city, so the existing file was left as it is.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0
    write_atomic(args.out, rows)
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
