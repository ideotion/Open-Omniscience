"""
The bulletin-language diagnostic — and the render-integrity checks that ride it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

TWO QUESTIONS, one pass, because both need the same double render of a real
edition:

1. **Would this edition read in the operator's language?** Per locale: how many of
   the sentences this app writes have a translation, which do not, and which have
   a broken one. The missing list is verbatim and complete, so this report IS the
   worklist — hand it back and the gap can be filled without guessing at what the
   renderer asks for.
2. **Does the document say what the record knows?** The renderer has been the
   bottleneck twice: 114 source countries reached a page as 8 with no account of
   the rest, and a story's own articles were added to the record and printed by
   neither renderer. Both were found by reading output, not by a test. These
   checks read the output on every run.

WHY A DIAGNOSTIC AND NOT A TEST. A test runs on fixtures the author chose. This
runs on the operator's newest real edition — the corpus that actually exists, in
the languages actually configured — and it produces a FILE, which is the form a
finding has to take to travel from a field machine back to whoever fixes it.

READ-ONLY AND LOCAL. It renders an already-persisted record: no DB write, no
model, no network. Rendering is what it measures, so it can measure it anywhere.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from src.bulletin.i18n import UI_LANGS, Translator, catalog_path
from src.bulletin.render import render_html, render_markdown

#: How many missing strings the report carries in full. The point is a worklist, so
#: this is generous; the count is always exact even when the list is cut, and the
#: cut is stated rather than left to be inferred from a suspiciously round number.
MAX_LISTED = 400

#: A frame hole that survived into the output means a value never arrived. Only
#: names this renderer actually uses are looked for, so a source's own text
#: containing braces cannot be mistaken for our bug.
_BRACE = re.compile(r"\{([a-z_]+)\}")

_REF = re.compile(r"\[(\d{4,})\]")


# --------------------------------------------------------------------------- #
#  a record to measure when the operator has none yet
# --------------------------------------------------------------------------- #
def sample_edition() -> dict:
    """A synthetic record that reaches every branch of both renderers.

    Deliberately exercised rather than minimal: a sample that omits cards or
    coverage would report full translation coverage for a document half the size
    of a real one — a fabricated pass on strings nobody translated. Every figure
    here is invented and the record says so, so it can never be mistaken for a
    measurement of a corpus.
    """
    article = {
        "id": 1,
        "title": "Sample article title",
        "url": "https://example.org/a",
        "source": {"name": "Example", "domain": "example.org"},
        "asserted": {
            "published_at": "2026-08-05T09:30:00",
            "author": "A. Author",
            "language": "fr",
        },
        "deduced": {
            "word_count": 812,
            "detected_language": "en",
            "sentiment": {"label": "negative", "basis": "VADER, English only"},
            "collected_at": "2026-08-09T18:00:00",
        },
        "keywords": [{"term": "grève", "mentions": 9}],
        "places": [{"name": "Paris"}],
        "entities": [{"name": "Ministry"}],
        "dates": [{"date": "2026-08-04"}],
        "excerpt": "An excerpt of the source's own words.",
        "excerpt_truncated": True,
    }
    return {
        "synthetic": True,
        "note": "A synthetic record for the language diagnostic. No figure here is a measurement.",
        "filename": "sample-edition.json",
        "generated_at": "2026-08-11T12:00:00+00:00",
        "period": {"cadence": "weekly", "start": "2026-08-04", "last_day": "2026-08-10", "days": 7},
        "masthead": {
            "articles": 72225,
            "sources_contributing": 2117,
            "top_3_share": 0.14,
            "days_with_ingest": 7,
            "period_days": 7,
            "corpus_share": 0.09,
            "corpus_articles": 794333,
            "articles_by_day": [{"day": "2026-08-04", "articles": 10}],
            "channels": [{"source_type": "news", "articles": 71381}],
            "languages": [{"language": "fr", "articles": 900}, {"language": None, "articles": 4}],
            "source_countries": [{"country": "fr", "articles": 5402}],
            "source_unlocated_articles": 8445,
            "top_sources": [{"name": "Example", "domain": "example.org", "articles": 12}],
            "caveat": "A country absent here is a country this corpus did not collect from.",
        },
        "sections": [
            {
                "section": "rising_concepts",
                "baseline_days": 30,
                "terms": [
                    {"term": "fission", "recent": 2933, "growth": 1257.0, "growth_is_ratio": True},
                    {"term": "drp1", "recent": 1908, "growth": 1908.0, "growth_is_ratio": False,
                     "prior": 0},
                    {"term": "mito", "recent": 5701, "growth": 5701.0, "growth_is_ratio": False,
                     "prior": 4},
                    {"term": "older", "recent": 12, "growth": 3.0},
                ],
                "caveat": "Many terms are tested at once, so some will rise by chance.",
            },
            {
                "section": "across_channels",
                "terms": [{"term": "grève", "first_seen": "2026-08-05", "channel": "news"},
                          {"term": "tie", "first_seen": "2026-08-06",
                           "channels_tied": ["news", "scientific"]}],
                "channels": [{"provenance": "news", "concepts_first_here": 4}],
            },
            {
                "section": "by_topic_tag",
                "topics": [{"topic": "energy", "articles": 4, "mentions": 40}],
                "mentions_untagged": 12451102,
                "mentions_tagged": 17080,
                "mentions_total": 12468182,
                "caveat": "The untagged count beside it is the rest of the period.",
            },
            {
                "section": "alerts",
                "events": 92,
                "by_event_type": [{"event_type": "earthquake", "events": 40}],
                "by_provider": [{"provider": "usgs", "events": 52}],
                "examples": [{"place": "80 km ESE of Isangel, Vanuatu", "magnitude": 4.8,
                              "severity": "moderate", "event_time": "2026-08-10T08:34:00",
                              "provider": "usgs"}],
                "caveat": "Every field here is what the provider published, never combined.",
            },
            {
                "section": "changes_of_record",
                "law_revisions": 16,
                "law_revisions_flagged": 1,
                "wiki_revisions": 3,
                "wiki_revisions_flagged": 0,
                "law_examples": [{"title": "Data Protection Act", "jurisdiction": "gb",
                                  "observed_at": "2026-08-07", "delta_bytes": 2048,
                                  "flagged": True}],
                "wiki_examples": [{"title": "Fission", "observed_at": "2026-08-08"}],
            },
            {
                "section": "through_time",
                "years": [{"year": 2019, "articles": 3}],
                "window": {"days": 5, "matches_period": False},
            },
            {
                "section": "country_coverage",
                "countries_total": 2,
                "countries_listed": 1,
                "countries": [
                    {
                        "country": "fr",
                        "name": "France",
                        "continent": "Europe",
                        "reading": "covered from inside and from outside",
                        "local": {"articles": 3, "terms": [{"term": "grève", "mentions": 9,
                                                            "articles": 3}]},
                        "international": {"articles": 0, "terms": []},
                    }
                ],
                "continents": [
                    {
                        "continent": "Europe",
                        "countries_contributing": 1,
                        "reading": "covered from inside",
                        "local": {"articles": 3, "terms": [{"term": "grève", "mentions": 9,
                                                            "articles": 3}]},
                        "international": {"articles": 0, "terms": []},
                    }
                ],
                "caveat": "A missing side is a fact about this corpus, never about the world.",
            },
            {
                "section": "cards",
                "producers_run": 39,
                "producers_total": 39,
                "truncated": True,
                "cards_found": 2,
                "card_types": 2,
                "types": [
                    {
                        "type": "echo_chamber",
                        "cards_found": 2,
                        "cards_shown": 1,
                        "cards": [
                            {
                                "title": "Three sources, one wording",
                                # Faithful to what a real producer emits: composed around
                                # live values, so no fixed key can match it. It must reach
                                # the report as PASSTHROUGH, never as a missing translation.
                                "summary": (
                                    "Mentions of “flooding” are running ~3.2× the "
                                    "prior-period rate (18 recent vs 5 before)."
                                ),
                                # This card exercises the label-translatable path; the
                                # reading_diet card below deliberately carries NO pairs, so
                                # the pre-signal_pairs fallback is exercised too — a fixture
                                # where both cards had pairs could not tell them apart.
                                "signal_pairs": [["distinct sources", "3"], ["articles", "9"]],
                                "signal_line": "distinct sources 3 · articles 9",
                                "n": 3,
                                "bucket": "overtold",
                                "method": "MinHash over stored keywords.",
                                "caveat": "Absence of a flag is not absence of coordination.",
                                "corpus_articles": 9,
                                "article_rows": [article],
                            }
                        ],
                    },
                    {
                        "type": "reading_diet",
                        "cards_found": 1,
                        "cards_shown": 1,
                        "cards": [
                            {
                                "title": "Your reading leans on a few sources",
                                # NO signal_pairs on purpose: this is the shape of an
                                # edition written before pairs existed, so the fallback is
                                # exercised on every run rather than only in a unit test.
                                "signal_line": "top three share 0.14 · sources 21",
                                "corpus_articles": 0,
                                "method": "A whole-corpus distribution.",
                            }
                        ],
                    },
                ],
                "window": {"days": 7, "matches_period": False},
                "caveat": "AS OBSERVED WHEN THIS EDITION WAS GENERATED.",
            },
            {"section": "skipped_example", "skipped": "no data in this period"},
            {"section": "broken_example", "error": "ValueError: synthetic"},
        ],
        "stories": {
            "stories": [
                {
                    "shared_terms": ["alerta", "vientos"],
                    "articles": 115,
                    "distinct_sources": 4,
                    "article_rows": [article],
                    "narration": {
                        "text": "A deterministic sentence composed from the cluster's own counts.",
                        "narrated": False,
                        "fallback_reason": "no model was reachable",
                    },
                },
                {
                    "shared_terms": ["solo"],
                    "articles": 2,
                    "distinct_sources": 1,
                    "single_source": True,
                    "narration": {"text": "A model paragraph.", "narrated": True, "partial": True},
                },
            ],
            "caveat": "A cluster is a lexical grouping, never a claim that one event occurred.",
        },
        "ai_worklist": {
            "jobs": [
                {
                    "what": "One grounded paragraph per story cluster",
                    "units": 2,
                    "calls": 2,
                    "corpora": [{"label": "alerta, vientos", "articles": 115}],
                    "adds": "A paragraph under each story, grounded in its own articles.",
                    "if_skipped": "Each story keeps the deterministic sentence.",
                },
                {
                    "what": "Translate articles into the target language",
                    "units": 1,
                    "calls": 1,
                    "articles_total": 3,
                    "already_done": 1,
                    "already_in_target": 1,
                    "language_unknown": 1,
                    "adds": "A translation stored beside each article.",
                    "if_skipped": "Articles stay in their own language.",
                },
            ],
            "calls_total": 3,
            "duration": {"known": False, "reason": "No per-call latency has been measured here."},
            "caveat": "A plan is not a measurement of what a model will produce.",
        },
        "selection": {"sections_shown": 8, "sections_total": 10, "stories_shown": 2,
                      "stories_total": 8},
        "disclosures": {
            "quarantined_in_period": 12,
            "mentions_without_a_date": 4,
            "reindex_backlog": {"available": True, "articles_pending": 7},
            "baseline_coverage": {"complete": False, "note": "The baseline window is partial."},
        },
        "method": "Counts come from stored keyword mentions over the period.",
        "caveat": "Every figure describes THIS corpus, never the world.",
    }


# --------------------------------------------------------------------------- #
#  does the document say what the record knows
# --------------------------------------------------------------------------- #
def render_integrity(edition: dict, *, lang: str = "en") -> dict:
    """Read the rendered output back and check it against the record.

    Every check answers a question a reader of the document would have, and each
    one is reported with what it found rather than as a bare pass — a check that
    says only "ok" cannot be audited.
    """
    t1 = Translator(lang)
    md = render_markdown(edition, tr=t1)
    md_again = render_markdown(edition, tr=Translator(lang))
    html = render_html(edition, tr=Translator(lang))

    # 1. Determinism. A record renders to one document; if it does not, no figure
    #    in it can be quoted, because the next render may say something else.
    deterministic = md == md_again

    # 2. A frame hole that reached the reader. The names come from the FRAMES the
    #    render declared, never from the output: a set derived from the output would
    #    contain every brace in it and could therefore exclude nothing, which would
    #    turn a source that publishes "{x}" in a headline into a report of our bug.
    ours = t1.frame_holes()
    unresolved = sorted({n for n in _BRACE.findall(md) if n in ours})

    # 3. Sections. Each one in the record must be findable in the document — the
    #    render-drops-the-record failure, checked against output rather than trusted.
    missing_sections = []
    for section in edition.get("sections") or []:
        head = str(section.get("section", "")).replace("_", " ").capitalize()
        if head and t1.t(head) not in md:
            missing_sections.append(section.get("section"))

    # 4. Article rows. A record that names articles and a document that does not is
    #    exactly the defect that shipped: a 115-article cluster arrived as a count.
    titles = _article_titles(edition)
    unnamed = [t for t in titles if t and t not in md]

    # 5. References. Every number printed must be one the numberer assigned, or a
    #    reader following it into the annexes opens the wrong article or none.
    from src.bulletin.annexes import assign_refs

    known = {row["ref"] for row in assign_refs(edition)}
    printed = set(_REF.findall(md))
    dangling = sorted(printed - known)

    # 6. The word "None" reaching a reader. Reported as a SUSPICION with its
    #    context, never as a verdict: a source's own title may contain it.
    none_hits = [
        line.strip()[:160]
        for line in md.splitlines()
        if re.search(r"(?<![A-Za-z])None(?![A-Za-z])", line)
    ]

    return {
        "language": t1.lang,
        "markdown_bytes": len(md.encode("utf-8")),
        "html_bytes": len(html.encode("utf-8")),
        "deterministic": deterministic,
        "unresolved_placeholders": unresolved,
        "sections_in_record": len(edition.get("sections") or []),
        "sections_missing_from_document": missing_sections,
        "articles_named_in_record": len(titles),
        "articles_not_printed": unnamed[:20],
        "articles_not_printed_total": len(unnamed),
        "references_printed": len(printed),
        "references_assigned": len(known),
        "dangling_references": dangling,
        "suspicious_none_lines": none_hits[:10],
        "suspicious_none_total": len(none_hits),
        "method": (
            "The record is rendered twice and the output is read back. A section, an "
            "article title or a reference number present in the record and absent from "
            "the document is reported by name. The 'None' lines are a suspicion, not a "
            "verdict: a source's own title may legitimately contain the word."
        ),
    }


def _article_titles(edition: dict) -> list[str]:
    """Every article title the record names, wherever it sits.

    A walk rather than a list of known places: the record has grown article rows
    under cards and under stories at different times, and an enumeration would go
    stale exactly when a new home is added — which is how they went unprinted once.
    """
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "article_rows" and isinstance(value, list):
                    for row in value:
                        if isinstance(row, dict) and row.get("title"):
                            out.append(str(row["title"]))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(edition)
    # Deduped, order kept: one article cited twice is one title to look for.
    seen: dict[str, None] = {}
    for title in out:
        seen.setdefault(title, None)
    return list(seen)


class _AnsweredIdentically(dict):
    """A catalog that answers every sentence with the English itself.

    Used ONLY to discover which sentences exist — never to measure anything. The
    answer keeps every ``{hole}`` by being the frame, so no frame is refused, and it
    satisfies BOTH "nothing is missing" and "something is spelled the same", which
    is what makes one probe enough to reach every complete-catalog branch.

    A probe answering everything DIFFERENTLY was written and then removed: measured
    against this renderer it reached nothing the identical one does not, because the
    branches it could reach turn on the count of answered sentences, which an
    identical answer also increments. Recorded so it is not re-added as insurance —
    a probe that discovers nothing still costs a render per locale, and one kept
    "just in case" reads as a mechanism when it is not one.
    """

    def get(self, key: Any, default: Any = None) -> str:  # type: ignore[override]
        return str(key)


def _strings_behind_a_full_catalog(edition: dict, code: str) -> list[str]:
    """The sentences this edition asks for only once nothing is missing.

    THE BUG THIS EXISTS FOR: a run against an empty catalog cannot see a sentence
    that appears only when the catalog is good. ``Translator.disclosure`` is exactly
    that — it prints "this edition was written in X" when nothing is missing and a
    shortfall line otherwise — so the stub built from one such run was permanently
    one string short, and the string it omitted was a caveat, the class the
    informed-consent rule requires in every locale. A translator who filled the stub
    perfectly was then told they had missed one.

    The complement is NOT rendered here: the sentences a partial catalog reaches are
    already the caller's ``missing`` list, measured on the real catalog, so re-rendering
    that regime would cost a render per locale and discover nothing. The two halves are
    unioned at the call site, where both are visible.

    THE LIMIT, stated rather than implied: one probe reaches every branch that turns on
    the KIND of answer, because an identical answer satisfies both "nothing is missing"
    and "something is spelled the same". A branch on WHICH sentence was answered would
    escape it. None exists today, and a new one would surface as a string the report
    names as missing while the stub does not offer it — the same shape as the defect
    above, so the same test guards it.
    """
    T = Translator(code)
    if not T.is_english:
        T.catalog = _AnsweredIdentically()
    render_markdown(edition, tr=T)
    # An answered run has no gap to read, so take the sentences it SAW.
    return T.seen()


# --------------------------------------------------------------------------- #
#  the report
# --------------------------------------------------------------------------- #
def language_report(edition: dict, *, langs: tuple[str, ...] | None = None) -> dict:
    """Per-locale translation coverage for ONE edition, plus its integrity checks."""
    codes = tuple(langs or UI_LANGS)
    per_language = []
    for code in codes:
        T = Translator(code)
        md = render_markdown(edition, tr=T)
        rep = T.report()
        listed = rep.pop("missing_strings")
        rep["missing_listed"] = listed[:MAX_LISTED]
        rep["missing_truncated"] = max(0, len(listed) - MAX_LISTED)
        # The skeleton an author fills in. Emitting it means nobody has to derive
        # the renderer's own vocabulary by reading the renderer.
        #
        # Built from what this edition can REACH, not only from what this run lacked:
        # a sentence that appears only once the catalog is good is missing from the
        # second list by construction, so filling the stub used to leave a gap the next
        # report would then report. The two halves are unioned HERE so both are visible:
        # ``listed`` is what a partial catalog reaches, measured on the real catalog, and
        # the probe is what a full one reaches. ``missing`` above is untouched — it is a
        # measurement of THIS catalog and must stay one.
        #
        # English is the SOURCE and owes no worklist: its catalog is empty by
        # definition, so an unguarded probe would offer every sentence in the document
        # as English-to-translate-into-English.
        gap = (
            []
            if T.is_english
            else [
                s
                for s in _strings_behind_a_full_catalog(edition, code)
                if s not in T.catalog and s not in set(listed)
            ]
        )
        rep["catalog_stub"] = {s: "" for s in (listed + gap)[:MAX_LISTED]}
        # Reachable-but-not-missing entries exist only when a sentence lives behind a
        # branch this run did not take, so a reader can tell the stub is deliberately
        # larger than the gap rather than double-counting.
        rep["stub_beyond_missing"] = len(gap)
        rep["catalog_file"] = str(catalog_path(code))
        rep["sample"] = _sample_lines(md)
        rep["disclosure"] = T.disclosure()
        per_language.append(rep)

    integrity = render_integrity(edition)
    covered = [r for r in per_language if r["coverage"] is not None]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "edition": {
            "filename": edition.get("filename"),
            "generated_at": edition.get("generated_at"),
            "cadence": (edition.get("period") or {}).get("cadence"),
            "synthetic": bool(edition.get("synthetic")),
            "articles": (edition.get("masthead") or {}).get("articles"),
        },
        "strings_in_document": integrity.get("markdown_bytes") and per_language[0]["strings_seen"],
        "languages": per_language,
        # TWO different questions, because one word cannot answer both honestly.
        #
        # COMPLETE asks the worklist question: does every sentence the renderer asked
        # for have an entry? That is the one a translator finishes. It deliberately
        # does NOT require coverage 1.0, because some entries are legitimately
        # identical to the English — "Asia" in Spanish, "cyclone" in French — so a
        # genuinely finished catalog can never reach 1.0 and would otherwise be filed
        # under "started" forever, which reads as unfinished work that does not exist.
        #
        # FULLY_TRANSLATED is the stricter form: every entry also DIFFERS from the
        # English. It is rarely reachable for a real language and is kept because it
        # is what stops a catalog of copied English reporting itself done — such a
        # catalog appears under complete, with identical_to_english equal to its size
        # and coverage 0.0 printed beside it, so the copy is visible rather than
        # counted as work. Neither list is a substitute for reading those two numbers.
        "complete": sorted(
            r["language"] for r in covered if not r["missing"] and not r["rejected"]
        ),
        "fully_translated": sorted(
            r["language"] for r in covered if r["coverage"] == 1.0 and not r["rejected"]
        ),
        # An empty ``fully_translated`` beside a full ``complete`` is the one pairing a
        # reader can misread, and the explanation above lives in the source rather than
        # in the file they downloaded. So it is published as DERIVED data: the count of
        # identical entries per complete locale, which is both the reason the stricter
        # list is empty and the number to check that reason against. Computed, never a
        # static sentence, because a static one would keep claiming this after someone
        # translated the last copied entry and made the strict list reachable.
        "identical_in_complete": {
            r["language"]: r["identical_to_english"]
            for r in covered
            if not r["missing"] and not r["rejected"] and r["identical_to_english"]
        },
        # Genuinely partial: something is translated AND something is still missing.
        # A complete catalog is not "started"; an empty one is not either.
        "started": sorted(
            r["language"]
            for r in covered
            if 0 < (r["coverage"] or 0) < 1.0 and r["missing"]
        ),
        "not_started": sorted(
            r["language"] for r in covered if not r["catalog_entries"] and r["language"] != "en"
        ),
        "render_integrity": integrity,
        "how_to_use": (
            "Each locale's catalog_stub is the file to fill in at catalog_file: the keys are "
            "the sentences this renderer asked for and had no translation of. A frame with "
            "{named} holes must keep every hole, in any order — one that loses a hole is "
            "refused at render time and reported under rejected_strings rather than printed. "
            "Words quoted from sources are never in this list: they are data, and translating "
            "an article is the separate, model-assisted step the bulletin offers as phase 2. "
            "Neither are the sentences counted under passthrough: a producer composed those "
            "around live values, so a catalog entry for one would only ever match a corpus "
            "with the same numbers in it. They are printed in English, excluded from "
            "coverage, and fixed upstream by giving the producer a keyable frame — the "
            "coverage figure is therefore a share of what CAN be translated, not of the "
            "whole document."
        ),
    }


#: Record keys whose value is prose THIS APP wrote and the renderer prints verbatim.
#: Not a guess at what looks like prose: these are the fields ``render.py`` passes
#: through ``Translator.t``, so the two lists are the same seam read from two ends.
_PROSE_KEYS = frozenset(
    {
        "caveat", "method", "reading", "note", "adds", "if_skipped", "what",
        "reason", "skipped", "summary", "signal_line",
    }
)

_PROSE_MIN = 25


def stored_prose(*, packages: tuple[str, ...] = ("bulletin",)) -> dict[str, list[str]]:
    """The prose the computing modules WRITE INTO a record, harvested from source.

    A rendered edition cannot exhibit all of it — a period with no alert never
    carries the alert caveat, a corpus with no story never carries the story one —
    so measuring translation coverage by rendering alone would report a document
    complete while half its possible sentences had no entry. This reads the seam
    from the other end: every string literal assigned to one of the record keys the
    renderer translates.

    Static, so it names sentences no corpus on this machine happens to produce. It
    is a floor rather than a total: a caveat composed at runtime from two halves is
    two literals here and one sentence in the document, and the language report says
    so rather than implying the list is exhaustive.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    found: dict[str, list[str]] = {}
    for pkg in packages:
        for path in sorted((root / pkg).glob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            hits: list[str] = []
            for node in ast.walk(tree):
                # {"caveat": "…"} and Card(caveat="…") — the two ways this tree
                # attaches prose to a record.
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values, strict=False):
                        if (
                            isinstance(key, ast.Constant)
                            and key.value in _PROSE_KEYS
                            and isinstance(value, ast.Constant)
                            and isinstance(value.value, str)
                            and len(value.value) >= _PROSE_MIN
                        ):
                            hits.append(value.value)
                elif isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if (
                            kw.arg in _PROSE_KEYS
                            and isinstance(kw.value, ast.Constant)
                            and isinstance(kw.value.value, str)
                            and len(kw.value.value) >= _PROSE_MIN
                        ):
                            hits.append(kw.value.value)
                elif isinstance(node, ast.Assign):
                    # Module constants named for what they are: _CAVEAT, _METHOD…
                    names = {
                        t.id for t in node.targets if isinstance(t, ast.Name)
                    }
                    if any(("CAVEAT" in n or "METHOD" in n) for n in names) and isinstance(
                        node.value, ast.Constant
                    ):
                        if isinstance(node.value.value, str) and len(node.value.value) >= _PROSE_MIN:
                            hits.append(node.value.value)
            if hits:
                seen: dict[str, None] = {}
                for h in hits:
                    seen.setdefault(h, None)
                found[f"{pkg}/{path.name}"] = list(seen)
    return found


