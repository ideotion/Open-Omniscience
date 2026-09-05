"""How often is a banned month token actually part of a date?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. ``configs/stopwords_extra`` bans 82 month forms from the keyword
index, and ``global_stopwords()`` unions every file in that directory regardless of
which one a word lives in, so the ban is LANGUAGE-AGNOSTIC: French ``mars`` hides the
planet Mars in an English article, ``march`` hides the March on Washington, ``may``
hides Theresa May, ``sept`` (French seven) hides nothing useful in English but is gone
there too. The ban exists to suppress DATELINES, which is a real problem; the question
it never answered is how much else it takes with it.

The design of record (docs/design/KEYWORD_TRANSLATION_DISAMBIGUATION_2026-09-05.md
section 5) proposes making the block DATE-AWARE instead of string-level -- drop a month
token only where the date extractor claimed its span -- and says the decision rests on
one number: **how many occurrences of a banned month token fall OUTSIDE any span the
date extractor claims.** If it is small the ban is nearly free and the rework drops down
the queue; if it is large the rework pays for itself. This module measures that number.

It is a MEASUREMENT, not a verdict. It changes nothing, proposes nothing, and produces
counts only -- never a score, never a recommendation.

WHAT IT COUNTS, and what it deliberately does not:

* the vocabulary is derived at runtime from BOTH sources -- the date extractor's own
  month tables intersected with the live stopword union -- so the measured set can never
  drift from either. Adding a month name to one side without the other changes the
  measured set on the next run rather than silently measuring the old one;
* the denominator is UNIGRAM occurrences. The ban's reach is larger: ``extract.py``
  drops an n-gram if ANY of its tokens is a stopword, so ``april ryan`` and ``march on
  washington`` die too and are not counted here. Every "outside" figure below is
  therefore a FLOOR on what the ban deletes, and is reported as one;
* a claimed span means "this text was consumed as a date", which is a larger fact than
  "a date was stored" -- see ``extract_dates_with_spans``. For this question the larger
  fact is the right one: a refused Jalali span was still read as a date;
* the extractor's own recall is imperfect (the recorded CJK-boundary gap; field date
  coverage measured in the 36-52% range), so a dateline the extractor MISSES is counted
  here as "outside". That direction is stated rather than corrected: it makes the
  outside figure an over-estimate of what a date-aware block would newly admit, which is
  the conservative direction for a decision about deleting less.
"""

from __future__ import annotations

import random
import re
from datetime import date
from functools import lru_cache

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analytics.extract import global_stopwords
from src.database.models import Article
from src.timemap.dateextract import (
    _FA_MONTHS,
    _MAX_SCAN,
    _MONTH_LANG_OVERRIDES,
    _MONTHS,
    _TH_MONTHS,
    extract_dates_with_spans,
)

# The default sample. Every article costs one content decrypt plus one cheap regex
# pass; only an article that actually CONTAINS a month token costs a date extraction
# (measured ~120 ms on a field-average 22 KB body), so the sample is dominated by the
# hits rather than by its own size.
DEFAULT_SAMPLE = 400

_SEED = 20260905  # fixed so two runs on one corpus agree; reported in the payload
_ID_SAMPLE_SHOWN = 200  # ids listed for spot-checking; a bound on EXAMPLES, never on a count


@lru_cache(maxsize=1)
def month_vocabulary() -> dict[str, tuple[str, ...]]:
    """Every month name the date extractor knows, mapped to where it knows it from.

    ``global`` = the language-agnostic table; ``gated`` = recognised only under a
    matching language hint; ``thai``/``jalali`` = the two calendar-specific tables.
    A name can appear in more than one.
    """
    vocab: dict[str, set[str]] = {}
    for token in _MONTHS:
        vocab.setdefault(token, set()).add("global")
    for token in _MONTH_LANG_OVERRIDES:
        vocab.setdefault(token, set()).add("gated")
    for token in _TH_MONTHS:
        vocab.setdefault(token, set()).add("thai")
    for token in _FA_MONTHS:
        vocab.setdefault(token, set()).add("jalali")
    return {token: tuple(sorted(where)) for token, where in sorted(vocab.items())}


@lru_cache(maxsize=1)
def banned_month_tokens() -> dict[str, tuple[str, ...]]:
    """The month names the stopword union currently bans, with their provenance.

    Derived from the LIVE stopword union, so it tracks every batch. A month name the
    stoplist does not carry is not measured: it costs the keyword index nothing.
    """
    stops = global_stopwords()
    return {t: where for t, where in month_vocabulary().items() if t in stops}


