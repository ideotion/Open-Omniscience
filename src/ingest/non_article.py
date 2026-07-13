"""
Non-article classifier — stop nav / index / tag / tool / wall pages at the ingest door.

The source-quality diagnostic's recall gap (2026-07-13) showed the corpus contains items that are
NOT articles but have perfectly normal keyword stats, so the repetition-based detector can't see
them: section pages (``irishexaminer.com/world/``), taxonomy listings (``.../news/tag/depression``),
utility/tool pages (a WHOIS lookup, a downloads index, a login/search page), a site homepage, and
consent/paywall/404 WALLS whose body is chrome. This classifier catches those at INGEST, before the
item is stored, so they never enter the corpus.

Design — HIGH PRECISION over recall (a false positive would DROP A REAL ARTICLE = data loss). The
LOAD-BEARING guard is the EXTRACTED BODY LENGTH: by the time this runs, ``extract_article``
(trafilatura) has already pulled a real article body (it returns ``None`` below a char floor, so
the pipeline never reaches here otherwise). A nav / index / tag / section / wall page yields only a
THIN extracted body; a real article yields a SUBSTANTIAL one. So:
  * A body at or above ``_ARTICLE_MIN_WORDS`` is a real article — KEPT regardless of URL shape. A
    genuine article at ``/business``, ``/category/politics`` or ``/tag/gaza`` is never dropped.
  * Only for a THIN body do the URL-shape / wall rules fire — the drop condition is (thin body) AND
    (a non-article URL shape OR a definitive wall phrase), which is what makes it high-precision.
  * Every rule is EXPLICIT; the classifier returns the first matching rule with a disclosed REASON +
    signal, never a fuzzy score.

This is not-exclusion of a SOURCE (the source's real articles still ingest) — it is not-storing a
non-article. The caller SKIPS with a distinct, counted, reversible outcome; nothing is silently
dropped (``OO_SKIP_NON_ARTICLES=0`` disables the whole filter).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

# Utility / tool / listing path segments that are (almost) never an article slug on their own.
_UTILITY_SEGMENTS = frozenset({
    "search", "login", "signin", "sign-in", "register", "signup", "sign-up", "subscribe",
    "account", "accounts", "glossary", "sitemap", "sitemaps", "rss", "feed", "feeds", "print",
    "cart", "checkout", "download", "downloads", "wp-login", "wp-admin", "admin",
})
# Taxonomy segments — a LISTING when followed by a short taxonomy value, not an article slug.
_TAXONOMY_SEGMENTS = frozenset({
    "tag", "tags", "category", "categories", "topic", "topics", "author", "authors",
})
# Single-segment section LANDINGS (a section front, not an article).
_SECTION_WORDS = frozenset({
    "world", "news", "sport", "sports", "business", "politics", "opinion", "opinions",
    "technology", "tech", "science", "sciences", "health", "culture", "entertainment",
    "lifestyle", "life", "travel", "money", "markets", "economy", "weather", "video", "videos",
    "photos", "gallery", "galleries", "podcast", "podcasts", "newsletters", "events", "about",
    "contact", "index", "home",
})
# Definitive consent / paywall / error WALL phrases (matched only on a SHORT body).
_WALL_PHRASES = (
    "enable javascript", "please enable javascript", "javascript is disabled",
    "javascript to continue", "subscribe to continue", "subscribe to read",
    "sign in to continue", "sign in to read", "log in to continue", "create an account to",
    "register to read", "register to continue", "for full access", "404 not found",
    "page not found", "access denied", "you don't have permission",
    "this content is not available", "content is no longer available",
    "you have reached your", "to continue reading", "your free articles",
)
# The load-bearing guard: a body at/above this many words is a real article, KEPT regardless of
# URL. The recall-gap non-article pages had ~30-50 extracted words; real articles run far longer.
# So a THIN body below this is the precondition for any URL/wall drop rule to fire.
_ARTICLE_MIN_WORDS = 100
_WALL_MAX_WORDS = 40       # a wall's body is chrome-tiny; gate the phrase match below this so a
                           # 40-99-word real brief that merely quotes a wall phrase is kept
_TAXONOMY_MAX_LEN = 40     # a taxonomy value is short; an article slug is long
_TAXONOMY_MAX_HYPHENS = 3  # "middle-east" is a tag; "us-court-upholds-birthright-citizenship" isn't


@dataclass(frozen=True)
class NonArticleVerdict:
    """Why an item was judged not an article. ``signal`` is the machine tag, ``reason`` the human
    sentence — a DEDUCED candidate, disclosed and reversible, never a verdict on the SOURCE."""

    signal: str
    reason: str


def _is_short_taxonomy(seg: str) -> bool:
    return len(seg) <= _TAXONOMY_MAX_LEN and seg.count("-") <= _TAXONOMY_MAX_HYPHENS


def classify_non_article(
    url: str, *, title: str | None = None, text: str | None = None, word_count: int | None = None,
) -> NonArticleVerdict | None:
    """Return a verdict if ``url``/``text`` is CLEARLY a non-article, else ``None`` (keep it).

    A SUBSTANTIAL extracted body (``>= _ARTICLE_MIN_WORDS``) is a real article — kept regardless of
    URL. Only a THIN body proceeds to the wall / URL rules (order: boilerplate wall → utility path →
    pagination → taxonomy listing → homepage → section landing). Conservative — when in doubt, keep."""
    wc: int | None = word_count if word_count is not None else (len(text.split()) if text else None)

    # THE guard: a real article has a substantial extracted body — keep it whatever the URL shape.
    # A nav/index/tag/section/wall page yields only a thin body; only that proceeds to the rules.
    if wc is not None and wc >= _ARTICLE_MIN_WORDS:
        return None

    # 1. Boilerplate WALL — a chrome-TINY body dominated by a definitive consent/paywall/error
    #    phrase. The extra-tight word gate keeps a short real brief that merely quotes the phrase.
    if text and wc is not None and wc < _WALL_MAX_WORDS:
        low = text.lower()
        for phrase in _WALL_PHRASES:
            if phrase in low:
                return NonArticleVerdict("boilerplate_wall", f"consent/paywall/error wall: '{phrase}'")

    path = urlparse(url).path.strip("/").lower()
    segments = [s for s in path.split("/") if s]

    if not segments:
        return NonArticleVerdict("url_homepage", "site homepage / front page — no article path")

    # 2. Utility / tool path anywhere in the URL.
    for i, seg in enumerate(segments):
        if seg in _UTILITY_SEGMENTS:
            return NonArticleVerdict("url_utility", f"utility/tool path segment '/{seg}'")
        if seg == "page" and i + 1 < len(segments) and segments[i + 1].isdigit():
            return NonArticleVerdict("url_pagination", "pagination listing page")

    # 3. Taxonomy LISTING — a tag/category/author segment followed by at most a short value.
    for i, seg in enumerate(segments):
        if seg in _TAXONOMY_SEGMENTS:
            rest = segments[i + 1:]
            if len(rest) <= 1 and all(_is_short_taxonomy(r) for r in rest):
                return NonArticleVerdict("url_taxonomy", f"taxonomy listing under '/{seg}'")

    # 4. Single-segment SECTION landing (a section front, not an article).
    if len(segments) == 1 and segments[0] in _SECTION_WORDS:
        return NonArticleVerdict("url_section", f"section landing '/{segments[0]}'")

    return None  # looks like a real article — keep it


def skip_non_articles_enabled() -> bool:
    """Whether the ingest path drops non-articles (``OO_SKIP_NON_ARTICLES``, default ON). Set it to
    ``0``/``false`` to keep everything (the filter is fully reversible)."""
    return os.getenv("OO_SKIP_NON_ARTICLES", "1").strip().lower() not in ("0", "false", "no", "off")


def run_non_article_selftest() -> dict:
    """Prove the classifier on hand-picked fixtures incl. the recall-gap misses — and, crucially,
    that REAL articles are NOT dropped (the negative space). Deterministic, no I/O, no score."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    # SHOULD be caught (the recall-gap kinds)
    caught = {
        "homepage": "https://deswater.com",
        "utility_downloads": "https://lngjournal.com/index.php/downloads",
        "utility_glossary": "https://www.bmv.com.mx/en/bmv/glossary",
        "taxonomy_tag": "https://nano-magazine.com/news/tag/depression",
        "events_section": "https://nano-magazine.com/events",
        "section_world": "https://www.irishexaminer.com/world/",
        "login": "https://example.com/account/login",
    }
    for name, u in caught.items():
        v = classify_non_article(u, text="short nav text")
        check(f"catches_{name}", v is not None, u)
    check("catches_cookie_wall", classify_non_article(
        "https://site.com/x", text="We use cookies. Please enable JavaScript to continue.",
        word_count=9) is not None)

    # MUST be kept (real articles — the negative space; a false positive drops real content). The
    # body-gate cases (a real article at a bare section / short taxonomy / utility URL) are the
    # load-bearing ones: the SUBSTANTIAL body keeps them despite the non-article URL shape.
    kept = {
        "real_article_slug": "https://www.sydsvenskan.se/varlden/uppgift-ukrainare-atalas-for-nord-stream-sabotage/",
        "article_under_section": "https://www.irishexaminer.com/world/arid-41234567.html",
        "article_under_category": "https://site.com/category/politics/us-supreme-court-upholds-birthright-citizenship",
        "body_gate_bare_section": "https://blog.example.com/business",   # bare section word + full body
        "body_gate_bare_tag": "https://news.com/tag/gaza",               # short taxonomy value + full body
        "body_gate_utility_word": "https://site.com/print",             # utility word + full body
    }
    for name, u in kept.items():
        v = classify_non_article(u, text="A full genuine article body " * 40, word_count=240)
        check(f"keeps_{name}", v is None, f"{u} -> {v}")
    # a long real article that merely MENTIONS a wall phrase is kept (word gate)
    check("keeps_long_article_mentioning_subscribe", classify_non_article(
        "https://site.com/news/real-story-slug",
        text="Long real article. " * 300 + " subscribe to continue was in a quoted banner.",
        word_count=903) is None)
    # but the same bare-section URL with a THIN body (a listing front) is still dropped
    check("drops_thin_bare_section", classify_non_article(
        "https://blog.example.com/business", text="Headline one. Headline two.", word_count=4) is not None)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-non-article-selftest-1",
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Hand-picked URLs/bodies through classify_non_article, both should-catch and "
        "should-KEEP (the negative space), incl. the body-gate cases (a real article at a "
        "non-article-shaped URL is kept because its extracted body is substantial).",
        "caveat": "High-precision by design (a substantial extracted body is always kept) — it will "
        "miss some non-articles (a long consent wall, non-English nav) rather than risk dropping a "
        "real article. Fully reversible via OO_SKIP_NON_ARTICLES.",
    }
