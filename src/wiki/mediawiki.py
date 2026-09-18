"""
MediaWiki API request builders + response parsers (pure, network-free).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

We use the official MediaWiki Action API (revisions / recentchanges / compare),
not page scraping: it is the efficient, change-oriented, ToS-friendly path. This
module only *builds* request params and *parses* JSON responses, so it is fully
unit-tested with fixtures; the live HTTP call lives in the client/scheduler.

Editions are per-language: ``api_endpoint("en")`` -> the English Wikipedia API.
"""

from __future__ import annotations

from datetime import datetime

from bs4 import BeautifulSoup
from dateutil import parser as date_parser


def api_endpoint(wiki: str) -> str:
    """API endpoint for a language edition code (e.g. 'en' -> en.wikipedia.org)."""
    code = (wiki or "en").strip().lower()
    return f"https://{code}.wikipedia.org/w/api.php"


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return date_parser.parse(str(value))
    except (ValueError, TypeError, OverflowError):
        return None


def build_revisions_params(title: str, *, limit: int = 20, older_than: int | None = None) -> dict:
    """Params for fetching a page's recent revisions (newest first)."""
    params = {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvprop": "ids|timestamp|user|comment|flags|size|tags",
        "rvlimit": limit,
        "rvdir": "older",
        "format": "json",
        "formatversion": 2,
    }
    if older_than:
        params["rvstartid"] = older_than
    return params


def parse_revisions(payload: dict) -> list[dict]:
    """Parse an action=query&prop=revisions response (formatversion=2)."""
    pages = (payload or {}).get("query", {}).get("pages", [])
    out: list[dict] = []
    for pg in pages:
        pageid, title = pg.get("pageid"), pg.get("title")
        prev_size = None
        # revisions come newest-first; delta is vs the older (next) revision, but
        # we expose raw size and let the caller compute deltas against parents.
        for r in pg.get("revisions", []):
            out.append(
                {
                    "revid": r.get("revid"),
                    "parent_revid": r.get("parentid"),
                    "timestamp": _parse_ts(r.get("timestamp")),
                    "editor": r.get("user"),
                    "editor_anon": bool(r.get("anon", False)),
                    "comment": r.get("comment"),
                    "size": r.get("size"),
                    "minor": bool(r.get("minor", False)),
                    "bot": bool(r.get("bot", False)),
                    "tags": list(r.get("tags", [])),
                    "pageid": pageid,
                    "title": title,
                }
            )
        _ = prev_size
    return out


def build_recentchanges_params(
    *, namespace: int = 0, limit: int = 50, types: str = "edit|new"
) -> dict:
    """Params for the recentchanges feed of a wiki (article namespace by default)."""
    return {
        "action": "query",
        "list": "recentchanges",
        "rcnamespace": namespace,
        "rcprop": "ids|sizes|flags|user|userid|comment|timestamp|tags|title",
        "rctype": types,
        "rclimit": limit,
        "format": "json",
        "formatversion": 2,
    }


def parse_recentchanges(payload: dict) -> list[dict]:
    """Parse a list=recentchanges response (formatversion=2)."""
    rc = (payload or {}).get("query", {}).get("recentchanges", [])
    out: list[dict] = []
    for c in rc:
        old, new = c.get("oldlen"), c.get("newlen")
        delta = (new - old) if (isinstance(old, int) and isinstance(new, int)) else None
        out.append(
            {
                "revid": c.get("revid"),
                "parent_revid": c.get("old_revid"),
                # THE PAGE ID WAS ALWAYS IN THE RESPONSE; THIS PARSER DROPPED IT.
                # ``rcprop`` above already asks for ``ids``, and ``revid`` /
                # ``old_revid`` — kept two lines up — come from that SAME prop, so a
                # response carrying them carries ``pageid`` too. That is verifiable
                # here, in this file, without reaching the API: the request asks for
                # the group and the parser keeps two of its three members.
                #
                # It matters beyond tidiness. Q715 keys the wiki lane on
                # ``(wiki, pageid)`` because a page MOVE changes the title, and
                # src/versioned/adapters/wiki.py recorded that it could not build
                # that identity from a change "without a second request per change"
                # — a conclusion drawn from this parser's output rather than from the
                # API's. Carrying the field makes the ruled identity free.
                "pageid": c.get("pageid"),
                "title": c.get("title"),
                "timestamp": _parse_ts(c.get("timestamp")),
                "editor": c.get("user"),
                "editor_anon": bool(c.get("anon", False)),
                "bot": bool(c.get("bot", False)),
                "minor": bool(c.get("minor", False)),
                "comment": c.get("comment"),
                "size": new,
                "delta_bytes": delta,
                "tags": list(c.get("tags", [])),
            }
        )
    return out


