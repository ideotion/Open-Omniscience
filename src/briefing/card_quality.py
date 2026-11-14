"""Card quality checks -- the deterministic half of the card improvement loop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS IS (maintainer-asked 2026-11-14, Lane X): «a self recurring quality check and
optimization workflow of the cards». The loop is: the operator presses the ONE Field data
button, which saves ``oo-field-cards-*.zip`` (``POST /api/diagnostics/field-cards``) beside
the source files; the file is handed back; ``scripts/card_quality_report.py`` runs these same
checks over it, ranks the findings and compares them with the previous file; the findings
become fixes; the next file shows whether they worked.

ONE IMPLEMENTATION, TWO CALLERS. The app runs :func:`self_check` after every Home refresh
(``service._refresh_briefing``) and keeps a short history the field file carries; the script
runs :func:`quality_report` offline. Both call the same functions, so a check cannot mean one
thing in the app and another in the report.

STDLIB ONLY, ON PURPOSE. The script loads this file by path (``importlib``), without importing
``src.briefing`` (whose ``__init__`` pulls the database layer), so the report runs on a returned
file with nothing but Python installed. Keep it that way: no ``src`` import in this module.

HONESTY RULES IT HOLDS ITSELF TO
--------------------------------
* A check that could not be applied to a card is NOT a pass: :func:`direction_check` answers
  ``None`` (not checkable) when the card carries no pair of figures to compare, and the report
  counts those separately.
* NO SCORE. Findings are listed and counted per check; there is no blended quality number, no
  per-card grade, and the ranking is a disclosed sort (severity, then how many cards a check
  hit), never a weighting.
* NO MEASURED ACCURACY FIGURE IS CLAIMED. These checks find inconsistencies inside a card and
  between a card and its own evidence; they say nothing about whether the world matches the
  card, and the report says so.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

SCHEMA = "oo-card-quality-1"
COMPARE_SCHEMA = "oo-card-quality-compare-1"
SELF_CHECK_SCHEMA = "oo-card-selfcheck-1"

HIGH, MEDIUM, LOW, INFO = "high", "medium", "low", "info"
_SEVERITY_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3}

#: Every check this module can raise, with its dimension, severity and one plain sentence.
#: The report prints this table, so a reader never has to open the code to know what a
#: check id means. ``cheap`` checks run in the app after each refresh; the others need the
#: evidence rows only the field file carries. ``arithmetic_failed`` runs wherever the caller hands
#: in the app's own recomputation of the trigger math (the app and the field file both do).
CHECKS: dict[str, dict[str, Any]] = {
    "direction_mismatch": {
        "dimension": "accuracy", "severity": HIGH, "cheap": True,
        "what": "The words say rising (or falling) but the card's own figures move the other way.",
    },
    "arithmetic_failed": {
        "dimension": "accuracy", "severity": HIGH, "cheap": True,
        "what": "A 'Why am I seeing this?' math row was recomputed and did not give the value shown.",
    },
    "non_finite_figure": {
        "dimension": "accuracy", "severity": HIGH, "cheap": True,
        "what": "A figure in the card is NaN or infinite, or was replaced by null because it was.",
    },
    "negative_count": {
        "dimension": "accuracy", "severity": HIGH, "cheap": True,
        "what": "A figure named as a count (articles, sources, mentions, n) is below zero.",
    },
    "n_mismatch": {
        "dimension": "accuracy", "severity": MEDIUM, "cheap": True,
        "what": "The card's n differs from the number of articles it links to.",
    },
    "evidence_missing_articles": {
        "dimension": "accuracy", "severity": HIGH, "cheap": False,
        "what": "Some article ids behind the card no longer exist in the corpus.",
    },
    "evidence_quarantined": {
        "dimension": "accuracy", "severity": MEDIUM, "cheap": False,
        "what": "Some articles behind the card are quarantined (screened as not-an-article).",
    },
    "unfilled_template": {
        "dimension": "honesty", "severity": HIGH, "cheap": True,
        "what": "A title or summary still shows a {placeholder}: a frame was not filled.",
    },
    "caveat_missing": {
        "dimension": "honesty", "severity": HIGH, "cheap": True,
        "what": "The card has no caveat.",
    },
    "method_missing": {
        "dimension": "honesty", "severity": HIGH, "cheap": True,
        "what": "The card has no method.",
    },
    "date_missing": {
        "dimension": "honesty", "severity": MEDIUM, "cheap": True,
        "what": "The card carries no computed-at date.",
    },
    "n_missing": {
        "dimension": "honesty", "severity": LOW, "cheap": True,
        "what": "The card states no n and links no articles, so its sample size is not shown.",
    },
    "feed_incomplete": {
        "dimension": "honesty", "severity": MEDIUM, "cheap": True,
        "what": "The last refresh stopped early, or kept the previous feed; Home says so.",
    },
    "feed_old": {
        "dimension": "honesty", "severity": MEDIUM, "cheap": True,
        "what": "The feed on Home was computed more than 7 days before this check.",
    },
    "empty_text": {
        "dimension": "usefulness", "severity": HIGH, "cheap": True,
        "what": "The card has an empty title or summary.",
    },
    "trivial_signal": {
        "dimension": "usefulness", "severity": MEDIUM, "cheap": True,
        "what": "The card is about nothing: its n, or its count figure, is zero.",
    },
    "duplicate_title": {
        "dimension": "usefulness", "severity": MEDIUM, "cheap": True,
        "what": "Two or more cards show the same title.",
    },
    "near_identical": {
        "dimension": "usefulness", "severity": LOW, "cheap": True,
        "what": "Two cards of the same kind are about nearly the same things (overlap 0.8 or more of the words filled into their templates).",
    },
    "same_articles": {
        "dimension": "usefulness", "severity": LOW, "cheap": True,
        "what": "Two different cards are built from nearly the same articles (overlap 0.9 or more, 3+ articles).",
    },
    "too_long": {
        "dimension": "usefulness", "severity": LOW, "cheap": True,
        "what": "A title over 120 characters or a summary over 400: hard to read at a glance.",
    },
    "no_evidence_link": {
        "dimension": "usefulness", "severity": LOW, "cheap": True,
        "what": "The card links no article and no evidence row, so it cannot be opened onto its corpus.",
    },
    "producer_stopped": {
        "dimension": "performance", "severity": HIGH, "cheap": True,
        "what": "A producer ran past its time bound and its cards were left out.",
    },
    "producer_error": {
        "dimension": "performance", "severity": HIGH, "cheap": True,
        "what": "A producer raised an error during the refresh.",
    },
    "producer_slow": {
        "dimension": "performance", "severity": MEDIUM, "cheap": True,
        "what": "A producer took 60 s or more.",
    },
    "kind_never_seen": {
        "dimension": "coverage", "severity": INFO, "cheap": True,
        "what": "A registered producer made no card in this feed (quiet, disabled, stopped or failing).",
    },
}

TITLE_MAX_CHARS = 120
SUMMARY_MAX_CHARS = 400
SLOW_PRODUCER_S = 60.0
FEED_OLD_DAYS = 7
NEAR_IDENTICAL_JACCARD = 0.8
SAME_ARTICLES_JACCARD = 0.9
SAME_ARTICLES_MIN = 3

_HOLE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# Direction words, English only: the cached card's plain fields are the English fallback the
# frames rebuild (card.frames_text), so they are the one language every card carries.
_RISING = re.compile(
    r"\b(rising|rises|rose|surg\w*|grow\w*|grew|climb\w*|increas\w*|jump\w*|spik\w*|soar\w*|up from)\b|[↑▲⬆]",
    re.IGNORECASE,
)
_FALLING = re.compile(
    r"\b(falling|falls|fell|declin\w*|drop\w*|decreas\w*|shrink\w*|shrank|plung\w*|slump\w*|down from)\b|[↓▼⬇]",
    re.IGNORECASE,
)
# Names that mark a figure as a count. Matched on the whole key or a ``_``-separated part.
_COUNT_PARTS = frozenset({
    "n", "count", "articles", "sources", "mentions", "voices", "reports", "outlets", "items", "docs", "total",
})
# Pairs of signal keys that carry a "now" and a "before" figure, tried in order.
_PAIRS = (
    ("recent", "prior"),
    ("recent_mentions", "prior_mentions"),
    ("recent_total", "prior_count"),
    ("recent_articles", "prior_articles"),
    ("after", "before"),
    ("current", "previous"),
)
_RATIO_METRICS = frozenset({"growth_ratio", "growth", "ratio"})


def _now() -> datetime:
    return datetime.now(UTC)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _dict(obj: dict, name: str) -> dict:
    v = obj.get(name)
    return v if isinstance(v, dict) else {}


def _list(obj: dict, name: str) -> list:
    v = obj.get(name)
    return v if isinstance(v, list) else []


def _text(card: dict, name: str) -> str:
    v = card.get(name)
    return v if isinstance(v, str) else ""


def _card_ref(card: dict) -> dict:
    return {
        "card_id": card.get("id"),
        "card_type": card.get("type"),
        "producer": card.get("produced_by") or None,
        "title": _text(card, "title")[:160],
    }


def _finding(check: str, card: dict | None, detail: str, evidence: dict | None = None) -> dict:
    spec = CHECKS[check]
    out: dict[str, Any] = {
        "check": check,
        "dimension": spec["dimension"],
        "severity": spec["severity"],
        "detail": detail,
    }
    if card is not None:
        out.update(_card_ref(card))
    if evidence:
        out["evidence"] = evidence
    return out


# --------------------------------------------------------------------------- #
#  Per-card checks
# --------------------------------------------------------------------------- #
def direction_check(card: dict) -> dict | None:
    """Do the card's direction words agree with its own figures?

    Returns ``None`` when the card cannot be checked (no direction word, or no pair of
    figures to compare), else ``{"claimed", "measured", "agrees", "basis"}``. A ratio metric
    counts as rising above 1 and falling below 1; a now/before pair compares the two."""
    words = " ".join((_text(card, "title"), _text(card, "summary")))
    up = bool(_RISING.search(words))
    down = bool(_FALLING.search(words))
    if up == down:  # no direction word, or both (a comparison sentence): nothing to check
        return None
    claimed = "rising" if up else "falling"
    signal = _dict(card, "signal")
    measured: str | None = None
    basis: dict[str, Any] = {}
    for now_key, before_key in _PAIRS:
        a, b = _num(signal.get(now_key)), _num(signal.get(before_key))
        if a is not None and b is not None:
            basis = {now_key: a, before_key: b}
            measured = "rising" if a > b else "falling" if a < b else "flat"
            break
    if measured is None and str(signal.get("metric") or "") in _RATIO_METRICS:
        v = _num(signal.get("value"))
        if v is not None:
            basis = {"metric": signal.get("metric"), "value": v}
            measured = "rising" if v > 1 else "falling" if v < 1 else "flat"
    if measured is None:
        return None
    return {"claimed": claimed, "measured": measured, "agrees": measured == claimed, "basis": basis}


def _walk_numbers(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_numbers(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_numbers(v, f"{path}[{i}]")
    else:
        yield path, obj


def _is_count_name(key: str) -> bool:
    low = key.lower()
    return low in _COUNT_PARTS or any(p in _COUNT_PARTS for p in low.split("_"))


def check_card(card: dict, *, now: datetime | None = None) -> list[dict]:
    """Every per-card check that needs nothing but the card itself."""
    del now  # reserved: per-card age checks would use it; the feed-level one does today
    out: list[dict] = []
    title, summary = _text(card, "title"), _text(card, "summary")
    if not title.strip() or not summary.strip():
        out.append(_finding("empty_text", card, "title empty" if not title.strip() else "summary empty"))
    for name, value in (("title", title), ("summary", summary)):
        holes = _HOLE.findall(value)
        if holes:
            out.append(_finding("unfilled_template", card, f"{name} shows {', '.join(sorted(set(holes)))}"))
    if not _text(card, "caveat").strip():
        out.append(_finding("caveat_missing", card, "caveat is empty"))
    if not _text(card, "method").strip():
        out.append(_finding("method_missing", card, "method is empty"))
    if not _text(card, "created_at").strip():
        out.append(_finding("date_missing", card, "created_at is empty"))
    ids = _list(card, "article_ids")
    n = card.get("n")
    evidence = _list(card, "evidence")
    if n is None and not ids:
        out.append(_finding("n_missing", card, "n is null and the card links no article set"))
    if isinstance(n, int) and not isinstance(n, bool) and ids and n != len(ids):
        out.append(_finding("n_mismatch", card, f"n = {n}, article_ids = {len(ids)}",
                            {"n": n, "article_ids": len(ids)}))
    if not ids and not evidence:
        out.append(_finding("no_evidence_link", card, "no article_ids and no evidence rows"))
    signal = _dict(card, "signal")
    for path, value in _walk_numbers({"signal": signal, "n": n}):
        if isinstance(value, float) and not math.isfinite(value):
            out.append(_finding("non_finite_figure", card, f"{path} = {value!r}"))
            continue
        key = path.rsplit(".", 1)[-1]
        v = _num(value)
        if v is not None and v < 0 and _is_count_name(key):
            out.append(_finding("negative_count", card, f"{path} = {value}"))
    metric = str(signal.get("metric") or "")
    measured = _num(signal.get("value"))
    if (isinstance(n, int) and not isinstance(n, bool) and n == 0) or (
        measured == 0 and metric and _is_count_name(metric)
    ):
        out.append(_finding("trivial_signal", card, f"n = {n}, {metric or 'value'} = {signal.get('value')}"))
    if len(title) > TITLE_MAX_CHARS:
        out.append(_finding("too_long", card, f"title is {len(title)} characters"))
    if len(summary) > SUMMARY_MAX_CHARS:
        out.append(_finding("too_long", card, f"summary is {len(summary)} characters"))
    d = direction_check(card)
    if d is not None and not d["agrees"]:
        out.append(_finding("direction_mismatch", card, f"says {d['claimed']}, figures are {d['measured']}", d))
    return out


# --------------------------------------------------------------------------- #
#  Feed-level checks
# --------------------------------------------------------------------------- #
def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if len(w) > 2}


def _tokens(card: dict) -> set[str]:
    """The words that are DATA in a card's title and summary, not its template.

    A card's keyed frames (``i18n``) hold the fixed template and the values filled into it, so
    two cards of one kind share every template word whatever they are about; comparing whole
    sentences called "“regional” spread across 5 sources" and "“local” spread across 3 sources"
    near-identical. A card without frames is compared on its whole title and summary."""
    i18n = _dict(card, "i18n")
    frames = [fr for name in ("title", "summary") for fr in _list(i18n, name) if isinstance(fr, dict)]
    values = [str(v) for fr in frames for v in _dict(fr, "v").values() if v is not None]
    values += [str(v) for v in _dict(card, "title_vars").values() if v is not None]
    if frames or card.get("title_i18n"):
        return _words(" ".join(values))
    return _words(_text(card, "title") + " " + _text(card, "summary"))


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def _norm_title(card: dict) -> str:
    return " ".join(_text(card, "title").lower().split())


def check_feed(cards: list[dict]) -> list[dict]:
    """Duplicates and near-duplicates across the feed (each pair reported once)."""
    out: list[dict] = []
    by_title: dict[str, list[dict]] = {}
    for c in cards:
        t = _norm_title(c)
        if t:
            by_title.setdefault(t, []).append(c)
    for group in by_title.values():
        if len(group) > 1:
            ids = [c.get("id") for c in group]
            for c in group:
                out.append(_finding("duplicate_title", c, f"{len(group)} cards share this title", {"card_ids": ids}))
    tokens = [_tokens(c) for c in cards]
    idsets = [set(c.get("article_ids") or []) for c in cards]
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]
            if _norm_title(a) and _norm_title(a) == _norm_title(b):
                continue  # already a duplicate_title
            if a.get("type") == b.get("type") and tokens[i] and tokens[j]:
                jt = _jaccard(tokens[i], tokens[j])
                if jt >= NEAR_IDENTICAL_JACCARD:
                    out.append(_finding("near_identical", a, f"token overlap {jt:.2f} with {b.get('id')}",
                                        {"other_card_id": b.get("id"), "overlap": round(jt, 3)}))
            if len(idsets[i]) >= SAME_ARTICLES_MIN and len(idsets[j]) >= SAME_ARTICLES_MIN:
                ja = _jaccard(idsets[i], idsets[j])
                if ja >= SAME_ARTICLES_JACCARD:
                    out.append(_finding("same_articles", a, f"article overlap {ja:.2f} with {b.get('id')}",
                                        {"other_card_id": b.get("id"), "overlap": round(ja, 3)}))
    return out


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def check_meta(meta: dict, *, registered: list[str] | None, cards: list[dict],
               now: datetime | None = None) -> list[dict]:
    """Staleness, producer performance and coverage, from the feed's own record."""
    now = now or _now()
    out: list[dict] = []
    for key in ("incomplete_reason", "kept_reason"):
        if meta.get(key):
            out.append(_finding("feed_incomplete", None, f"{key} = {meta[key]}"))
    gen = _parse_time(meta.get("generated_at"))
    if gen is not None and (now - gen).total_seconds() > FEED_OLD_DAYS * 86400:
        out.append(_finding("feed_old", None, f"feed generated {gen.isoformat(timespec='seconds')}",
                            {"age_days": round((now - gen).total_seconds() / 86400, 1)}))
    for name in meta.get("stopped_producers") or []:
        out.append({**_finding("producer_stopped", None, f"{name} stopped at its bound"), "producer": name})
    timings = _list(meta, "producer_timings")
    for t in timings:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if t.get("outcome") == "error":
            out.append({**_finding("producer_error", None, f"{name} raised {t.get('error_type') or 'an error'}"),
                        "producer": name})
        secs = _num(t.get("seconds"))
        if secs is not None and secs >= SLOW_PRODUCER_S and t.get("outcome") != "stopped":
            out.append({**_finding("producer_slow", None, f"{name} took {secs:.0f} s"), "producer": name,
                        "evidence": {"seconds": secs}})
    if registered:
        made = {c.get("produced_by") for c in cards if c.get("produced_by")}
        if made:  # cards from before produced_by was cached cannot say who made them
            outcome = {t.get("name"): t.get("outcome") for t in timings if isinstance(t, dict)}
            for name in registered:
                if name not in made:
                    why = outcome.get(name) or "not in this refresh's timings"
                    out.append({**_finding("kind_never_seen", None, f"{name} made no card ({why})"), "producer": name})
    return out


