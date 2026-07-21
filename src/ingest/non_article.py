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
    genuine article at ``/business``, ``/category/politics`` or ``/tag/gaza`` is never dropped...
    UNLESS the PROSE GATE fires (below): word-RICH nav soup can clear this word-count guard too.
  * Only for a THIN body do the URL-shape / wall rules fire — the drop condition is (thin body) AND
    (a non-article URL shape OR a definitive wall phrase), which is what makes it high-precision.
  * Every rule is EXPLICIT; the classifier returns the first matching rule with a disclosed REASON +
    signal, never a fuzzy score.

THE PROSE GATE (NAV-SOUP SPECIMEN ruling, maintainer field specimen 2026-07-20: the Irish Mirror
``newsletter-preference-centre`` page stored as an Article) closes the recall gap the load-bearing
guard above otherwise leaves open: a body can be WORD-RICH (>= ``_ARTICLE_MIN_WORDS``) and still be
pure nav/menu chrome, not prose — the specimen was ~135 words of nothing but menu items. For a
body at/above the guard, :func:`src.services.prose_gate.prose_gate_verdict` runs an AND-gated check
(low function-word density of the asserted/best-matching language AND near-zero sentence-ending
punctuation — either alone is not enough, precision-serving exactly like the rest of this module)
and returns a ``nav_soup`` verdict only when BOTH are true. Script-aware (an unsegmented zh/ja/th
body is never judged — unmeasurable text is never dropped on a gap) and conservative by
construction (a headline-list page deliberately escapes; that undercount is the source-level
auditor's territory, not this gate's job — see ``src/analytics/source_audit.py``).

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

