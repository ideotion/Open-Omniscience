"""
Read one page out of a downloaded MULTISTREAM dump — locally, zero network.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gap this closes (field report #4, elevated): downloaded dumps were files
the app could not open. Wikimedia's ``pages-articles-multistream`` dump is a
CONCATENATION of small bz2 streams (≤100 pages each), and its companion index
lists ``offset:pageid:title`` per page — so finding a page is: scan the index
for the title, ``seek()`` to the stream's byte offset, decompress ONE small
block, parse the ≤100 pages it holds. No database, no network, no rebuild.

Honesty notes carried in every result:
  * the text returned is RAW WIKITEXT (unrendered) from the dump as
    downloaded — a snapshot, not the live article;
  * the index scan is linear (the method states lines scanned); an exact
    title match wins, otherwise a case-insensitive match is used and SAID;
  * legacy single-stream ``pages-articles`` files cannot be random-accessed —
    that is reported honestly with the re-download hint, never guessed at.
"""

from __future__ import annotations

import bz2
import logging
import time
import xml.etree.ElementTree as ET  # noqa: S405 - ET.ParseError type only; parsing is defused
from pathlib import Path

# A downloaded dump arrives over the network: parse it as UNTRUSTED XML. defusedxml
# blocks entity-expansion / external-entity attacks (billion laughs, XXE) that the
# stdlib parser is vulnerable to -- a real defense, not a suppressed warning.
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as _safe_fromstring

from src.wiki.dumps import dump_filename, validate_wiki_code

_LOG = logging.getLogger(__name__)

_READ_CHUNK = 1024 * 256


def dump_paths(wiki: str, base_dir: Path | None = None) -> dict:
    """Where the multistream pair (and the legacy file) would live for ``wiki``."""
    # Validate first so an unsafe edition code can never reach a filesystem path
    # (path-traversal defense in depth; dump_filename re-checks).
    wiki = validate_wiki_code(wiki)
    if base_dir is None:
        from src.paths import data_dir

        base_dir = data_dir() / "wiki_dumps"
    base_dir = Path(base_dir)
    return {
        "data": base_dir / dump_filename(wiki, "pages-articles-multistream"),
        "index": base_dir / dump_filename(wiki, "pages-articles-multistream-index"),
        "legacy": base_dir / dump_filename(wiki, "pages-articles"),
    }


def _scan_index(index_path: Path, title: str) -> tuple[dict | None, int]:
    """Find ``title`` in the multistream index. Returns (hit, lines_scanned).

    One linear pass; an exact match returns immediately, the first
    case-insensitive match is remembered as a fallback (and labelled).
    """
    want = title.strip()
    want_cf = want.casefold()
    fallback: dict | None = None
    scanned = 0
    with bz2.open(index_path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            scanned += 1
            parts = line.rstrip("\n").split(":", 2)
            if len(parts) != 3:
                continue
            offset_s, pageid_s, page_title = parts
            if page_title == want:
                return ({"offset": int(offset_s), "pageid": int(pageid_s),
                         "title": page_title, "match": "exact"}, scanned)
            if fallback is None and page_title.casefold() == want_cf:
                fallback = {"offset": int(offset_s), "pageid": int(pageid_s),
                            "title": page_title, "match": "case-insensitive"}
    return fallback, scanned


def _read_stream_block(data_path: Path, offset: int) -> bytes:
    """Decompress exactly ONE bz2 stream starting at ``offset`` (≤100 pages)."""
    dec = bz2.BZ2Decompressor()
    out = bytearray()
    with open(data_path, "rb") as fh:
        fh.seek(offset)
        while not dec.eof:
            chunk = fh.read(_READ_CHUNK)
            if not chunk:
                break
            out += dec.decompress(chunk)
    return bytes(out)


def _extract_page(block_xml: bytes, pageid: int) -> dict | None:
    """Pull one ``<page>`` out of a decompressed block (bare page elements)."""
    root = _safe_fromstring(b"<root>" + block_xml + b"</root>")
    for page in root.iter("page"):
        pid = page.findtext("id")
        if pid is None or int(pid) != pageid:
            continue
        rev = page.find("revision")
        return {
            "title": page.findtext("title") or "",
            "pageid": pageid,
            "ns": page.findtext("ns"),
            "revid": rev.findtext("id") if rev is not None else None,
            "rev_timestamp": rev.findtext("timestamp") if rev is not None else None,
            "wikitext": (rev.findtext("text") if rev is not None else None) or "",
        }
    return None


def find_page(wiki: str, title: str, *, base_dir: Path | None = None) -> dict:
    """Look ``title`` up in the downloaded multistream dump for ``wiki``.

    Always returns a dict; ``found`` plus an honest ``reason``/``note`` tell
    the caller exactly what happened — including the legacy-file case where
    reading is impossible without a re-download.
    """
    paths = dump_paths(wiki, base_dir)
    have_data, have_index = paths["data"].exists(), paths["index"].exists()
    if not (have_data and have_index):
        reason = "no-multistream-dump" if not have_data else "no-index"
        return {
            "found": False,
            "reason": reason,
            "legacy_file_present": paths["legacy"].exists(),
            "wiki": wiki.lower(),
        }

    t0 = time.monotonic()
    hit, scanned = _scan_index(paths["index"], title)
    if hit is None:
        return {
            "found": False, "reason": "title-not-in-index", "wiki": wiki.lower(),
            "index_lines_scanned": scanned,
            "scan_seconds": round(time.monotonic() - t0, 3),
        }
    try:
        block = _read_stream_block(paths["data"], hit["offset"])
        page = _extract_page(block, hit["pageid"])
    except (OSError, ValueError, ET.ParseError, DefusedXmlException) as exc:
        _LOG.warning("dump block read failed for %s:%s", wiki, title, exc_info=True)
        return {"found": False, "reason": "block-unreadable", "error": str(exc),
                "wiki": wiki.lower()}
    if page is None:
        return {"found": False, "reason": "page-missing-from-block",
                "wiki": wiki.lower()}
    page.update({
        "found": True,
        "wiki": wiki.lower(),
        "match": hit["match"],
        "index_lines_scanned": scanned,
        "scan_seconds": round(time.monotonic() - t0, 3),
        "method": (
            "multistream index scanned linearly for the title, then one bz2 "
            "stream decompressed at its byte offset — local files only, no network"
        ),
        "note": (
            "raw wikitext (unrendered) from your downloaded dump — a snapshot "
            "as of the dump date, not the live article"
        ),
    })
    return page


def readable_wikis(base_dir: Path | None = None) -> list[str]:
    """Editions whose multistream data+index pair is fully present on disk."""
    if base_dir is None:
        from src.paths import data_dir

        base_dir = data_dir() / "wiki_dumps"
    base_dir = Path(base_dir)
    out = []
    for f in sorted(base_dir.glob("*wiki-latest-pages-articles-multistream.xml.bz2")):
        wiki = f.name.split("wiki-latest-", 1)[0]
        if (base_dir / dump_filename(wiki, "pages-articles-multistream-index")).exists():
            out.append(wiki)
    return out