def check_evidence(card: dict, evidence: dict | None) -> list[dict]:
    """Checks that need the evidence rows the field file carries (never run in the app)."""
    out: list[dict] = []
    if not isinstance(evidence, dict):
        return out
    missing = evidence.get("missing_n") or 0
    if missing:
        out.append(_finding("evidence_missing_articles", card, f"{missing} of {evidence.get('total')} ids do not resolve",
                            {"missing_n": missing, "total": evidence.get("total")}))
    quarantined = evidence.get("quarantined_n") or 0
    if quarantined:
        out.append(_finding("evidence_quarantined", card, f"{quarantined} of {evidence.get('total')} articles quarantined",
                            {"quarantined_n": quarantined, "total": evidence.get("total")}))
    return out


def check_arithmetic(card: dict, arithmetic: dict | None) -> list[dict]:
    """The app's own recomputation of the trigger math (``card_audit.check_trigger``)."""
    if not isinstance(arithmetic, dict) or not arithmetic.get("failed_n"):
        return []
    rows = [r for r in arithmetic.get("rows") or [] if isinstance(r, dict) and r.get("reproduced") is False]
    return [_finding("arithmetic_failed", card, f"{arithmetic['failed_n']} math row(s) did not reproduce",
                     {"rows": rows[:5]})]


