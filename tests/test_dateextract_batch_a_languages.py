"""Date-extraction vocabulary — backend batch A: Catalan, Persian (Gregorian only),
Malayalam, Telugu.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These four languages had NO month vocabulary (a date-diagnostics gap). This file pins:
  * each new native date extracts to the expected (iso, precision);
  * "miss over invent" — a bare month word with no adjacent day/year yields nothing;
  * the DELIBERATE OMISSIONS never fabricate — Persian SOLAR HIJRI month names (a different
    calendar) and Persian "May" (مه/می, an ultra-common word) are withheld and must NOT
    produce a date;
  * the datediag probe stays in LOCKSTEP (ca/fa/ml/te are in MONTH_VOCAB_LANGS and
    analyze_article reports zero actionable gap on a native date).

NOTE: the Malayalam/Telugu glyphs are AI-transliterated standard Gregorian names, flagged
for native review. A wrong glyph is a MISS (a month only fires beside a day/year), never a
fabrication, so an imperfect table degrades honestly — this test proves the MECHANISM
(script + digit + connector handling), which is what it can independently verify.
"""

from __future__ import annotations

from datetime import date

from src.timemap.dateextract import extract_dates

TODAY = date(2026, 6, 15)
ANCHOR = date(2024, 6, 10)


def _dates(text, lang=None):
    return [(c["date"], c["precision"])
            for c in extract_dates(text, today=TODAY, anchor=ANCHOR, language=lang)]


def test_catalan_dates_extract():
    cases = [
        ("La reunió va ser el 5 de març de 2024.", "ca", ("2024-03-05", "day")),
        ("Publicat el 15 de juny de 2023.", "ca", ("2023-06-15", "day")),
        ("L'informe és del 3 de setembre de 2022.", "ca", ("2022-09-03", "day")),
        ("el gener de 2021", "ca", ("2021-01-01", "month")),
    ]
    for text, lang, expected in cases:
        assert expected in _dates(text, lang), f"{text!r} -> {_dates(text, lang)!r}"


def test_persian_gregorian_dates_extract_western_and_persian_digits():
    cases = [
        ("جلسه در 15 ژانویه 2024 برگزار شد.", ("2024-01-15", "day")),
        ("جلسه در ۱۵ ژانویه ۲۰۲۴ برگزار شد.", ("2024-01-15", "day")),  # Persian digits
        ("در 3 اوت 2023 منتشر شد.", ("2023-08-03", "day")),
        ("سپتامبر 2022", ("2022-09-01", "month")),
        ("دسامبر 2021", ("2021-12-01", "month")),
    ]
    for text, expected in cases:
        assert expected in _dates(text, "fa"), f"{text!r} -> {_dates(text, 'fa')!r}"


def test_malayalam_and_telugu_dates_extract():
    cases = [
        ("5 മാർച്ച് 2024", "ml", ("2024-03-05", "day")),
        ("2024 മാർച്ച് 5 ന് യോഗം നടന്നു.", "ml", ("2024-03-05", "day")),
        ("ജനുവരി 2023", "ml", ("2023-01-01", "month")),
        ("5 మార్చి 2024", "te", ("2024-03-05", "day")),
        ("జనవరి 2023", "te", ("2023-01-01", "month")),
    ]
    for text, lang, expected in cases:
        assert expected in _dates(text, lang), f"{text!r} -> {_dates(text, lang)!r}"


def test_miss_over_invent_bare_month_word():
    # A month name with no adjacent day/year must NOT yield a date (recall never trades
    # precision — the same guard every language honours).
    assert _dates("El març va ser plujós.", "ca") == []
    assert _dates("മാർച്ച് മാസം", "ml") == []
    assert _dates("سپتامبر خوب بود.", "fa") == []


def test_persian_solar_hijri_names_are_not_fabricated():
    # Solar Hijri months name a DIFFERENT calendar; mapping them to Gregorian numbers would
    # fabricate a date (and the year 1403 even passes the CE window). They are omitted.
    assert _dates("۱۵ فروردین ۱۴۰۳ برگزار شد.", "fa") == []
    assert _dates("۵ اردیبهشت ۱۴۰۳", "fa") == []


def test_persian_may_is_withheld_as_a_fabrication_vector():
    # Persian "May" is مه / می — both ultra-common words ("fog" / the verb-prefix / "wine").
    # Withheld like the Levantine نيسان/آب: a day+year next to them must NOT extract May.
    assert _dates("۵ مه ۲۰۲۴", "fa") == []
    assert _dates("۵ می ۲۰۲۴", "fa") == []


def test_datediag_probe_stays_in_lockstep():
    import src.timemap.datediag as dd

    for lang in ("ca", "fa", "ml", "te"):
        assert lang in dd.MONTH_VOCAB_LANGS, lang
    # analyze_article must see exactly what the extractor sees (no phantom gap) on a native date.
    for text, lang in (
        ("5 de març de 2024", "ca"),
        ("15 ژانویه 2024", "fa"),
        ("5 മാർച്ച് 2024", "ml"),
        ("5 మార్చి 2024", "te"),
    ):
        a = dd.analyze_article(text, language=lang, today=TODAY)
        assert a["n_extracted"] == 1 and a["actionable_gap"] == 0, (lang, a)