def build_current_text_params(title: str) -> dict:
    """Params for the current wikitext + revid of a page (for a baseline snapshot)."""
    return {
        "action": "query",
        "prop": "revisions",
        "titles": title,
        "rvprop": "ids|timestamp|content|size",
        "rvslots": "main",
        "rvlimit": 1,
        "format": "json",
        "formatversion": 2,
    }


def build_revision_texts_params(revids: list[int]) -> dict:
    """Params for the FULL TEXT of specific revisions (batched, <=50 per call).

    The per-revision full-text store (maintainer-agreed 2026-06-12): exact
    version materialization beats reconstructing from diffs — revisions are
    fetched in one batched call when the tracker stores them.
    """
    return {
        "action": "query",
        "prop": "revisions",
        "revids": "|".join(str(r) for r in revids[:50]),
        "rvprop": "ids|content",
        "rvslots": "main",
        "format": "json",
        "formatversion": 2,
    }


def parse_revision_texts(payload: dict) -> dict[int, str]:
    """Parse a batched revision-content response -> {revid: wikitext}."""
    out: dict[int, str] = {}
    for pg in (payload or {}).get("query", {}).get("pages", []) or []:
        for r in pg.get("revisions", []) or []:
            revid = r.get("revid")
            slot = (r.get("slots", {}) or {}).get("main", {})
            text = slot.get("content")
            if revid and text is not None:
                out[int(revid)] = text
    return out


def parse_current_text(payload: dict) -> dict:
    """Parse a current-text response -> {revid, text, size, pageid, title} or {}.

    A title the wiki does not know returns ``{"missing": True, "title": ...}``
    so the caller can SAY so — a typo must never become a silent, forever-
    pending watch (live test 2026-06-10).
    """
    pages = (payload or {}).get("query", {}).get("pages", [])
    if not pages:
        return {}
    pg = pages[0]
    if pg.get("missing") or pg.get("invalid"):
        return {"missing": True, "title": pg.get("title")}
    revs = pg.get("revisions", [])
    if not revs:
        return {}
    r = revs[0]
    slot = (r.get("slots", {}) or {}).get("main", {})
    return {
        "revid": r.get("revid"),
        "text": slot.get("content", ""),
        "size": r.get("size"),
        "pageid": pg.get("pageid"),
        "title": pg.get("title"),
    }


def build_categories_params(title: str) -> dict:
    """Params for an article's REAL Wikipedia categories (hidden ones excluded)."""
    return {
        "action": "query",
        "prop": "categories",
        "titles": title,
        "clshow": "!hidden",
        "cllimit": 50,
        "format": "json",
        "formatversion": 2,
    }


def parse_categories(payload: dict) -> list[str]:
    """Category names without the namespace prefix, e.g. 'Constitutional law'."""
    pages = (payload or {}).get("query", {}).get("pages", [])
    if not pages:
        return []
    out = []
    for c in pages[0].get("categories", []) or []:
        name = str(c.get("title", ""))
        out.append(name.split(":", 1)[1] if ":" in name else name)
    return out


def build_compare_params(from_rev: int, to_rev: int) -> dict:
    """Params for a server-computed diff between two revisions."""
    return {
        "action": "compare",
        "fromrev": from_rev,
        "torev": to_rev,
        "prop": "diff",
        "format": "json",
        "formatversion": 2,
    }


def parse_compare(payload: dict) -> dict:
    """Extract added/removed text from a compare diff (HTML table)."""
    body = (payload or {}).get("compare", {}).get("body", "")
    if not body:
        return {"added": "", "removed": "", "added_bytes": 0, "removed_bytes": 0}
    soup = BeautifulSoup(body, "html.parser")
    added = " ".join(td.get_text(" ", strip=True) for td in soup.select("td.diff-addedline"))
    removed = " ".join(td.get_text(" ", strip=True) for td in soup.select("td.diff-deletedline"))
    return {
        "added": added.strip(),
        "removed": removed.strip(),
        "added_bytes": len(added.encode("utf-8")),
        "removed_bytes": len(removed.encode("utf-8")),
    }