# --------------------------------------------------------------------------- #
#  The report
# --------------------------------------------------------------------------- #
def _rank(findings: list[dict]) -> list[dict]:
    hits = Counter(f["check"] for f in findings)
    return sorted(
        findings,
        key=lambda f: (_SEVERITY_ORDER[f["severity"]], -hits[f["check"]], f["check"], str(f.get("card_id") or ""),
                       str(f.get("producer") or ""), f.get("detail", "")),
    )


def quality_report(
    cards: list[dict],
    *,
    meta: dict | None = None,
    registered: list[str] | None = None,
    per_card: dict[str, dict] | None = None,
    cheap_only: bool = False,
    now: datetime | None = None,
) -> dict:
    """Run every check over a feed and rank the findings.

    ``cards`` are card dicts as cached (``Card.to_dict`` plus ``produced_by``). ``meta`` is the
    feed record (``generated_at``, ``incomplete_reason``, ``stopped_producers``,
    ``producer_timings``). ``per_card`` maps a card id to ``{"evidence", "arithmetic"}`` from
    the field file; ``cheap_only`` skips the checks that need it (the in-app run)."""
    now = now or _now()
    meta = meta or {}
    per_card = per_card or {}
    findings: list[dict] = []
    not_checkable_direction = 0
    checked_direction = 0
    arithmetic_seen = evidence_seen = False
    for c in cards:
        findings.extend(check_card(c, now=now))
        if direction_check(c) is None:
            not_checkable_direction += 1
        else:
            checked_direction += 1
        extra = per_card.get(str(c.get("id"))) or {}
        if "arithmetic" in extra:
            arithmetic_seen = True
            findings.extend(check_arithmetic(c, extra.get("arithmetic")))
        if not cheap_only and "evidence" in extra:
            evidence_seen = True
            findings.extend(check_evidence(c, extra.get("evidence")))
    findings.extend(check_feed(cards))
    findings.extend(check_meta(meta, registered=registered, cards=cards, now=now))
    ranked = _rank(findings)
    by_check = Counter(f["check"] for f in ranked)
    kinds: dict[str, dict[str, Any]] = {}
    for c in cards:
        k = kinds.setdefault(str(c.get("type")), {"cards": 0, "findings": Counter()})
        k["cards"] += 1
    for f in ranked:
        if f.get("card_type") is not None:
            kinds.setdefault(str(f["card_type"]), {"cards": 0, "findings": Counter()})["findings"][f["check"]] += 1
    # A check is listed as run only when its input was there: a feed with no evidence rows has
    # not passed the evidence checks, it has not had them.
    ran = [
        k for k, v in CHECKS.items()
        if (k != "arithmetic_failed" or arithmetic_seen) and (v["cheap"] or evidence_seen)
    ]
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "feed_generated_at": meta.get("generated_at"),
        "cards": len(cards),
        "checks_run": ran,
        "checks_not_run": [k for k in CHECKS if k not in ran],
        "direction": {"checked": checked_direction, "not_checkable": not_checkable_direction,
                      "note": "not_checkable cards carry no direction word or no pair of figures; they are not passes"},
        "counts": [{"check": k, "n": by_check.get(k, 0), "severity": CHECKS[k]["severity"],
                    "dimension": CHECKS[k]["dimension"]} for k in ran],
        "per_kind": {k: {"cards": v["cards"], "findings": [{"check": c, "n": n} for c, n in sorted(v["findings"].items())]}
                     for k, v in sorted(kinds.items())},
        "findings": ranked,
        "note": ("Each finding is an inconsistency inside a card or between a card and its own evidence. "
                 "No check here measures whether the world matches a card, and there is no blended score."),
    }


