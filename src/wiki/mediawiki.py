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
        "action": "query", "prop": "revisions", "titles": title,
        "rvprop": "ids|timestamp|user|comment|flags|size|tags",
        "rvlimit": limit, "rvdir": "older", "format": "json", "formatversion": 2,
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
            out.append({
                "revid": r.get("revid"), "parent_revid": r.get("parentid"),
                "timestamp": _parse_ts(r.get("timestamp")), "editor": r.get("user"),
                "editor_anon": bool(r.get("anon", False)),
                "comment": r.get("comment"), "size": r.get("size"),
                "minor": bool(r.get("minor", False)), "bot": bool(r.get("bot", False)),
                "tags": list(r.get("tags", [])), "pageid": pageid, "title": title,
            })
        _ = prev_size
    return out


def build_recentchanges_params(*, namespace: int = 0, limit: int = 50,
                               types: str = "edit|new") -> dict:
    """Params for the recentchanges feed of a wiki (article namespace by default)."""
    return {
        "action": "query", "list": "recentchanges", "rcnamespace": namespace,
        "rcprop": "ids|sizes|flags|user|userid|comment|timestamp|tags|title",
        "rctype": types, "rclimit": limit, "format": "json", "formatversion": 2,
    }


def parse_recentchanges(payload: dict) -> list[dict]:
    """Parse a list=recentchanges response (formatversion=2)."""
    rc = (payload or {}).get("query", {}).get("recentchanges", [])
    out: list[dict] = []
    for c in rc:
        old, new = c.get("oldlen"), c.get("newlen")
        delta = (new - old) if (isinstance(old, int) and isinstance(new, int)) else None
        out.append({
            "revid": c.get("revid"), "parent_revid": c.get("old_revid"),
            "title": c.get("title"), "timestamp": _parse_ts(c.get("timestamp")),
            "editor": c.get("user"), "editor_anon": bool(c.get("anon", False)),
            "bot": bool(c.get("bot", False)), "minor": bool(c.get("minor", False)),
            "comment": c.get("comment"), "size": new, "delta_bytes": delta,
            "tags": list(c.get("tags", [])),
        })
    return out


def build_compare_params(from_rev: int, to_rev: int) -> dict:
    """Params for a server-computed diff between two revisions."""
    return {"action": "compare", "fromrev": from_rev, "torev": to_rev,
            "prop": "diff", "format": "json", "formatversion": 2}


def parse_compare(payload: dict) -> dict:
    """Extract added/removed text from a compare diff (HTML table)."""
    body = (payload or {}).get("compare", {}).get("body", "")
    if not body:
        return {"added": "", "removed": "", "added_bytes": 0, "removed_bytes": 0}
    soup = BeautifulSoup(body, "html.parser")
    added = " ".join(td.get_text(" ", strip=True) for td in soup.select("td.diff-addedline"))
    removed = " ".join(td.get_text(" ", strip=True) for td in soup.select("td.diff-deletedline"))
    return {
        "added": added.strip(), "removed": removed.strip(),
        "added_bytes": len(added.encode("utf-8")), "removed_bytes": len(removed.encode("utf-8")),
    }


def diff_summary(added: str, removed: str, *, limit: int = 2000) -> str:
    """Compact human-readable diff stored on a revision (+ added / - removed)."""
    parts = []
    if removed:
        parts.append("- " + removed[:limit])
    if added:
        parts.append("+ " + added[:limit])
    return "\n".join(parts)
