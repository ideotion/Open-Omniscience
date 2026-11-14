"""Every Home card and what it was built from, as ONE zip (saved by the Field data button).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-asked 2026-11-14 (Lane X): «include in the field test to download all cards and their
full associated content, so I can hand it back to you for analysis and optimization».
``FIELD_DATA_EXPORTS`` in ``src/static/app-diagnostics.js`` POSTs this route; delete it only
together with that entry. Imported after the other field-data route, so no pinned position moves.

WHAT THE ZIP HOLDS
------------------
* ``manifest.json``: what each file is, and in plain words what PERSONAL content the zip carries
  (article titles and excerpts, the terms the cards are about, places with coordinates when any),
  counted from the files themselves rather than asserted.
* ``feed.json``: the Home feed exactly as the app serves it from its cache (the same cards the
  full view and the simple view show), each with its dismissed state, plus the feed's own record:
  when it was computed, whether the last refresh stopped early or kept the previous feed, which
  producers were stopped at their bound, each producer's time and outcome, and whether the corpus
  has grown enough since for the app to call the feed stale. Nothing is recomputed: a field file
  describes what the operator saw.
* ``cards.json``: per card, the app's own checks (the trigger math recomputed, the
  non-fabrication checks, whether its article ids resolve) and its evidence: the articles behind
  it (exact count, a bounded sample with metadata, linked layers and an excerpt), and the keyword
  facts when the card is about a term.
* ``quality.json``: ``src.briefing.card_quality`` run over all of it, the same checks
  ``scripts/card_quality_report.py`` runs on the returned file.
* ``selfcheck.jsonl``: the recurring self-check history (one line per Home refresh, newest 200).

WHAT STAYS HOME. Every string passes ``scrubbed_value`` (no passphrase the process holds, in any
shape). Article addresses are written without user name, password, query or fragment (a token in
a query string is the one secret an address commonly carries). A newsletter's body stays out
unless ``OO_QUALITY_INCLUDE_NEWSLETTER_TEXT`` is set, the R655 gate the other field files use.
Read-only, loopback, no network; a POST (R694) because it reads article text.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from src.database.session import get_db

from ._base import router

FIELD_CARDS_SCHEMA = "oo-field-cards-1"
#: Articles with a payload per card (the exact total is always stated beside it).
FIELD_CARDS_MAX_ARTICLES = 25
#: Characters of article text per shown article.
FIELD_CARDS_EXCERPT_CHARS = 600
#: Linked rows (keywords, places, entities, ...) per layer per shown article.
FIELD_CARDS_MAX_LINKED_ROWS = 10
#: Seconds spent resolving evidence before the remaining cards are written without it (and say so).
FIELD_CARDS_EVIDENCE_BUDGET_S = 180.0
_STATEMENT_DEADLINE_S = 240.0
_COORD_KEYS = frozenset({"lat", "lon", "lng", "latitude", "longitude"})


def _clean_url(url: Any) -> Any:
    """An address without user name, password, query or fragment."""
    if not isinstance(url, str) or not url:
        return url
    try:
        parts = urlsplit(url)
        if not parts.netloc:
            return url  # an address inside the app ("/#markets") carries nothing of anyone's
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return None


def _clean_urls(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (_clean_url(v) if k in ("url", "href", "link") else _clean_urls(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_urls(v) for v in value]
    return value


def _count_coordinates(value: Any) -> int:
    if isinstance(value, dict):
        own = 1 if any(str(k).lower() in _COORD_KEYS and v is not None for k, v in value.items()) else 0
        return own + sum(_count_coordinates(v) for v in value.values())
    if isinstance(value, list):
        return sum(_count_coordinates(v) for v in value)
    return 0


def _newsletter_article_ids(db: Session, ids: list[int]) -> set[int]:
    """Which of ``ids`` are newsletters, by the R655 test the other field files use."""
    from sqlalchemy import or_, select

    from src.database.models import Article, Source
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    out: set[int] = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        rows = db.execute(
            select(Article.id)
            .outerjoin(Source, Source.id == Article.source_id)
            .where(Article.id.in_(chunk))
            .where(or_(Source.domain.in_(NEWSLETTER_SOURCE_DOMAINS), Article.newsletter_attached_via.isnot(None)))
        ).all()
        out.update(int(r[0]) for r in rows)
    return out


def _evidence_ids(card: dict) -> list[int]:
    ids = [i for i in card.get("article_ids") or [] if isinstance(i, int)]
    seen = set(ids)
    for e in card.get("evidence") or []:
        if isinstance(e, dict):
            for name in ("article_id", "id"):
                v = e.get(name)
                if isinstance(v, int) and not isinstance(v, bool):
                    if v not in seen:
                        ids.append(v)
                        seen.add(v)
                    break
    return ids


def _card_evidence(db: Session, card: dict, *, include_newsletters: bool) -> dict:
    from src.briefing.card_audit import _keyword_facts, _resolve_articles, _safe_section

    ids = _evidence_ids(card)
    shown = ids[:FIELD_CARDS_MAX_ARTICLES]
    resolved = _safe_section(
        "articles",
        lambda: _resolve_articles(
            db, ids, depth="standard", excerpt_chars=FIELD_CARDS_EXCERPT_CHARS,
            max_linked_rows=FIELD_CARDS_MAX_LINKED_ROWS, shown_ids=shown,
        ),
    )
    withheld = 0
    if isinstance(resolved, dict) and resolved.get("items") and not include_newsletters:
        letters = _newsletter_article_ids(db, [it["id"] for it in resolved["items"] if isinstance(it.get("id"), int)])
        for it in resolved["items"]:
            if it.get("id") in letters and "content" in it:
                it["content"] = {"withheld": "a newsletter body stays home unless OO_QUALITY_INCLUDE_NEWSLETTER_TEXT is set (R655)"}
                withheld += 1
    keywords = _safe_section("keywords", lambda: _keyword_facts(db, SimpleNamespace(key=card.get("key") or "")))
    return {
        "total": len(ids),
        "from_article_ids": len(card.get("article_ids") or []),
        "shown": resolved.get("shown") if isinstance(resolved, dict) else 0,
        "resolved_total": resolved.get("resolved_total") if isinstance(resolved, dict) else None,
        "missing_n": resolved.get("missing_n") if isinstance(resolved, dict) else None,
        "quarantined_n": resolved.get("quarantined_n") if isinstance(resolved, dict) else None,
        "newsletter_bodies_withheld": withheld,
        "articles": resolved,
        "keywords": keywords,
        "note": "'total' is the exact number of articles behind the card; 'shown' is how many carry a payload here.",
    }


def build_field_cards_files(db: Session, *, now: datetime | None = None) -> dict[str, str]:
    """The zip's files, by name. Reads the cache and the evidence; writes nothing."""
    from src.api.diagnostics.source_samples import include_newsletter_text
    from src.briefing import service
    from src.briefing.card_audit import check_trigger, non_fabrication_checks
    from src.briefing.card_quality import CHECKS, quality_report, with_producers
    from src.briefing.registry import producers
    from src.monitoring.secret_scrub import scrubbed_value

    now = now or datetime.now(UTC)
    include_nl = include_newsletter_text()
    payload = service._read_cache() or {}
    has_feed = bool(payload)
    view = service._present(payload, include_dismissed=True) if has_feed else {"cards": []}
    try:
        stale = bool(service._is_cache_stale(db, payload)) if has_feed else None
    except Exception:  # noqa: BLE001 - a count that cannot be read leaves the answer unknown, not false
        stale = None
    registered = [n for n, _p in producers()]
    cards = with_producers(payload, [c for c in view.get("cards") or [] if isinstance(c, dict)])
    meta_keys = ("version", "generated_at", "article_count", "incomplete_reason", "kept_reason",
                 "stopped_producers", "producer_deadline_s", "producer_timings", "card_producers")
    meta = {k: payload.get(k) for k in meta_keys if k in payload}
    feed = {
        "schema": FIELD_CARDS_SCHEMA,
        "feed_present": has_feed,
        "feed": meta,
        "stale_by_corpus_growth": stale,
        "registered_producers": registered,
        "count": view.get("count"),
        "total": view.get("total"),
        "dismissed_count": view.get("dismissed_count"),
        "cards": cards,
        "note": ("The cards exactly as the app's cache serves them to Home (full and simple view), dismissed ones "
                 "included and flagged. Nothing here was recomputed for this file."),
    }

    started = time.monotonic()
    per_card: dict[str, dict] = {}
    rows = []
    skipped = 0
    from src.database.maintenance import StatementTimeout, statement_deadline

    with statement_deadline(db, _STATEMENT_DEADLINE_S):
        for c in cards:
            cid = str(c.get("id"))
            arithmetic = check_trigger(c.get("trigger"))
            if time.monotonic() - started < FIELD_CARDS_EVIDENCE_BUDGET_S:
                try:
                    evidence: dict = _card_evidence(db, c, include_newsletters=include_nl)
                except StatementTimeout:
                    skipped += 1
                    evidence = {"skipped": "statement deadline", "deadline_s": _STATEMENT_DEADLINE_S,
                                "total": len(_evidence_ids(c))}
            else:
                skipped += 1
                evidence = {"skipped": "time budget", "budget_s": FIELD_CARDS_EVIDENCE_BUDGET_S,
                            "total": len(_evidence_ids(c))}
            per_card[cid] = {"arithmetic": arithmetic}
            if "skipped" not in evidence:
                per_card[cid]["evidence"] = evidence
            rows.append({
                "card_id": cid,
                "type": c.get("type"),
                "produced_by": c.get("produced_by"),
                "dismissed": bool(c.get("dismissed")),
                "arithmetic": arithmetic,
                "non_fabrication": non_fabrication_checks(c),
                "evidence": evidence,
            })
    cards_doc = {
        "schema": FIELD_CARDS_SCHEMA,
        "cards": rows,
        "evidence_skipped_by_budget": skipped,
        "evidence_seconds": round(time.monotonic() - started, 1),
        "limits": {
            "articles_with_payload_per_card": FIELD_CARDS_MAX_ARTICLES,
            "excerpt_chars": FIELD_CARDS_EXCERPT_CHARS,
            "linked_rows_per_layer": FIELD_CARDS_MAX_LINKED_ROWS,
            "evidence_budget_s": FIELD_CARDS_EVIDENCE_BUDGET_S,
        },
    }
    quality = quality_report(cards, meta=meta, registered=registered, per_card=per_card, now=now)

    history = ""
    try:
        path = service._self_check_path()
        if path.exists():
            history = path.read_text("utf-8")
    except OSError:
        history = ""

    feed = scrubbed_value(_clean_urls(feed))
    cards_doc = scrubbed_value(_clean_urls(cards_doc))
    quality = scrubbed_value(quality)
    history = scrubbed_value(history)

    excerpts = sum(
        1 for r in cards_doc["cards"]
        for it in ((r.get("evidence") or {}).get("articles") or {}).get("items") or []
        if isinstance(it, dict) and isinstance(it.get("content"), dict) and it["content"].get("text")
    )
    titles = sum(
        1 for r in cards_doc["cards"]
        for it in ((r.get("evidence") or {}).get("articles") or {}).get("items") or []
        if isinstance(it, dict) and it.get("title")
    )
    coords = _count_coordinates(feed) + _count_coordinates(cards_doc)
    from src import __version__

    manifest = {
        "schema": FIELD_CARDS_SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "app_version": __version__,
        "files": {
            "feed.json": "the Home feed as served from the cache, every card, dismissed ones flagged, with the feed's own record",
            "cards.json": "per card: the app's own checks and the evidence it was built from",
            "quality.json": "the card quality checks over all of it (the same ones scripts/card_quality_report.py runs)",
            "selfcheck.jsonl": "the recurring self-check after each Home refresh, newest 200 (check ids, counts, card ids)",
        },
        "personal_content": {
            "summary": (
                "This file describes what you collected and follow. Read it before you send it; it leaves your "
                "machine only if you send it."
            ),
            "cards": len(cards),
            "card_text": "every card's title and summary, which name the terms, places, sources and stories they are about",
            "article_titles": titles,
            "article_excerpts": excerpts,
            "excerpt_chars_max": FIELD_CARDS_EXCERPT_CHARS,
            "newsletter_bodies": "included (OO_QUALITY_INCLUDE_NEWSLETTER_TEXT is set)" if include_nl else "withheld (R655)",
            "places_with_coordinates": coords,
            "dismissed_cards": sum(1 for c in cards if c.get("dismissed")),
        },
        "not_included": [
            "your passphrase or any key: every string is scrubbed of the passphrases the app holds",
            "query strings, fragments, user names and passwords in addresses: removed",
            "anything from the network: nothing is fetched to make this file",
        ],
        "checks": {k: v["what"] for k, v in CHECKS.items()},
    }
    dump = json.dumps
    return {
        "manifest.json": dump(manifest, ensure_ascii=False, indent=2, default=str),
        "feed.json": dump(feed, ensure_ascii=False, indent=2, default=str),
        "cards.json": dump(cards_doc, ensure_ascii=False, indent=2, default=str),
        "quality.json": dump(quality, ensure_ascii=False, indent=2, default=str),
        "selfcheck.jsonl": history,
    }


@router.post("/field-cards")
def field_cards(db: Session = Depends(get_db)) -> Response:
    """Field data export: every Home card and its evidence, as ONE zip (see the module docstring)."""
    files = build_field_cards_files(db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files.items():
            z.writestr(name, data)
    fname = f"oo-field-cards-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