def _sample_lines(md: str, *, n: int = 12) -> list[str]:
    """A short readable excerpt, so a reviewer can judge the tone without the file."""
    out = []
    for line in md.splitlines():
        s = line.strip()
        if len(s) > 24 and not s.startswith(("|", "---")):
            out.append(s[:200])
        if len(out) >= n:
            break
    return out


def bulletin_language_report(*, edition: dict | None = None, langs: tuple[str, ...] | None = None) -> dict:
    """The report for the operator's newest real edition, or for the sample.

    A machine with no edition yet still gets a full answer — the mechanism and the
    catalogs can be reviewed before a first bulletin exists — and the report says
    which it measured, because coverage over a synthetic record is a statement
    about the renderer and coverage over a real one is a statement about a corpus.
    """
    record = edition
    source = "supplied"
    if record is None:
        try:
            from src.bulletin.store import list_editions, read_edition

            rows = list_editions()
            if rows:
                record = read_edition(rows[0]["filename"])
                source = f"newest persisted edition ({rows[0]['filename']})"
        except Exception:  # noqa: BLE001 — a missing store is a normal state here
            record = None
    if record is None:
        record = sample_edition()
        source = "synthetic sample (no persisted edition found)"
    out = language_report(record, langs=langs)
    out["measured"] = source
    return out


