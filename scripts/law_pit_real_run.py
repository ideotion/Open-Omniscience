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

  found                 the phrase is placed on the 2019 day (the 2019 capture, dated by the source), and
                        a search "on" today finds it nowhere
  not-found             both captures held, but the 2019 day did not find the 2019 words (the reason says
                        whether the source's date was read or the version was dated by observation)
  not-decisive          the 2019 and current texts are the same, no phrase differs, or the phrase given
                        is also in the current text: this Act or phrase cannot show the check (try
                        another with --title or --phrase)
  fetch-refused         a capture was refused or empty (the refusal is kept verbatim, whether it is the
                        site's, the robots rules' or this environment's network policy)

It asks ONE host, www.legislation.gov.uk over https, and says so before it asks: the URLs it builds are checked
before any request, every request the fetcher makes (the page, robots.txt, each redirect hop) is checked as a whole
URL before it goes out, and an answer whose final URL is anywhere else is refused. It refuses
without --online (the operator's consent for this run; the app's own airplane state lives in the app's
process and is not visible from here, so run it with the app stopped), and writes only into a NEW, EMPTY
scratch data directory (never a store someone uses):

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
# The search index's own word rule (FTS5 unicode61): letters and digits, everything else separates.
# A phrase is chosen and checked with it, so "data-protection" and "data protection" are the same words here
# exactly as they are to the index, and a number inside a phrase stays inside it.
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_PHRASE_WORDS = 5
#: The ONE host this script may ask, compared as the whole network location (never as a substring).
HOST = "www.legislation.gov.uk"


def allowed_url(url: str) -> bool:
    """True only for ``https://www.legislation.gov.uk/...``: https, exactly that network location (so no port, no
    userinfo, no apex or lookalike host), and no backslash anywhere (a browser reads ``https://evil.test\\@host``
    as host ``evil.test`` where a lenient parser reads ``host``)."""
    if not isinstance(url, str) or "\\" in url or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme == "https" and p.netloc == HOST and p.username is None and p.password is None


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


def _in_text(phrase: str, text: str) -> bool:
    """Is ``phrase`` a run of whole words of ``text``, by the index's own word rule?"""
    return " ".join(_WORD.findall(phrase.lower())) in " ".join(_WORD.findall(text.lower()))


def _capture(session, fetcher, doc, url: str) -> dict:
    from src.law.track import track_document

    doc.url = url
    out = track_document(session, fetcher, doc)
    session.refresh(doc)
    return {"url": url, "status": out.get("status"), "detail": out.get("detail"), "size": out.get("size")}


def run(
    session, fetcher, doc_row: dict, *, day: str = DEFAULT_DAY, phrase: str | None = None, today: str | None = None,
    url_ok=allowed_url,
) -> dict:
    """Capture the two versions through the app's tracker and ask the app's search. ``session`` is the
    corpus session; the law lane must exist. Returns the report (JSON-able)."""
    from src.database.models import LawDocument, LawRevision
    from src.law.pit_search import search
    from src.law.versions import effective_versions

    today = today or datetime.now(UTC).date().isoformat()
    pit_url, current_url = capture_urls(doc_row["official_url"], day)
    report: dict = {
        "act": doc_row["title"], "host": urlparse(pit_url).hostname, "asked_for_day": day, "today": today,
        "captures": [], "verdict": None, "why": None,
    }
    for url in (pit_url, current_url):  # the URLs actually fetched, checked before anything is written or asked
        if not url_ok(url):
            report["verdict"] = "fetch-refused"
            report["why"] = f"refused before any request: {url!r} is not an https URL on {HOST}"
            return report
    doc = LawDocument(**{**doc_row, "url": pit_url})
    session.add(doc)
    session.commit()
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
    if _in_text(chosen, new.full_text or "") or not _in_text(chosen, old.full_text or ""):
        report["verdict"] = "not-decisive"
        report["phrase"] = chosen
        report["why"] = "the phrase is in the current text too, or not in the 2019 text, so it cannot tell the two days apart"
        return report
    query = f'"{chosen}"'
    then = search(session, query, on=day)
    now = search(session, query, on=today)
    report["phrase"] = chosen
    report["search_on_2019_day"] = {"matched": then["matched"], "versions": [h["version_id"] for h in then["hits"]]}
    report["search_on_today"] = {"matched": now["matched"], "versions": [h["version_id"] for h in now["hits"]]}
    dated = [v["dating"] for v in report["versions"]]
    found_then = old.id in [h["version_id"] for h in then["hits"]]
    found_now = now["matched"] > 0  # ANY version placed on today that holds the words, not only the old one
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


def make_fetcher(timeout: float = 45.0):
    """The app's ethical fetcher, held to :data:`HOST` on EVERY request: the session's ``get`` refuses any URL
    that is not an allowed one before it goes out (page, robots.txt, every redirect hop), the redirect path's
    ``_guard_target`` refuses another host's name, and a result whose final URL is not allowed is refused after."""
    from src.ingest import BlockedTarget, EthicalFetcher, FetchError

    class _Pinned(EthicalFetcher):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            real_get = self.session.get

            def _get(url, *a, **kw):
                # EVERY request (the page, robots.txt, each redirect hop) passes here, and the WHOLE URL is judged:
                # the hop guard below sees only a hostname, and a parser differential (a backslash form such as
                # ``https://evil.test\\@www.legislation.gov.uk/x``) reads as the right host there and as another
                # to the library that connects.
                if not allowed_url(url):
                    raise BlockedTarget(f"refused: {url!r} is not an https URL on {HOST}")
                return real_get(url, *a, **kw)

            self.session.get = _get

        def _guard_target(self, host):  # called for the request and for every redirect target
            if host != HOST:
                raise BlockedTarget(f"refused: {host!r} is not {HOST}")
            super()._guard_target(host)

        def fetch(self, url, *args, **kwargs):
            result = super().fetch(url, *args, **kwargs)
            if not allowed_url(getattr(result, "final_url", "") or ""):
                raise FetchError(f"refused: the answer came from {getattr(result, 'final_url', None)!r}, not {HOST}")
            return result

    return _Pinned(timeout=timeout)


def _catalogue_row(title: str) -> dict | None:
    from src.law.catalog import load_legal_catalog

    for d in load_legal_catalog().get("documents") or []:
        if (
            allowed_url(str((d or {}).get("url") or ""))
            and allowed_url(str(d.get("official_url") or d.get("url") or ""))
            and title.lower() in str(d.get("title") or "").lower()
        ):
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
    host = HOST
    if not args.online:
        sys.exit(f"refusing: this contacts {host} (two GETs of the Act's CLML, through the ethical fetcher); say --online to allow it")
    fetcher = make_fetcher()  # before any write: nothing is created if this cannot be built

    from src.database.session import SessionLocal, init_db
    from src.versioned.store import create_lane

    init_db()
    create_lane("law")
    with SessionLocal() as session:
        report = run(session, fetcher, row, day=args.day, phrase=args.phrase)
    text = json.dumps(report, indent=1, default=str)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if report["verdict"] == "found" else 1


if __name__ == "__main__":
    sys.exit(main())
