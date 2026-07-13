"""
LLM-perception EVAL HARNESS — who/where/when extraction (S6.5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The ruled ordering (2026-06-18): the harness comes BEFORE any LLM extraction feature — a
model is measured against the RULE-BASED baseline before it is trusted, exactly as the
`ir_eval` retrieval harness gates ranking/conflation. This module scores an extractor
(rule-based OR a future LLM, pluggable) on a difficulty-tiered, phenomenon-tagged synthetic
gold set across languages, reporting per-stratum **precision / recall / HALLUCINATION-rate**
— never one pooled average alone, never a composite score.

HONESTY (the LLM-PERCEPTION doctrine, enforced here):
  * PER-STRATUM with n stated (by language / tier / phenomenon / field), an `overall` pooled
    view carrying the read-per-stratum caveat — a model can win overall while failing Arabic;
  * HALLUCINATION-rate is first-class (predictions NOT in the gold ÷ predictions) — the
    fabrication measure the whole project turns on; a NEGATIVE case (empty gold) makes every
    prediction a hallucination, so "invented an entity from nothing" is measured directly;
  * de-US-centring measured per stratum (a US-centric vs non-US recall split), so a baseline
    that only works on Anglophone/US text is visible, not hidden in the pooled number;
  * a place STRING match and its gazetteer COORDINATE match are scored SEPARATELY (a right
    "Paris" can resolve to the wrong Paris) — the coordinate stratum runs only where the case
    carries gold coords and the extractor returns them;
  * DETERMINISTIC (no model call in the scorer); the extractor is injected. This ships the
    HARNESS only — NOT an extraction feature (that waits for a model to clear the harness).

The synthetic gold set here is MODEST and clearly synthetic — it proves the mechanism across
tiers/phenomena/languages; the ar/zh/ja/hi/bn cases are flagged ``needs_native_review``. A
larger graded set is an operator/next-session expansion (the same measure-before-trust gate).
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PerceptionCase:
    """One synthetic case. ``who``/``where``/``when`` are the GOLD answers (normalized on
    compare). ``when`` uses ISO dates or bare years, as published. ``where_geo`` is an
    optional ``{place: (lat, lon)}`` for the separate coordinate stratum."""

    id: str
    language: str
    tier: str  # easy | medium | hard
    phenomenon: str  # explicit-date | no-year-date | place | org | person | ambiguous-place | negative
    text: str
    who: tuple[str, ...] = ()
    where: tuple[str, ...] = ()
    when: tuple[str, ...] = ()
    us_centric: bool = False
    needs_native_review: bool = False
    where_geo: dict = field(default_factory=dict)


def _norm(s: str) -> str:
    """Fold case + accents + collapse whitespace, for a forgiving string match."""
    s = unicodedata.normalize("NFKD", str(s or "")).strip().lower()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _counts(pred: list[str], gold: tuple[str, ...]) -> tuple[int, int, int, int]:
    """(tp, fp, fn, n_pred): set overlap of normalized predictions vs gold."""
    ps = {_norm(x) for x in pred if _norm(x)}
    gs = {_norm(x) for x in gold if _norm(x)}
    tp = len(ps & gs)
    fp = len(ps - gs)
    fn = len(gs - ps)
    return tp, fp, fn, len(ps)


def _metrics(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    # hallucination = share of PREDICTIONS that are not in the gold (the fabrication measure).
    hallucination_rate = fp / (tp + fp) if (tp + fp) else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "hallucination_rate": round(hallucination_rate, 4)
        if hallucination_rate is not None
        else None,
    }


_FIELDS = ("who", "where", "when")


def evaluate_perception(extract_fn, cases: list[PerceptionCase]) -> dict:
    """Score ``extract_fn(text, language) -> {"who":[...], "where":[...], "when":[...]}`` over
    ``cases``. Returns per-stratum precision/recall/hallucination (by language / tier /
    phenomenon / field), a US-vs-non-US recall split (de-US-centring), a separate place
    COORDINATE stratum, and a pooled ``overall`` carrying the read-per-stratum caveat. No
    composite score; every stratum states n."""
    # accumulators: stratum-key -> field -> [tp,fp,fn]
    strata: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(
        lambda: {f: [0, 0, 0] for f in _FIELDS}
    )
    field_tot: dict[str, list[int]] = {f: [0, 0, 0] for f in _FIELDS}
    ncase: dict[tuple[str, str], int] = defaultdict(int)
    geo = [0, 0, 0]  # coordinate stratum tp/fp/fn

    def add(dim: str, val: str, fld: str, tp: int, fp: int, fn: int) -> None:
        s = strata[(dim, val)][fld]
        s[0] += tp
        s[1] += fp
        s[2] += fn

    for c in cases:
        out = extract_fn(c.text, c.language) or {}
        for fld in _FIELDS:
            tp, fp, fn, _ = _counts(list(out.get(fld) or []), getattr(c, fld))
            for dim, val in (
                ("language", c.language),
                ("tier", c.tier),
                ("phenomenon", c.phenomenon),
                ("us", "us-centric" if c.us_centric else "non-us"),
            ):
                add(dim, val, fld, tp, fp, fn)
            field_tot[fld][0] += tp
            field_tot[fld][1] += fp
            field_tot[fld][2] += fn
        for dim, val in (
            ("language", c.language),
            ("tier", c.tier),
            ("phenomenon", c.phenomenon),
            ("us", "us-centric" if c.us_centric else "non-us"),
        ):
            ncase[(dim, val)] += 1
        # separate place COORDINATE stratum: only when the case carries gold coords AND the
        # extractor returned coords for the place (a right name can resolve to the wrong point).
        if c.where_geo:
            pred_geo = (out.get("where_geo") or {})
            for place, (glat, glon) in c.where_geo.items():
                pc = pred_geo.get(place) or pred_geo.get(_norm(place))
                if pc is None:
                    geo[2] += 1  # fn (no coordinate predicted)
                elif abs(pc[0] - glat) <= 1.0 and abs(pc[1] - glon) <= 1.0:
                    geo[0] += 1  # tp (within ~1 degree)
                else:
                    geo[1] += 1  # fp (wrong point — the ambiguous-Paris failure)

    def dim_report(dim: str) -> dict:
        out: dict[str, dict] = {}
        for (d, val), fields in strata.items():
            if d != dim:
                continue
            row: dict[str, object] = {f: _metrics(*fields[f]) for f in _FIELDS}
            row["n_cases"] = ncase[(dim, val)]
            out[val] = row
        return dict(sorted(out.items()))

    return {
        "n_cases": len(cases),
        "by_language": dim_report("language"),
        "by_tier": dim_report("tier"),
        "by_phenomenon": dim_report("phenomenon"),
        "de_us_centring": dim_report("us"),  # us-centric vs non-us — read the recall split
        "by_field_overall": {f: _metrics(*field_tot[f]) for f in _FIELDS},
        "place_coordinate": _metrics(*geo) if (geo[0] + geo[1] + geo[2]) else None,
        "method": (
            "precision/recall/hallucination-rate per stratum (language·tier·phenomenon·field) "
            "vs a synthetic gold set; place STRING and gazetteer COORDINATE scored separately; "
            "de-US-centring is the us-centric vs non-us recall split."
        ),
        "caveat": (
            "Per-stratum with n — NEVER one pooled average alone (a model can win overall and "
            "fail a language). Hallucination-rate = predictions not in the gold ÷ predictions "
            "(the fabrication measure). No composite score. The gold set is synthetic + modest; "
            "ar/zh/ja/hi/bn cases need native review."
        ),
    }


def perception_delta(baseline: dict, candidate: dict) -> dict:
    """Per-field recall/precision/hallucination CHANGE (candidate − baseline), reported
    SEPARATELY (never blended) so a model's recall gain and any hallucination rise are both
    visible — the measure-before-trust A/B for an extraction change."""
    out: dict[str, object] = {}
    for fld in _FIELDS:
        b = baseline.get("by_field_overall", {}).get(fld, {})
        c = candidate.get("by_field_overall", {}).get(fld, {})

        def d(key: str, b=b, c=c):
            bv, cv = b.get(key), c.get(key)
            return round(cv - bv, 4) if (bv is not None and cv is not None) else None

        out[fld] = {
            "recall_delta": d("recall"),
            "precision_delta": d("precision"),
            "hallucination_delta": d("hallucination_rate"),
        }
    out["caveat"] = (
        "Recall gain and hallucination change reported SEPARATELY, never blended — a model "
        "that finds more but invents more is not an improvement. No composite."
    )
    return out


# --------------------------------------------------------------------------- #
# The synthetic gold set — MODEST, clearly synthetic, expandable. Simple factual sentences
# with UNAMBIGUOUS entities (low fabrication risk); ar/zh/ja/hi/bn flagged needs_native_review.
# `when` uses ISO dates / bare years as the extractor should emit them. Covers 12 languages,
# 3 tiers, and the phenomena incl. a NEGATIVE case (empty gold) + an ambiguous-place-with-geo.
# --------------------------------------------------------------------------- #
PERCEPTION_GOLD: list[PerceptionCase] = [
    PerceptionCase("en_e1", "en", "easy", "explicit-date",
                   "The World Health Organization met in Geneva on 5 March 2024.",
                   who=("World Health Organization",), where=("Geneva",), when=("2024-03-05",)),
    PerceptionCase("en_e2", "en", "easy", "explicit-date",
                   "The Senate convened in Washington on 5 March 2024.",
                   who=("Senate",), where=("Washington",), when=("2024-03-05",), us_centric=True),
    PerceptionCase("en_m1", "en", "medium", "org",
                   "The African Union opened its summit in Addis Ababa.",
                   who=("African Union",), where=("Addis Ababa",)),
    PerceptionCase("en_h1", "en", "hard", "ambiguous-place",
                   "Paris hosted the climate talks.",
                   where=("Paris",), where_geo={"Paris": (48.8566, 2.3522)}),
    PerceptionCase("en_n1", "en", "easy", "negative",
                   "It was a quiet, uneventful afternoon with nothing to report."),
    PerceptionCase("fr_e1", "fr", "easy", "explicit-date",
                   "Les Nations Unies se sont réunies à Genève le 5 mars 2024.",
                   who=("Nations Unies",), where=("Genève",), when=("2024-03-05",)),
    PerceptionCase("de_e1", "de", "easy", "explicit-date",
                   "Die Europäische Kommission tagte am 5. März 2024 in Brüssel.",
                   who=("Europäische Kommission",), where=("Brüssel",), when=("2024-03-05",)),
    PerceptionCase("es_e1", "es", "easy", "explicit-date",
                   "La Organización de Estados Americanos se reunió en Bogotá el 5 de marzo de 2024.",
                   who=("Organización de Estados Americanos",), where=("Bogotá",), when=("2024-03-05",)),
    PerceptionCase("pt_e1", "pt", "easy", "place",
                   "A cúpula ocorreu em Brasília.", where=("Brasília",)),
    PerceptionCase("nl_e1", "nl", "easy", "place",
                   "De top vond plaats in Den Haag.", where=("Den Haag",)),
    PerceptionCase("ru_e1", "ru", "easy", "place",
                   "Саммит прошёл в Москве.", where=("Москва",), needs_native_review=False),
    PerceptionCase("id_e1", "id", "easy", "place",
                   "Pertemuan diadakan di Jakarta.", where=("Jakarta",)),
    PerceptionCase("ar_e1", "ar", "easy", "place",
                   "عُقد الاجتماع في القاهرة.", where=("القاهرة",), needs_native_review=True),
    PerceptionCase("zh_e1", "zh", "easy", "place",
                   "峰会在北京举行。", where=("北京",), needs_native_review=True),
    PerceptionCase("ja_e1", "ja", "easy", "place",
                   "会議は東京で開かれた。", where=("東京",), needs_native_review=True),
    PerceptionCase("hi_e1", "hi", "easy", "place",
                   "शिखर सम्मेलन दिल्ली में हुआ।", where=("दिल्ली",), needs_native_review=True),
    PerceptionCase("bn_e1", "bn", "easy", "place",
                   "সম্মেলনটি ঢাকায় অনুষ্ঠিত হয়।", where=("ঢাকা",), needs_native_review=True),
]


def rule_based_perception(text: str, language: str | None = None) -> dict:
    """The RULE-BASED baseline adapter: wires the existing who/where/when extractors into the
    harness's ``{who, where, when}`` shape. This is the baseline a future LLM must clear.
    Best-effort + defensive (a failing extractor degrades to an empty field, never raises)."""
    who: list[str] = []
    where: list[str] = []
    when: list[str] = []
    try:
        from src.timemap.entextract import extract_entities

        ent = extract_entities(text)
        who = [e["name"] for e in ent.get("people", [])] + [
            e["name"] for e in ent.get("organizations", [])
        ]
    except Exception:  # noqa: BLE001 - a baseline field degrades, never breaks the harness
        who = []
    try:
        from src.timemap.locextract import extract_locations

        where = [str(p["name"]) for p in extract_locations(text, source_country=None) if p.get("name")]
    except Exception:  # noqa: BLE001
        where = []
    try:
        from src.timemap.dateextract import extract_dates

        for d in extract_dates(text, language=language) or []:
            iso = getattr(d, "iso", None) or getattr(d, "date", None)
            when.append(str(iso) if iso else str(getattr(d, "year", "")))
    except Exception:  # noqa: BLE001
        when = []
    return {"who": who, "where": where, "when": [w for w in when if w]}


def run_perception_eval_selftest() -> dict:
    """Prove the SCORER on a hand-computed fixture (a deterministic stub extractor, so a known
    precision/recall/hallucination is asserted — the harness, not an extractor). Exported so a
    regression reddens both the in-app self-test and CI (mirrors run_ir_eval_selftest)."""
    cases = [
        PerceptionCase("t1", "en", "easy", "explicit-date", "A met in B on 2024-01-01.",
                       who=("A",), where=("B",), when=("2024-01-01",)),
        PerceptionCase("t2", "en", "easy", "negative", "nothing here."),
    ]

    def stub(text, language=None):
        # t1: gets who+when right, INVENTS a wrong place "Z" (a hallucination), misses "B".
        # t2 (negative): invents "Ghost" -> a pure hallucination.
        if "2024-01-01" in text:
            return {"who": ["A"], "where": ["Z"], "when": ["2024-01-01"]}
        return {"who": ["Ghost"], "where": [], "when": []}

    r = evaluate_perception(stub, cases)
    who = r["by_field_overall"]["who"]
    where = r["by_field_overall"]["where"]
    when = r["by_field_overall"]["when"]
    checks = {
        # who: t1 tp=1 (A), t2 fp=1 (Ghost) -> precision 1/2, recall 1/1, hallucination 1/2
        "who_precision_half": who["precision"] == 0.5,
        "who_recall_full": who["recall"] == 1.0,
        "who_hallucination_half": who["hallucination_rate"] == 0.5,
        # where: t1 pred Z (fp), gold B (fn) -> precision 0, recall 0, hallucination 1.0
        "where_precision_zero": where["precision"] == 0.0,
        "where_hallucination_full": where["hallucination_rate"] == 1.0,
        # when: t1 exact -> precision/recall 1.0, hallucination 0.0
        "when_perfect": when["precision"] == 1.0 and when["recall"] == 1.0 and when["hallucination_rate"] == 0.0,
        # a negative case makes an invented entity a measured hallucination
        "negative_case_catches_fabrication": r["by_phenomenon"]["negative"]["who"]["fp"] == 1,
    }
    return {
        "schema": "oo-perception-eval-selftest-1",
        "gold_cases": len(PERCEPTION_GOLD),
        "passed": all(checks.values()),
        "checks": checks,
        "result": r,
    }
