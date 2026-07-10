"""Relative-day words for Hungarian + Persian (B4), with the negative-space guards.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

MEASURE-FIRST context: the field-test 2026-07-08 figures ("fa 0% / hu 22%") were
STALE — fa Jalali+Gregorian and hu named/numeric dates already extracted on the
current tree (the #590 Jalali claim-on-route work moved fa). The genuine residual was
relative day words. Only the collision-FREE ones are added; the rest are deliberately
omitted (miss over invent) and this file pins BOTH the additions and the omissions.
"""

from __future__ import annotations

import datetime

from src.timemap.dateextract import _REL_WORDS, extract_dates

_TODAY = datetime.date(2026, 7, 10)


def _one(text: str, lang: str):
    r = extract_dates(text, today=_TODAY, anchor=_TODAY, language=lang)
    return r[0]["date"] if r else None


def test_hungarian_relative_words_resolve():
    assert _one("A találkozó tegnap volt.", "hu") == "2026-07-09"  # tegnap = yesterday
    assert _one("A szavazás holnap lesz.", "hu") == "2026-07-11"  # holnap = tomorrow


def test_persian_yesterday_resolves():
    assert _one("جلسه دیروز برگزار شد.", "fa") == "2026-07-09"  # دیروز = yesterday


def test_persian_diruz_does_not_trigger_the_dey_month():
    # دیروز starts with دی (Dey, month 10). It must extract exactly one 'yesterday'
    # date, never a fabricated Dey-month date (the #590 substring hazard).
    r = extract_dates("دیروز جلسه بود.", today=_TODAY, anchor=_TODAY, language="fa")
    assert len(r) == 1 and r[0]["date"] == "2026-07-09"


def test_deliberate_omissions_stay_empty():
    # miss over invent — these are NOT in the vocabulary, so they must extract nothing.
    assert _one("Ma reggel esett.", "hu") is None  # hu bare "ma" (today), 2-char collision
    assert _one("روزنامه امروز را خواندم.", "fa") is None  # Emruz daily (امروز)
    assert _one("به رادیو فردا گوش دادم.", "fa") is None  # Radio Farda (فردا)


def test_vocabulary_contains_only_the_safe_forms():
    assert {"tegnap", "holnap", "دیروز"} <= set(_REL_WORDS)
    assert not ({"ma", "امروز", "فردا"} & set(_REL_WORDS))


def test_datediag_probe_mirrors_the_new_words():
    # Lockstep: the diagnostics probe rebuilds _REL_RE from _REL_WORDS, so a new
    # relative word is recognised by the coverage probe without a phantom gap.
    from src.timemap.datediag import _REL_RE

    assert _REL_RE.search("tegnap") and _REL_RE.search("holnap") and _REL_RE.search("دیروز")
