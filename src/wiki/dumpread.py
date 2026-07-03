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


def _iter_block_pages(block_xml: bytes, ns_filter: set[str] | None):
    """Yield EVERY ``<page>`` (namespace-filtered) from a decompressed block."""
    root = _safe_fromstring(b"<root>" + block_xml + b"</root>")
    for page in root.iter("page"):
        ns = page.findtext("ns")
        if ns_filter is not None and (ns or "0") not in ns_filter:
            continue
        pid = page.findtext("id")
        rev = page.find("revision")
        yield {
            "title": page.findtext("title") or "",
            "pageid": int(pid) if pid and pid.isdigit() else None,
            "ns": ns,
            "wikitext": (rev.findtext("text") if rev is not None else None) or "",
        }


def iter_pages(
    wiki: str,
    *,
    base_dir: Path | None = None,
    namespaces: tuple[int, ...] | None = (0,),
    limit: int | None = None,
):
    """Stream every page (raw wikitext) out of a downloaded multistream dump.

    ONE linear pass: the index groups pages into ≤100-page bz2 blocks (one per byte
    ``offset``), so we visit each DISTINCT offset once, ``seek()`` + decompress its
    block once, and yield all pages it holds — turning a per-title read (which rescans
    the whole index) into a single O(N) sweep suitable for building a search index.

    ``namespaces`` filters by the page ``<ns>`` (default ``(0,)`` = articles only;
    ``None`` = every namespace). ``limit`` caps the number of pages yielded. A block
    that fails to read/parse is skipped with a warning, never aborting the sweep.
    Yields ``{title, pageid, ns, wikitext}``; yields nothing if the dump is absent.
    """
    wiki = validate_wiki_code(wiki)
    paths = dump_paths(wiki, base_dir)
    if not (paths["data"].exists() and paths["index"].exists()):
        return
    ns_filter = None if namespaces is None else {str(int(n)) for n in namespaces}

    # Collect the DISTINCT block offsets in first-seen order. The index is one line
    # per page (``offset:pageid:title``); many pages share an offset (a block). A
    # set of offsets is small even for the largest edition (~pages/100 entries).
    offsets: list[int] = []
    seen: set[int] = set()
    with bz2.open(paths["index"], "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split(":", 2)
            if len(parts) != 3:
                continue
            try:
                off = int(parts[0])
            except ValueError:
                continue
            if off not in seen:
                seen.add(off)
                offsets.append(off)

    yielded = 0
    for off in offsets:
        try:
            block = _read_stream_block(paths["data"], off)
        except OSError:
            _LOG.warning("dump block read failed for %s at offset %s", wiki, off, exc_info=True)
            continue
        try:
            for page in _iter_block_pages(block, ns_filter):
                yield page
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
        except (ValueError, ET.ParseError, DefusedXmlException):
            _LOG.warning("dump block parse failed for %s at offset %s", wiki, off, exc_info=True)
            continue


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


def search_titles(
    wiki: str,
    query: str,
    *,
    limit: int = 20,
    scan_cap: int = 4_000_000,
    base_dir: Path | None = None,
) -> dict:
    """Substring TITLE search over a downloaded edition's multistream index.

    HONEST SCOPE: this searches TITLES only. The index lists every page's
    ``offset:pageid:title`` so a title scan is cheap and bounded; full-text over
    page BODIES would mean decompressing every bz2 block (the whole dump) per query,
    which is out of scope here — stated in ``note``. Each hit carries enough to read
    the page via ``find_page`` (the local dump reader). Always returns a dict; the
    linear scan is capped at ``scan_cap`` lines (``scanned``/``capped`` reported)."""
    wiki = validate_wiki_code(wiki)
    paths = dump_paths(wiki, base_dir)
    if not paths["index"].exists():
        return {
            "wiki": wiki.lower(), "query": query, "items": [], "scanned": 0,
            "reason": "no-index", "legacy_file_present": paths["legacy"].exists(),
        }
    want = query.strip().casefold()
    items: list[dict] = []
    scanned = 0
    capped = False
    t0 = time.monotonic()
    if want:
        with bz2.open(paths["index"], "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                scanned += 1
                if scanned > scan_cap:
                    capped = True
                    break
                parts = line.rstrip("\n").split(":", 2)
                if len(parts) != 3:
                    continue
                title = parts[2]
                if want in title.casefold():
                    items.append({"title": title, "pageid": int(parts[1]), "wiki": wiki.lower()})
                    if len(items) >= max(1, limit):
                        break
    return {
        "wiki": wiki.lower(),
        "query": query,
        "items": items,
        "scanned": scanned,
        "capped": capped,
        "scan_seconds": round(time.monotonic() - t0, 3),
        "method": (
            "multistream index scanned linearly for titles containing the query — "
            "local files only, no network"
        ),
        "note": (
            "TITLE matches in your downloaded dump (a snapshot as of the dump date); "
            "page bodies are not full-text-searched — open a title to read its wikitext"
        ),
    }


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