@lru_cache(maxsize=1)
def _token_re() -> re.Pattern[str]:
    """One alternation over every banned token, longest-first.

    Longest-first matters for the multi-word Arabic names: without it a two-word month
    would be found as its first word alone. The boundary is ``\\w`` on both sides, which
    is Unicode-aware, so an Arabic or Cyrillic token is bounded by its own script's
    letters rather than by ASCII. It is the DIAGNOSTIC's boundary rule, close to but not
    identical to the keyword tokenizer's (which additionally strips Romance elision);
    the difference cannot manufacture an occurrence, only miss an unusual one.
    """
    tokens = sorted(banned_month_tokens(), key=len, reverse=True)
    if not tokens:
        return re.compile(r"(?!x)x")  # matches nothing, and says so plainly
    alt = "|".join(re.escape(t) for t in tokens)
    return re.compile(rf"(?<!\w)({alt})(?!\w)", re.IGNORECASE | re.UNICODE)


def occupancy_for_text(
    text: str,
    *,
    language: str | None = None,
    anchor: date | None = None,
    today: date | None = None,
) -> dict[str, tuple[int, int]]:
    """Per banned token in ``text``: ``(consumed_as_a_date, outside_any_date)``.

    Mirrors the production path exactly -- ``datestore.store_for_article`` feeds the
    extractor the article's own ``language`` and its publication date as ``anchor``, and
    without both the extractor silently runs explicit-dates-only (the 2026-06-16
    anchor/language wiring bug). Passing them is what makes the "consumed" side real;
    omitting them would understate it and push the decision the wrong way.

    Only the first ``_MAX_SCAN`` characters are considered, because that is all the
    extractor looked at. Counting a token beyond that cut as "outside" would fabricate
    an absence out of a bound.
    """
    scanned = text[:_MAX_SCAN] if text else ""
    if not scanned.strip():
        return {}
    hits = [(m.group(1).lower(), m.start(), m.end()) for m in _token_re().finditer(scanned)]
    if not hits:
        return {}
    _, spans = extract_dates_with_spans(
        scanned, today=today, anchor=anchor, language=language, limit=10_000
    )
    out: dict[str, list[int]] = {}
    for token, start, end in hits:
        inside = any(start < ce and cs < end for cs, ce in spans)
        row = out.setdefault(token, [0, 0])
        row[0 if inside else 1] += 1
    return {token: (row[0], row[1]) for token, row in out.items()}


def _sample_ids(session: Session, sample: int) -> tuple[list[int], dict]:
    """Article ids drawn uniformly at random across the observed id range.

    NOT the FTS ranking. ``search_ids`` orders by bm25, so a sample taken from it would
    be dominated by articles where a month token is DENSE -- i.e. datelines-heavy ones
    -- which biases the consumed share upward and the whole decision toward "the ban is
    nearly free". A uniform draw has one stated bias instead: an article sitting just
    after a large gap in the id sequence is over-represented, because each draw takes
    the first article at or above it.
    """
    lo, hi, total = session.query(
        func.min(Article.id), func.max(Article.id), func.count(Article.id)
    ).one()
    basis: dict[str, object] = {"corpus_articles": int(total or 0), "seed": _SEED}
    if not total or lo is None or hi is None:
        return [], basis
    rng = random.Random(_SEED)  # nosec B311 - sampling for a diagnostic, not security
    seen: set[int] = set()
    draws = 0
    # Bounded: a corpus whose ids cluster can need several draws per new article, so the
    # loop stops on attempts as well as on hits and reports both.
    while len(seen) < sample and draws < sample * 8:
        draws += 1
        target = rng.randint(int(lo), int(hi))
        row = (
            session.query(Article.id)
            .filter(Article.id >= target, Article.quarantined.isnot(True))
            .order_by(Article.id)
            .limit(1)
            .first()
        )
        if row is not None:
            seen.add(int(row[0]))
    ids = sorted(seen)
    basis.update({
        "draws": draws,
        "distinct_articles": len(ids),
        # A bounded sample of the sample, so a reader can open the specimens behind any
        # figure below. The list is capped; the COUNT above never is.
        "sampled_article_ids": ids[:_ID_SAMPLE_SHOWN],
        "sampled_article_ids_shown": min(len(ids), _ID_SAMPLE_SHOWN),
    })
    return ids, basis