from src.services.prose_gate import prose_gate_verdict

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
    language: str | None = None,
) -> NonArticleVerdict | None:
    """Return a verdict if ``url``/``text`` is CLEARLY a non-article, else ``None`` (keep it).

    A SUBSTANTIAL extracted body (``>= _ARTICLE_MIN_WORDS``) is a real article — kept regardless of
    URL, UNLESS the PROSE GATE fires on it (word-rich nav soup; see the module docstring). Only a
    THIN body proceeds to the wall / URL rules (order: boilerplate wall → utility path → pagination
    → taxonomy listing → homepage → section landing). Conservative — when in doubt, keep.
    ``language`` is the asserted/detected article language, if known (passed through to the prose
    gate's best-matching-language search; optional, additive)."""
    wc: int | None = word_count if word_count is not None else (len(text.split()) if text else None)

    # THE guard: a real article has a substantial extracted body — keep it whatever the URL shape,
    # UNLESS the PROSE GATE (below) catches word-rich nav soup that cleared this word-count floor.
    # A nav/index/tag/section/wall page normally yields only a thin body; only THAT then proceeds
    # to the URL/wall rules below. The prose gate needs the actual body text — with text=None (the
    # retroactive URL-shape-only scan) it never fires, so that scan's behavior is unchanged.
    if wc is not None and wc >= _ARTICLE_MIN_WORDS:
        if text:
            prose_verdict = prose_gate_verdict(text, language=language)
            if prose_verdict is not None:
                return NonArticleVerdict(prose_verdict.signal, prose_verdict.reason)
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

    # THE PROSE GATE (NAV-SOUP SPECIMEN ruling 2026-07-20): a body that CLEARS the word-count
    # guard above can still be pure nav/menu chrome (the Irish Mirror newsletter-preference-centre
    # specimen, ~135 words of nothing but menu items). This is the recall gap the gate closes.
    nav_soup_body = (
        "News Latest Irish News Mirror Bingo Soccer Golf Rugby Union Sport Business Politics "
        "World News Travel Money Markets Weather Video Photos Gallery Podcast Newsletters Events "
        "About Contact Home Search Login Sign Up Subscribe Cookies Advertisement Privacy Terms "
        "Follow Facebook Twitter Instagram Newsletter Preference Centre Manage Subscriptions "
        "Menu Toggle Navigation Skip Content Latest News Sport GAA Rugby Soccer Racing Golf Boxing "
        "Motors Showbiz TV Fashion Beauty Food Recipes Property Travel Family Voucher Codes Bingo "
        "Dating Contact Advertise Cookie Policy Privacy Policy Terms Conditions Modern Slavery "
        "Statement Complaints Regulation Archive Sitemap Jobs Shop Weddings Announcements Obituaries "
        "Horoscopes Puzzles Crosswords Competitions Vouchers Discounts Deals Reviews Betting Casino "
        "Lottery Results Traffic Cameras Roadworks Bus Times Train Times Flight Tracker Currency "
        "Converter Recipes Wine Beer Cocktails Restaurants Bars Nightlife Theatre Cinema Music Books"
    )
    v = classify_non_article(
        "https://www.irishmirror.ie/all-about/newsletter-preference-centre",
        text=nav_soup_body, word_count=len(nav_soup_body.split()), language="en",
    )
    check("catches_word_rich_nav_soup_specimen", v is not None and v.signal == "nav_soup", str(v))
    # the real-article negative space is NOT newly caught by the gate (real prose has both a
    # healthy function-word density and real sentence punctuation) -- re-run the SAME "kept" URLs
    # above, this time with text= so the prose gate actually runs (the loop above uses a body with
    # no periods; ARTICLE_TEXT-shaped real prose with periods is the load-bearing negative space).
    real_prose_body = "A full genuine article body with real sentences, written like a person. " * 30
    for name, u in kept.items():
        v = classify_non_article(u, text=real_prose_body, word_count=len(real_prose_body.split()))
        check(f"prose_gate_keeps_{name}", v is None, f"{u} -> {v}")
    # a headline-list page deliberately escapes the gate (undercount by design, not this gate's job)
    headlines_body = (
        "Storm warning issued for the coast. Markets fall on rate fears. Council votes on new "
        "budget plan. Local team wins the regional final. Weather turns colder into the weekend. "
    ) * 3
    check("prose_gate_headline_list_escapes", classify_non_article(
        "https://site.com/news/roundup", text=headlines_body,
        word_count=len(headlines_body.split())) is None)
    # an unsegmented script (zh) is never dropped on a measurement gap, even word-rich
    zh_nav = "中国新闻体育财经" * 20
    check("prose_gate_skips_unsegmented_script", classify_non_article(
        "https://site.cn/x", text=zh_nav, word_count=len(zh_nav), language="zh") is None)
    # a MANAGED language with NO grammar vocabulary (sr -- keyword extraction works, sources are
    # enabled, but get_grammar_stopwords('sr') is empty) must never be dropped either: a sparse-
    # punctuation results/listicle article in that language is a REAL ARTICLE shape, and scoring
    # it as density 0.0 would silently degrade the AND-gate to punctuation-only.
    sr_article = ("Rezultati Utakmica Fudbal Kosarka Odbojka Tenis Rukomet Vaterpolo Atletika "
                 "Plivanje ") * 12
    check("prose_gate_skips_uncovered_managed_language", classify_non_article(
        "https://example.rs/sport/rezultati", text=sr_article,
        word_count=len(sr_article.split()), language="sr") is None)
    # Code-review finding (2026-07-20 re-review): the same sr article, but with NO language
    # asserted at all -- the shape the real ingest call site (src/ingest/pipeline.py) actually
    # exercises, since doc.language is only populated when trafilatura's detector fires. Must be
    # kept for the same reason (unmeasurable, not nav-soup evidence), not just when sr is asserted.
    check("prose_gate_skips_uncovered_managed_language_untagged", classify_non_article(
        "https://example.rs/sport/rezultati", text=sr_article,
        word_count=len(sr_article.split()), language=None) is None)

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
        "non-article-shaped URL is kept because its extracted body is substantial) and the PROSE "
        "GATE cases (word-rich nav soup clearing that same body-length guard is still caught, "
        "while real prose at the SAME non-article-shaped URLs is not newly caught).",
        "caveat": "High-precision by design (a substantial extracted body is kept unless the prose "
        "gate's AND-gate both fires) — it will miss some non-articles (a long consent wall, a "
        "headline-list page, non-English nav without a matching stoplist) rather than risk dropping "
        "a real article. Fully reversible via OO_SKIP_NON_ARTICLES.",
    }