def run_bulletin_language_selftest() -> dict:
    """Prove the mechanism on the synthetic record, with no DB and no catalog needed.

    Checks the FOUR properties the layer rests on, each stated as what it found:
    English is untouched, a missing translation falls back and is reported, a frame
    whose holes were changed is refused, and a copied-English entry is not counted
    as coverage.
    """
    edition = sample_edition()
    en = Translator("en")
    render_markdown(edition, tr=en)
    en_report = en.report()

    probe = Translator("zz")  # a locale with no catalog, by construction
    probe.catalog = {
        "Stories": "Stories",  # identical: legitimate, but not coverage
        "{cadence} bulletin — {start} to {end}": "{cadence} bulletin from {start}",  # a lost hole
        "References": "Referencias",  # a real translation
    }
    md = render_markdown(edition, tr=probe)
    rep = probe.report()

    checks = {
        # NOT "or language == en", which an earlier draft of this line had: that clause
        # is true for every English report, so the whole check could not fail. English
        # is the SOURCE language, so its report says nothing is missing and there is no
        # ratio — not-applicable rather than nought per cent.
        "english_reports_no_gap_and_no_ratio": (
            en_report["missing"] == 0
            and en_report["coverage"] is None
            and en_report["rejected"] == 0
        ),
        "english_seen_is_counted": en_report["strings_seen"] > 50,
        "a_real_translation_is_used": "Referencias" in md,
        "a_broken_frame_is_refused": any(
            "placeholders differ" in r["reason"] for r in rep["rejected_strings"]
        ),
        "a_refused_frame_renders_english": "bulletin — 2026-08-04 to 2026-08-10" in md,
        "an_identical_entry_is_not_coverage": rep["identical_to_english"] >= 1
        and "Stories" not in {s for s in rep["missing_strings"]},
        "a_gap_is_reported": rep["missing"] > 0,
    }
    integrity = render_integrity(edition)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "passed": all(checks.values()),
        "strings_in_sample_document": en_report["strings_seen"],
        "render_integrity": integrity,
        "method": (
            "A synthetic record is rendered in English and again through a hand-built "
            "catalog holding one real translation, one entry copied from the English and "
            "one frame with a hole removed. No database, no catalog file and no model are "
            "involved, so this runs anywhere the app does."
        ),
    }
