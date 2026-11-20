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
  * If the transport is ``direct`` and nothing chose it (no persisted safety settings in this data folder, no
    ``OO_FETCH_MODE``; a proxy variable alone does not count, since direct ignores it), the default would be clearnet,
    SILENTLY; on an install whose operator chose Tor that is a deanonymisation rather than a default. So it refuses unless
    you also pass ``--clearnet``.

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
import math
import os
import sys
import tempfile
import threading
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


def _direct_chosen() -> bool:
    """Did the operator CHOOSE the direct transport: persisted safety settings in this data folder, or ``OO_FETCH_MODE`` in
    the environment? A proxy variable alone does not count: with protected mode off it is not used, and a user who set it
    most likely meant to go through it. An unreadable store reads as not chosen, which refuses without --clearnet."""
    if os.getenv("OO_FETCH_MODE") is not None:
        return True
    try:
        from src.safety import settings as safety

        return safety._read_raw() is not None  # read-only; a missing or locked store reads as absent
    except Exception:  # noqa: BLE001
        return False


def _getter(settings: Any) -> Callable[[str], bytes]:
    """The app's own session for this endpoint, built from the SAME settings the transport was read from: protected-mode
    proxy, kill switch, no silent downgrade, only ``query.wikidata.org``. Streamed against a byte cap and a deadline."""
    from src.ingest import DEFAULT_USER_AGENT
    from src.safety.fetcher import _session_for

    session = _session_for(settings, user_agent=DEFAULT_USER_AGENT, allowed_hosts=(WDQS_HOST,))

    def get(url: str) -> bytes:
        if not url.startswith(WDQS_ENDPOINT + "?"):
            raise ValueError("only the Wikidata Query Service endpoint is asked")
        deadline = time.monotonic() + READ_DEADLINE_S
        resp = session.get(url, stream=True, timeout=(10, 30), headers={"Accept": "application/sparql-results+json"})
        # The deadline is for the whole read, so a server that trickles a byte under every socket timeout cannot hold the
        # run: a watchdog closes the response when the time is up, and the blocked read ends there.
        # The watchdog records that IT cut the read: on Windows a timer can fire a clock tick before time.monotonic()
        # reaches the deadline (row 204), so asking the clock afterwards misread the cut as a dropped connection.
        cut = threading.Event()

        def _cut() -> None:
            cut.set()
            resp.close()

        watchdog = threading.Timer(max(0.0, deadline - time.monotonic()), _cut)
        watchdog.daemon = True
        watchdog.start()
        try:
            if resp.status_code != 200:
                raise HttpStatus(int(resp.status_code))
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_ANSWER_BYTES:
                raise AnswerTooLarge()
            chunks, total = [], 0
            try:
                for chunk in resp.iter_content(65536):
                    total += len(chunk)
                    if total > MAX_ANSWER_BYTES or cut.is_set() or time.monotonic() > deadline:
                        raise AnswerTooLarge()
                    chunks.append(chunk)
            except AnswerTooLarge:
                raise
            except Exception:
                if cut.is_set() or time.monotonic() >= deadline:
                    raise AnswerTooLarge() from None  # the watchdog closed it
                raise
            if cut.is_set() or time.monotonic() > deadline:
                raise AnswerTooLarge()  # closed under the loop's feet, which can read as a short, clean end
            return b"".join(chunks)
        finally:
            watchdog.cancel()
            resp.close()

    return get


MAX_NAME = 200


def _usable(c: Any) -> str | None:
    """Why a parsed city cannot be written, or None. A row the app's loader would mis-read, or that YAML cannot carry back,
    is skipped by itself: one bad row never costs the run, and never reaches the file."""
    name = c.name
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
        return "name"
    try:
        name.encode("utf-8")  # a lone surrogate is valid JSON and writes a YAML file the loader cannot read back
    except UnicodeEncodeError:
        return "name"
    if not (math.isfinite(c.lat) and math.isfinite(c.lon) and -90 <= c.lat <= 90 and -180 <= c.lon <= 180):
        return "coordinates"
    if c.country is not None and not (isinstance(c.country, str) and len(c.country) == 2 and c.country.isascii()
                                      and c.country.isalpha()):
        return "country"
    if c.population is not None and not (isinstance(c.population, int) and 0 <= c.population < 10**11):
        return "population"
    return None


def cities_from_answer(body: bytes) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Parse the answer into the rows the file holds, one per (name, country), the most populous kept, and the count of rows
    skipped by reason. Raises ValueError on an answer that is not the SPARQL JSON shape, so a page of HTML or a truncated body
    never becomes an empty gazetteer."""
    from src.catalog.cities import parse_cities_sparql

    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("the answer is not a JSON object")
    results = payload.get("results")
    if not isinstance(results, dict) or not isinstance(results.get("bindings"), list):
        raise ValueError("the answer has no results.bindings list")
    skipped: dict[str, int] = {}
    best: dict[tuple[str, str | None], Any] = {}
    for b in results["bindings"]:
        if not isinstance(b, dict):
            skipped["shape"] = skipped.get("shape", 0) + 1
            continue
        try:
            parsed = parse_cities_sparql({"results": {"bindings": [b]}})  # one row at a time: a bad row is that row's loss
        except Exception:  # noqa: BLE001 - a non-numeric coordinate, an overflowing population, a non-text label
            skipped["unreadable"] = skipped.get("unreadable", 0) + 1
            continue
        for c in parsed:
            why = _usable(c)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            k = (c.name.lower(), c.country)
            if k not in best or (c.population or 0) > (best[k].population or 0):
                best[k] = c
    return [c.to_dict() for c in best.values()], skipped


def write_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write to a temporary file beside ``path``, read it back with the app's own loader, then swap it in. A file the app
    could not load never replaces the one it has."""
    import yaml

    from src.catalog.cities import _load_file

    text = "# Generated by scripts/build_city_gazetteer.py from Wikidata (CC0).\n\n" + yaml.safe_dump(
        {"cities": rows}, allow_unicode=True, sort_keys=False, width=4096
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cities-", suffix=".yml.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o644 & ~umask)  # mkstemp makes 0600; the file it replaces was an ordinary one
        if len(_load_file(Path(tmp))) != len(rows):
            raise ValueError("the written file does not read back whole")
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
    if transport == "direct" and not _direct_chosen() and not args.clearnet:
        print("refused: nothing in this data folder or your environment chose the direct transport, so the request would "
              "go out on clearnet by default. If you use Tor or a proxy, set OO_FETCH_MODE=protected and OO_HTTP_PROXY "
              "(or run this from the data folder that holds your settings); if clearnet is what you want, say so with "
              "--clearnet. Nothing was sent.", file=sys.stderr)
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
        rows, skipped = cities_from_answer(body)
    except Exception as exc:  # noqa: BLE001 - a page that is not the SPARQL JSON shape
        print(f"failed: the answer could not be read ({type(exc).__name__}). Nothing was written.", file=sys.stderr)
        return 1
    print(f"parsed {len(rows)} cities; rows skipped by reason: {skipped or 'none'}.", file=sys.stderr)
    if not rows:
        print("failed: the answer held no city, so the existing file was left as it is.", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0
    try:
        write_atomic(args.out, rows)
    except Exception as exc:  # noqa: BLE001 - a folder named as --out, a full disk, a file that did not read back
        print(f"failed: the file could not be written ({type(exc).__name__}). The existing file was left as it is.",
              file=sys.stderr)
        return 1
    print(f"wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
