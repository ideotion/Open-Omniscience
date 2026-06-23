"""Home-card (Lead) click diagnostics (maintainer field report 2026-06-22).

Records, for every Home card the briefing currently produces, EXACTLY what clicking it
loads in the analysis window — so we can see which cards hard-link to their own corpus
and which fall back to a fuzzy text search that loses it.

The bug it surfaces: a card WITHOUT ``article_ids`` falls back (in app.js) to
``openAnalysisFor(cardAnalyzeQuery(card))`` — a TEXT SEARCH of the card's seed term.
For e.g. the source-laundering card that means clicking searches the origin domain
("enable-javascript.com") and loads tens of thousands of articles, NOT the exact 314
citing articles the card identified. A card that carries ``article_ids`` instead opens
``openAnalysisForIds`` over precisely its set ("hard-linked").

This is a RECURRING tool (a Settings → Diagnostics button + GET endpoint): run it, send
the JSON, and the per-card verdict pinpoints every card that needs its exact corpus wired.
Read-only, no network, NO score.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

# Replicates app.js cardAnalyzeQuery: a quoted term in the title wins, else the card
# `key`, else the title with quotes stripped. This is the seed a search-fallback uses.
_QUOTED = re.compile(r'[“"]([^”"]{2,})[”"]')


def card_seed_query(card: dict) -> str:
    title = card.get("title") or ""
    m = _QUOTED.search(title)
    if m and m.group(1).strip():
        return m.group(1).strip()
    key = card.get("key")
    if key and str(key).strip():
        return str(key).strip()
    return re.sub(r"[“”\"]", "", title).strip()


def card_click_diagnostics(session) -> dict:
    """For each current Home card: does clicking it open its EXACT corpus (article_ids,
    "hard-linked") or a text search of its seed term ("search-fallback")? A search whose
    live FTS count differs wildly from the card's own ``n`` means the click LOSES the
    card's corpus — the dysfunction to fix, per card type."""
    from src.briefing import service
    from src.database.fts import SearchQueryError, search_ids

    cards = service.get_briefing(session, force=True, include_dismissed=True).get("cards", [])
    out: list[dict] = []
    hard = soft = mismatched = 0
    by_type: dict[str, dict] = {}

    for c in cards:
        ctype = c.get("type") or "?"
        ids = c.get("article_ids") or []
        has_ids = bool(ids)
        n = c.get("n")
        rec: dict = {
            "type": ctype,
            "title": c.get("title"),
            "bucket": c.get("bucket"),
            "id": c.get("id"),
            "n": n,                                  # the corpus size the card CLAIMS
            "signal": c.get("signal"),               # what the card is about (metric/value)
            "has_article_ids": has_ids,
            "article_ids_n": len(ids),
        }
        if has_ids:
            rec["click"] = {"mode": "exact", "opens": "openAnalysisForIds", "loads_n": len(ids)}
            rec["hard_linked"] = True
            rec["mismatch"] = False
            rec["verdict"] = f"hard-linked → opens exactly {len(ids)} articles"
            hard += 1
        else:
            seed = card_seed_query(c)
            search_n: int | None = None
            err: str | None = None
            try:
                search_n = len(search_ids(session, seed)) if seed else 0
            except SearchQueryError as exc:
                err = str(exc)
            # MISMATCH = the fuzzy search loads a wildly different count than the card's n
            # (or zero), i.e. clicking does NOT reproduce the card's corpus.
            mm = bool(
                n is not None
                and search_n is not None
                and (search_n == 0 or search_n > max(50, n * 3))
            )
            rec["seed_query"] = seed
            rec["click"] = {"mode": "search", "opens": "openAnalysisFor", "seed": seed,
                            "loads_n": search_n, "error": err}
            rec["hard_linked"] = False
            rec["mismatch"] = mm
            if mm:
                rec["verdict"] = (
                    f"SEARCH-FALLBACK MISMATCH → clicking runs a text search for {seed!r} and "
                    f"loads {search_n} articles, but this card is about {n} — the exact corpus is LOST"
                )
                mismatched += 1
            else:
                rec["verdict"] = f"search-fallback → text search {seed!r} loads {search_n} (card n={n})"
            soft += 1

        bt = by_type.setdefault(ctype, {"total": 0, "hard_linked": 0, "search_fallback": 0, "mismatched": 0})
        bt["total"] += 1
        bt["hard_linked" if has_ids else "search_fallback"] += 1
        if rec["mismatch"]:
            bt["mismatched"] += 1
        out.append(rec)

    return {
        "schema": "oo-cardclick-1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "total": len(cards),
            "hard_linked": hard,
            "search_fallback": soft,
            "mismatched": mismatched,
        },
        "by_type": by_type,
        "cards": out,
        "method": (
            "For each Home card (Lead): what clicking its body loads in the analysis window. "
            "hard-linked = the card carries article_ids → openAnalysisForIds over its EXACT set. "
            "search-fallback = no article_ids → openAnalysisFor(seed) runs a TEXT SEARCH of the "
            "card's seed term. A search-fallback whose live FTS count differs wildly from the "
            "card's own n means the click LOSES the card's corpus (the 'no hard linking' bug)."
        ),
        "caveat": (
            "search-fallback counts are the live FTS match for the seed term; a large mismatch "
            "vs the card's n is the dysfunction. The fix is per producer: carry article_ids."
        ),
    }