def month_occupancy_report(
    session: Session,
    *,
    sample: int = DEFAULT_SAMPLE,
    today: date | None = None,
) -> dict:
    """The slice-2 number: how much of the month ban is not about dates.

    Read-only. Counts only, no score, no recommendation -- the report says what was
    measured and how, and the ruling is the maintainer's.
    """
    tokens = banned_month_tokens()
    ids, basis = _sample_ids(session, sample)
    per_token: dict[str, dict] = {}
    per_language: dict[str, list[int]] = {}
    scanned_articles = 0
    articles_with_a_token = 0
    truncated_bodies = 0
    for aid in ids:
        row = (
            session.query(
                Article.content, Article.language, Article.published_at, Article.created_at
            )
            .filter(Article.id == aid)
            .first()
        )
        if row is None:
            continue
        content, language, published_at, created_at = row
        if not (content or "").strip():
            continue
        scanned_articles += 1
        if len(content) > _MAX_SCAN:
            truncated_bodies += 1
        observed = published_at or created_at
        counts = occupancy_for_text(
            content,
            language=language,
            anchor=observed.date() if observed else None,
            today=today,
        )
        if not counts:
            continue
        articles_with_a_token += 1
        base = (language or "").split("-", 1)[0].strip().lower() or "unknown"
        for token, (inside, outside) in counts.items():
            slot = per_token.setdefault(
                token,
                {
                    "known_as_a_month_in": list(tokens.get(token, ())),
                    "articles": 0,
                    "occurrences": 0,
                    "consumed_as_a_date": 0,
                    "outside_any_date": 0,
                    "by_language": {},
                },
            )
            slot["articles"] += 1
            slot["occurrences"] += inside + outside
            slot["consumed_as_a_date"] += inside
            slot["outside_any_date"] += outside
            lang_slot = slot["by_language"].setdefault(base, [0, 0])
            lang_slot[0] += inside
            lang_slot[1] += outside
            agg = per_language.setdefault(base, [0, 0])
            agg[0] += inside
            agg[1] += outside

    for slot in per_token.values():
        slot["by_language"] = {
            lang: {"consumed_as_a_date": c, "outside_any_date": o}
            for lang, (c, o) in sorted(slot["by_language"].items(), key=lambda kv: -sum(kv[1]))
        }
        slot["outside_share"] = _share(slot["outside_any_date"], slot["occurrences"])

    total_in = sum(s["consumed_as_a_date"] for s in per_token.values())
    total_out = sum(s["outside_any_date"] for s in per_token.values())
    return {
        "generated_at": date.today().isoformat(),
        "question": (
            "Of the month names the stoplist bans, how many occurrences were NOT part "
            "of a date the extractor recognised?"
        ),
        "method": (
            "Articles drawn uniformly at random from the corpus id range (quarantined "
            "excluded), each scanned for the banned month vocabulary and, where a token "
            "is present, run through the SAME date extraction the ingest path uses -- "
            "the article's own language and publication date included. An occurrence is "
            "'consumed' when it falls inside a span the extractor claimed."
        ),
        "caveats": [
            "Counts over a bounded random sample, not the whole corpus; every rate "
            "carries its n.",
            "Unigram occurrences only. The ban also deletes every n-gram containing a "
            "banned token, so 'outside_any_date' is a FLOOR on what it costs.",
            "A dateline the extractor MISSES is counted as outside, so the outside "
            "figure over-states what a date-aware block would newly admit.",
            "Only the first "
            f"{_MAX_SCAN:,} characters of a body are scanned, because that is all the "
            "extractor reads.",
            "No score, no ranking, no recommendation: this is a measurement.",
        ],
        "basis": {
            **basis,
            "requested_sample": sample,
            "articles_scanned": scanned_articles,
            "articles_with_a_banned_month_token": articles_with_a_token,
            "bodies_over_the_scan_bound": truncated_bodies,
            "banned_tokens_known": len(tokens),
            "banned_tokens_seen": len(per_token),
        },
        "totals": {
            "occurrences": total_in + total_out,
            "consumed_as_a_date": total_in,
            "outside_any_date": total_out,
            "outside_share": _share(total_out, total_in + total_out),
        },
        "by_language": {
            lang: {
                "consumed_as_a_date": c,
                "outside_any_date": o,
                "outside_share": _share(o, c + o),
            }
            for lang, (c, o) in sorted(per_language.items(), key=lambda kv: -sum(kv[1]))
        },
        "by_token": dict(
            sorted(per_token.items(), key=lambda kv: -kv[1]["occurrences"])
        ),
        "banned_tokens": {t: list(w) for t, w in tokens.items()},
    }


def _share(part: int, whole: int) -> float | None:
    """A share, or ``None`` when there is nothing to divide.

    Never 0.0 for an empty denominator: "no occurrences were seen" and "none of the
    occurrences were outside a date" are opposite findings, and a 0.0 would read as the
    second while meaning the first.
    """
    return round(part / whole, 4) if whole else None
