"""S4.1: the CJK-numeral date RECALL PROBE (datediag) — measure the one CJK class neither the
extractor nor the other probes see today (二〇二四年六月十一日). Candidates-only: the probe
NEVER stores a date, so it cannot fabricate; it just makes the class measurable for the operator
before anyone funds the fabrication-critical extractor change (#590). The negative-space cases
are mandatory — CJK numerals double as quantities/ordinals, so the probe is MARKER-ANCHORED
(needs 年+月 or 月…日) and a bare numeral run must never match.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap.datediag import analyze_article, recall_probe


def _kinds(text: str, language: str | None) -> set[str]:
    return {h["kind"] for h in recall_probe(text, language=language)}


def test_cjk_numeral_date_is_probed_for_zh_ja():
    for lang in ("zh", "ja"):
        assert "cjk_numeral" in _kinds("会议于二〇二四年六月十一日举行。", lang)  # full YMD
        assert "cjk_numeral" in _kinds("报告发表于二〇二四年六月。", lang)         # year-month
        assert "cjk_numeral" in _kinds("活动定于六月十一日。", lang)              # month-day


def test_cjk_numeral_negative_space():
    # MANDATORY (#590): marker-anchored, so bare CJK-numeral runs never match.
    for lang in ("zh", "ja"):
        assert "cjk_numeral" not in _kinds("售出十一件商品。", lang)   # 11 items (quantity)
        assert "cjk_numeral" not in _kinds("增长了六成。", lang)       # 60%
        assert "cjk_numeral" not in _kinds("六月的天气很好", lang)     # lone month word (no day)
        assert "cjk_numeral" not in _kinds("二〇二四年的报道", lang)   # year only (no month)
        assert "cjk_numeral" not in _kinds("请看第十一章", lang)       # chapter eleven (ordinal)
        assert "cjk_numeral" not in _kinds("十字路口", lang)           # "ten" in a word


def test_cjk_numeral_is_language_gated():
    # the numerals are ordinary words elsewhere -> only zh/ja probe them (no phantom gap)
    assert "cjk_numeral" not in _kinds("二〇二四年六月十一日", "en")
    assert "cjk_numeral" not in _kinds("二〇二四年六月十一日", None)


def test_cjk_numeral_is_context_only_never_an_actionable_gap():
    # the extractor deliberately does not parse it yet -> surfaced for measurement, but it
    # NEVER inflates actionable_gap (like bare_year): a zh article of only a CJK-numeral date
    # reports the candidate with a zero actionable gap, not a phantom vocabulary miss.
    r = analyze_article("会议于二〇二四年六月十一日举行。", language="zh", anchor=date(2024, 6, 1))
    assert r["probe_by_kind"].get("cjk_numeral", 0) >= 1
    assert r["actionable_gap"] == 0


def test_arabic_numeral_cjk_date_still_wins_its_span():
    # an Arabic-numeral CJK date is claimed by cjk_date (more specific), never double-reported.
    ks = _kinds("会议于2024年6月11日举行。", "zh")
    assert "cjk_date" in ks and "cjk_numeral" not in ks