def finding_key(f: dict) -> str:
    """A finding's identity across two files: the check plus what it is about."""
    return "|".join(str(x or "") for x in (f.get("check"), f.get("card_id"), f.get("producer")))


def compare_reports(previous: dict, current: dict) -> dict:
    """Which findings are new, which are gone, and how each check's count moved.

    Fewer findings for a check is ``improved`` and more is ``regressed``; a check run in only
    one of the two reports is ``not-comparable``, never assumed zero."""
    prev_counts = {c["check"]: c["n"] for c in previous.get("counts") or []}
    cur_counts = {c["check"]: c["n"] for c in current.get("counts") or []}
    per_check = []
    for check in sorted(set(prev_counts) | set(cur_counts)):
        a, b = prev_counts.get(check), cur_counts.get(check)
        if a is None or b is None:
            verdict = "not-comparable"
        else:
            verdict = "improved" if b < a else "regressed" if b > a else "unchanged"
        per_check.append({"check": check, "previous": a, "current": b, "verdict": verdict})
    prev_keys = {finding_key(f) for f in previous.get("findings") or []}
    cur = current.get("findings") or []
    cur_keys = {finding_key(f) for f in cur}
    gone = [f for f in previous.get("findings") or [] if finding_key(f) not in cur_keys]
    new = [f for f in cur if finding_key(f) not in prev_keys]
    return {
        "schema": COMPARE_SCHEMA,
        "previous_generated_at": previous.get("generated_at"),
        "current_generated_at": current.get("generated_at"),
        "per_check": per_check,
        "verdict_counts": dict(Counter(p["verdict"] for p in per_check)),
        "new_findings": new,
        "resolved_findings": gone,
        "note": "Counts compared per check; a check run in only one report is not-comparable. No blended verdict.",
    }