def diff_summary(added: str, removed: str, *, limit: int = 2000) -> str:
    """Compact human-readable diff stored on a revision (+ added / - removed)."""
    parts = []
    if removed:
        parts.append("- " + removed[:limit])
    if added:
        parts.append("+ " + added[:limit])
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# The HOT tier's batched read (Q706 / Q707), keyed on page ids (Q715).
# --------------------------------------------------------------------------- #
#: THE PER-REQUEST UNIT IS **TITLES (or page ids), AND IT IS 50**. Read from
#: ``docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`` §8 "Etiquette
#: (SEARCH-VERIFIED)" — "up to **50 titles per request**, and for several pages only
#: the **latest** revision's content may be fetched in one call (``rvlimit`` is
#: refused with multiple titles; with content it is capped at 50)" — corroborated in
#: ``docs/design/ROADMAP_INTAKE_2026-09-12_BETA_PATHWAY.md:408``. It is a limit on
#: PAGES PER REQUEST, not on revisions per page and not on bytes; the same 50 already
#: bounds ``build_revision_texts_params`` above, which is the in-tree corroboration.
#:
#: NOT RE-VERIFIED AGAINST THE LIVE API BY THE SESSION THAT WROTE THIS: every
#: Wikimedia host answers ``000`` from this sandbox (probed 2026-09-17:
#: stream.wikimedia.org, en.wikipedia.org, wikimedia.org, api.wikimedia.org,
#: ores.wikimedia.org all ``000``; api.github.com ``200`` as the control). The
#: operator's own >= 72 h run is what confirms it against the service (gate row V).
#:
#: A wiki that grants ``apihighlimits`` serves 500. This app is an anonymous client
#: and asks for no rights, so 50 is the number that applies to it — raising it on the
#: assumption of a right we never requested is how a polite client becomes a rejected
#: one at somebody else's expense.
MAX_PAGES_PER_REQUEST: int = 50

#: The ``prop`` set Q705's field list needs, in ONE request per batch. Each member is
#: here because a Q705 field reads from it; nothing is requested "while we are at it",
#: because every extra prop is bytes over somebody else's bandwidth.
_HOT_PROPS = "revisions|info|pageprops|categories|coordinates|images|extlinks"


def build_hot_pages_params(pageids: list[int], *, with_assessments: bool = False) -> dict:
    """Params for the current text + Q705 metadata of up to 50 pages, by page id.

    BY ID, NOT BY TITLE. A title is not an identity (Q715): between the change
    arriving and this request being made, the page may have MOVED, and a title
    request would then fetch whatever now occupies the old name — silently, with a
    perfectly ordinary-looking response. An id cannot be wrong in that way.

    ``with_assessments`` is opt-in because ``prop=pageassessments`` exists only on
    editions that installed the extension; asking an edition that has not is a
    warning in the response and a field that is simply absent, which
    :func:`src.wiki.pagefacts.facts_from_page` already handles as absent.
    """
    props = _HOT_PROPS + ("|pageassessments" if with_assessments else "")
    return {
        "action": "query",
        "prop": props,
        "pageids": "|".join(str(p) for p in pageids[:MAX_PAGES_PER_REQUEST]),
        "rvprop": "ids|timestamp|content|size|user|flags|comment",
        "rvslots": "main",
        "inprop": "protection",
        "cllimit": "max",
        "ellimit": "max",
        "imlimit": "max",
        "format": "json",
        "formatversion": 2,
    }


def parse_hot_pages(payload: dict) -> dict[int, dict]:
    """Parse a batched HOT response -> ``{pageid: page-object}``.

    The page object is handed on VERBATIM with two additions this parser is the right
    place for: ``text`` (the main slot's wikitext, lifted out of the revision) and
    ``missing`` (the API's own flag, normalised to a bool). Everything else stays as
    the API spelled it, so :func:`src.wiki.pagefacts.facts_from_page` reads the
    source's own field names and a new prop needs no change here.
    """
    pages = (payload or {}).get("query", {}).get("pages", [])
    out: dict[int, dict] = {}
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        pid = page.get("pageid")
        if not isinstance(pid, int):
            # A page the query could not resolve has no id. It is reported under its
            # title with ``missing: true``; there is nothing to key it on here, and
            # inventing a key would make an absence look like a page.
            continue
        enriched = dict(page)
        enriched["missing"] = bool(page.get("missing"))
        revisions = page.get("revisions")
        if isinstance(revisions, list) and revisions:
            newest = revisions[0]
            if isinstance(newest, dict):
                slots = newest.get("slots")
                main = slots.get("main") if isinstance(slots, dict) else None
                if isinstance(main, dict) and isinstance(main.get("content"), str):
                    enriched["text"] = main["content"]
                enriched["revid"] = newest.get("revid")
                enriched["timestamp"] = _parse_ts(newest.get("timestamp"))
        out[pid] = enriched
    return out
