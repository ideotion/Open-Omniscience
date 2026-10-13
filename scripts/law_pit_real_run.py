#!/usr/bin/env python3
"""
law_pit_real_run -- row G's real-source check: is a law's 2019 text findable by point-in-time search?

The gate's closing clause is «a law's 2019 text is findable by point-in-time search on the fixture
jurisdiction AND on one real source». The fixture half is `tests/test_law_evolution_surface.py`. This is
the real half (R125/R132: it runs in the cloud, on www.legislation.gov.uk, which the maintainer allows;
it joins no operator step). It uses the app's own paths end to end and nothing of its own:

  1. the Act is fetched twice through the ethical fetcher (robots, honest UA, politeness): the version
     the publisher serves for the asked-for 2019 day (`<official_url>/<day>/data.xml`) and the current
     one (`<official_url>/data.xml`);
  2. both go through `src.law.track.track_document` (the CLML adapter, the dating rule, the lane);
  3. a distinctive phrase that the 2019 text holds and the current text does not is picked from the two
     texts (or given with --phrase), and `src.law.pit_search.search` is asked for it "on" the 2019 day
     and "on" today.

The verdict is one word from a closed vocabulary, with its reason; there is no score:

  found                 the phrase is in force-and-held on the 2019 day (the 2019 capture, dated by the
                        source), and is NOT found on today's date
  not-found             both captures held, but the 2019 day did not find the 2019 words (the reason says
                        whether the source's date was read or the version was dated by observation)
  not-decisive          the 2019 and current texts are the same, or no phrase differs: this Act is the
                        wrong specimen for the check (try another with --title)
  fetch-refused         a capture was refused or empty (the refusal is kept verbatim, whether it is the
                        site's, the robots rules' or this environment's network policy)

It egresses to ONE host and says which before it asks. It refuses without --online, refuses while the
global kill switch is engaged, and writes only into a NEW, EMPTY scratch data directory (never a store
someone uses):

    OO_DATA_DIR=/tmp/oo-law-pit/state OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1 \\
        python scripts/law_pit_real_run.py --online --out /tmp/oo-law-pit/report.json

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_TITLE = "Data Protection Act 2018"
DEFAULT_DAY = "2019-06-01"
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
_PHRASE_WORDS = 5
#: The publisher's host, compared whole (never as a substring of a URL).
_HOSTS = {"legislation.gov.uk", "www.legislation.gov.uk"}


def capture_urls(official_url: str, day: str) -> tuple[str, str]:
    """(the version in force on ``day``, the current version) -- composed from the catalogue row's own
    ``official_url``, never typed here."""
    base = official_url.rstrip("/")
    return f"{base}/{day}/data.xml", f"{base}/data.xml"


def pick_phrase(old_text: str, new_text: str) -> str | None:
    """A run of words the OLD text holds and the NEW one does not: the first such run in reading order.
    None when the two read the same (then the Act cannot show the check)."""
    old = _WORD.findall(old_text.lower())
    new = " ".join(_WORD.findall(new_text.lower()))
    for i in range(len(old) - _PHRASE_WORDS + 1):
        run = old[i : i + _PHRASE_WORDS]
        if " ".join(run) not in new and sum(len(w) for w in run) >= 25:
            return " ".join(run)
    return None


def _capture(session, fetcher, doc, url: str) -> dict:
    from src.law.track import track_document

    doc.url = url
    out = track_document(session, fetcher, doc)
    session.refresh(doc)
    return {"url": url, "status": out.get("status"), "detail": out.get("detail"), "size": out.get("size")}


def run(session, fetcher, doc_row: dict, *, day: str = DEFAULT_DAY, phrase: str | None = None, today: str | None = None) -> dict:
    """Capture the two versions through the app's tracker and ask the app's search. ``session`` is the
    corpus session; the law lane must exist. Returns the report (JSON-able)."""
    from src.database.models import LawDocument, LawRevision
    from src.law.pit_search import search
    from src.law.versions import effective_versions

    today = today or datetime.now(UTC).date().isoformat()
    pit_url, current_url = capture_urls(doc_row["official_url"], day)
    doc = LawDocument(**{**doc_row, "url": pit_url})
    session.add(doc)
    session.commit()
    report: dict = {
        "act": doc_row["title"], "host": urlparse(pit_url).hostname, "asked_for_day": day, "today": today,
        "captures": [], "verdict": None, "why": None,
    }
    for url in (pit_url, current_url):
        cap = _capture(session, fetcher, doc, url)
        report["captures"].append(cap)
        if cap["status"] not in ("baseline", "changed", "reverted", "unchanged", "duplicate", "re-extracted"):
            report["verdict"] = "fetch-refused"
            report["why"] = f"{url}: {cap['status']}: {cap['detail']}"
            return report
    revs = session.query(LawRevision).filter_by(document_id=doc.id).order_by(LawRevision.id.asc()).all()
    report["versions"] = [
        {"version_id": v.revision_id, "valid_from": v.valid_from, "valid_to": v.valid_to, "dating": v.dating}
        for v in effective_versions(revs)
    ]
    if len(revs) < 2:
        report["verdict"] = "not-decisive"
        report["why"] = (
            "the 2019 version and the current one read the same, so one version is held: this Act shows nothing "
            "about point-in-time search"
        )
        return report
    old, new = revs[0], revs[-1]
    chosen = phrase or pick_phrase(old.full_text or "", new.full_text or "")
    if not chosen:
        report["verdict"] = "not-decisive"
        report["why"] = "no run of words in the 2019 text is missing from the current one"
        return report
    query = f'"{chosen}"'
    then = search(session, query, on=day)
    now = search(session, query, on=today)
    report["phrase"] = chosen
    report["search_on_2019_day"] = {"matched": then["matched"], "versions": [h["version_id"] for h in then["hits"]]}
    report["search_on_today"] = {"matched": now["matched"], "versions": [h["version_id"] for h in now["hits"]]}
    dated = [v["dating"] for v in report["versions"]]
    found_then = old.id in [h["version_id"] for h in then["hits"]]
    found_now = old.id in [h["version_id"] for h in now["hits"]]
    if found_then and not found_now:
        report["verdict"] = "found"
        report["why"] = (
            f"{chosen!r} is found in the version in force on {day} and not on {today}; "
            f"the versions' dating is {dated} (official = read from the publisher's own document)"
        )
    else:
        report["verdict"] = "not-found"
        report["why"] = (
            f"the words are in the older capture but the search did not place it on {day} "
            f"(found then: {found_then}, found today: {found_now}); versions' dating is {dated}"
            + ("; a version dated by observation cannot answer a past day" if "official" not in dated else "")
        )
    return report


def _catalogue_row(title: str) -> dict | None:
    from src.law.catalog import load_legal_catalog

    for d in load_legal_catalog().get("documents") or []:
        host = (urlparse(str((d or {}).get("url") or "")).hostname or "").lower()
        if host in _HOSTS and title.lower() in str(d.get("title") or "").lower():
            return {
                "jurisdiction": d.get("jurisdiction") or "uk", "title": d["title"], "url": d["url"],
                "official_url": d.get("official_url") or d["url"], "category": d.get("category") or "legislation",
                "consolidated": True, "language": d.get("language") or "en", "country": d.get("country"),
            }
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--online", action="store_true", help="say yes to contacting the host named in the output")
    ap.add_argument("--title", default=DEFAULT_TITLE, help="a catalogue title on legislation.gov.uk")
    ap.add_argument("--day", default=DEFAULT_DAY, help="the 2019 day to ask for, YYYY-MM-DD")
    ap.add_argument("--phrase", default=None, help="words to search for; default: picked from the two texts")
    ap.add_argument("--out", default=None, help="write the report JSON here")
    args = ap.parse_args(argv)

    import analytics45_seed as scratch

    why = scratch.refuse_unless_scratch()
    if why:
        sys.exit(why)
    row = _catalogue_row(args.title)
    if row is None:
        sys.exit(f"refusing: no entry on the publisher's host titled like {args.title!r} in configs/legal_sources.yml")
    host = urlparse(row["official_url"]).hostname
    if not args.online:
        sys.exit(f"refusing: this contacts {host} (two GETs of the Act's CLML, through the ethical fetcher); say --online to allow it")
    from src.ingest import EthicalFetcher, kill_switch_active

    if kill_switch_active():
        sys.exit("refusing: the global kill switch (airplane mode) is engaged")

    from src.database.session import SessionLocal, init_db
    from src.versioned.store import create_lane

    init_db()
    create_lane("law")
    fetcher = EthicalFetcher(timeout=45.0)
    with SessionLocal() as session:
        report = run(session, fetcher, row, day=args.day, phrase=args.phrase)
    text = json.dumps(report, indent=1, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if report["verdict"] == "found" else 1


if __name__ == "__main__":
    sys.exit(main())