# --------------------------------------------------------------------------- #
#  The in-app recurring self-check
# --------------------------------------------------------------------------- #
SELF_CHECK_KEEP = 200


def with_producers(payload: dict, cards: list[dict] | None = None) -> list[dict]:
    """The feed's cards, each with ``produced_by`` filled from the feed's ``card_producers`` map.

    ``Card.to_dict`` does not carry the producer, so the cache keeps a separate id -> producer map;
    copies are returned and the cache's own dicts are never changed."""
    producers = _dict(payload, "card_producers")
    src = cards if cards is not None else _list(payload, "cards")
    return [
        {**c, "produced_by": c.get("produced_by") or producers.get(str(c.get("id"))) or ""}
        for c in src if isinstance(c, dict)
    ]


def self_check(payload: dict, *, registered: list[str] | None = None, per_card: dict[str, dict] | None = None,
               now: datetime | None = None) -> dict:
    """The cheap checks over a freshly written Home feed, as ONE compact history record.

    Holds check ids, counts and card ids only, never card text, so the history file adds no
    personal content beyond what the feed cache already holds."""
    cards = with_producers(payload)
    report = quality_report(cards, meta=payload, registered=registered, per_card=per_card, cheap_only=True, now=now)
    return {
        "schema": SELF_CHECK_SCHEMA,
        "at": report["generated_at"],
        "feed_generated_at": payload.get("generated_at"),
        "cards": len(cards),
        "counts": [c for c in report["counts"] if c["n"]],
        "high_n": sum(c["n"] for c in report["counts"] if c["severity"] == HIGH),
        "findings": [{"check": f["check"], "card_id": f.get("card_id"), "producer": f.get("producer")}
                     for f in report["findings"] if f["severity"] != INFO][:100],
        "direction": report["direction"],
        "checks_run": report["checks_run"],
    }


def append_history(lines: list[str], record: dict, *, keep: int = SELF_CHECK_KEEP) -> list[str]:
    """The history with ``record`` appended and only the newest ``keep`` lines kept."""
    kept = [ln for ln in lines if ln.strip()][-(keep - 1):] if keep > 1 else []
    return [*kept, json.dumps(record, ensure_ascii=False, sort_keys=True)]
