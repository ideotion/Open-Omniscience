"""Date-extractor recall slice B (field F4: coverage 51.6%, 45-CJK undercount).

The measured recall gaps this closes — each verified missing before the change:

  * KOREAN had ZERO coverage: dates use Hangul markers (년/월/일), not the 年月日
    ideographs — and the diagnostics probe was equally blind, so the field
    numbers structurally undercounted the gap.
  * GLUED CJK dates were invisible to BOTH the extractor and the probe:
    ideographs are \\w in Python re, so \\b never fired in "报道于2024-06-11发布".
    Fixed with ASCII lookarounds (byte-identical on Latin/Cyrillic/Arabic text).
  * 号/號 day markers (mainland-colloquial / traditional) degraded to month
    precision or missed.
  * Greek ACCUSATIVE month-year prose ("τον Σεπτέμβριο του 2001") and ALL-CAPS
    accentless forms (Greek uppercase drops the tonos) extracted nothing.
  * Cyrillic ordinal day-attachments ("11-го сентября") silently LOST day
    precision; Bengali date clitics ("১১ই সেপ্টেম্বর") missed.
  * Croatian and Czech had zero month vocabulary; Serbian-Latin unaccented
    genitives, Malay, Filipino and Swahili months missed. Collision tokens
    (dubna=Dubna-the-town, juna/jula=names/Norwegian-Christmas) are language-
    GATED via the override map, never global.

Pure module — runs in the sandbox and CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap.dateextract import extract_dates

TODAY = date(2026, 6, 22)
ANCHOR = date(2026, 6, 10)


def _dates(text, lang=None, anchor=ANCHOR):
    return [
        (c["date"], c["precision"])
        for c in extract_dates(text, today=TODAY, anchor=anchor, language=lang)
    ]


# ---- Korean 년/월/일 ---------------------------------------------------------- #

def test_korean_dates_extract():
    assert _dates("회의는 2024년 6월 11일에 열렸다.", "ko") == [("2024-06-11", "day")]
    assert _dates("보고서는 2023년 9월에 나왔다.", "ko") == [("2023-09-01", "month")]
    assert _dates("회의는 6월 11일에 열린다.", "ko") == [("2026-06-11", "day")]  # anchored


def test_korean_deictic_years_resolve_exactly():
    assert _dates("작년 6월 11일에 발표되었다.", "ko") == [("2025-06-11", "day")]
    assert _dates("올해 6월 11일에 발표되었다.", "ko") == [("2026-06-11", "day")]
    assert _dates("내년 6월 11일에 열린다.", "ko") == [("2027-06-11", "day")]


def test_korean_unparseable_year_suppresses():
    # A bare 2-digit year before 월일 = an explicit year we could not read.
    assert _dates("24년 6월 11일에 열렸다.", "ko") == []


# ---- glued CJK boundaries + 号/號 -------------------------------------------- #

def test_glued_ascii_dates_in_cjk_prose():
    # \b cannot fire between an ideograph and a digit — these were invisible.
    assert _dates("报道于2024-06-11发布。", "zh") == [("2024-06-11", "day")]
    assert _dates("于2024/06/11发布。", "zh") == [("2024-06-11", "day")]


def test_colloquial_day_markers():
    assert _dates("会议于2024年6月11号召开。", "zh") == [("2024-06-11", "day")]
    assert _dates("会议在6月11号举行。", "zh") == [("2026-06-11", "day")]  # anchored


def test_latin_text_boundaries_unchanged():
    # The lookarounds block the SAME ASCII neighbours \b blocked.
    assert _dates("Ref x2024-06-11 in the log.", "en") == []
    assert _dates("Version 11/06/20261 shipped.", "en") == []


# ---- Greek accusative + accentless ------------------------------------------ #

def test_greek_accusative_and_allcaps():
    assert _dates("Θα γίνει τον Σεπτέμβριο του 2001.", "el") == [("2001-09-01", "month")]
    # ALL-CAPS Greek drops the tonos; str.lower() emits final-ς (verified) —
    # the accentless table keys cover both.
    assert _dates("ΣΤΙΣ 11 ΣΕΠΤΕΜΒΡΙΟΥ 2001 ΕΓΙΝΕ.", "el") == [("2001-09-11", "day")]


# ---- Cyrillic ordinal attachments + Bengali clitics -------------------------- #

def test_cyrillic_ordinal_day_suffixes():
    # Day precision was silently LOST to the month match before.
    assert _dates("Он выступил 11-го сентября 2001 года.", "ru") == [("2001-09-11", "day")]
    assert _dates("Он выступит 11-го сентября.", "ru") == [("2026-09-11", "day")]  # anchored


def test_bengali_date_clitics():
    assert _dates("সভা ১১ই সেপ্টেম্বর ২০০১ সালে।", "bn") == [("2001-09-11", "day")]
    assert _dates("২৫শে ডিসেম্বর ২০২৩ তারিখে।", "bn") == [("2023-12-25", "day")]


# ---- Latin-script month tails (hr/cs/sr-Latin/ms/tl/sw) ---------------------- #

def test_croatian_and_czech_months():
    assert _dates("Sastanak je bio 5. rujna 2024.", "hr") == [("2024-09-05", "day")]
    assert _dates("Schůzka byla 5. září 2024.", "cs") == [("2024-09-05", "day")]


def test_gated_dubna():
    # cs April genitive vs Dubna, Russia (physics prose) — hint-or-skip.
    assert _dates("Schůzka byla 5. dubna 2024.", "cs") == [("2024-04-05", "day")]
    assert _dates("The Dubna 2024 workshop met.", "en") == []


def test_serbian_latin_genitives_with_gates():
    assert _dates("Sastanak je bio 5. januara 2024.", "sr") == [("2024-01-05", "day")]
    assert _dates("Sednica je bila 5. jula 2024.", "sr") == [("2024-07-05", "day")]
    # nb "i jula 2024" = "at Christmas 2024" — ungated this would fabricate July.
    assert _dates("Vi møttes i jula 2024 hjemme.", "nb") == []
    assert _dates("Juna 30 godina kasnije.", "sr", anchor=date(2026, 3, 15)) == []  # name shape


def test_malay_filipino_swahili_months():
    assert _dates("Mesyuarat pada 5 Ogos 2024.", "ms") == [("2024-08-05", "day")]
    assert _dates("Naganap noong ika-5 ng Hunyo 2024.", "tl") == [("2024-06-05", "day")]
    assert _dates("Mkutano ulifanyika 5 Machi 2024.", "sw") == [("2024-03-05", "day")]


# ---- second adversarial round (verifier-found defects in the first cut) ------ #

def test_duben_is_gated_like_dubna():
    # Duben is a German village/surname; the first cut gated only the genitive.
    assert _dates("Kontakt: Dorfstraße, Duben 15, 15926 Luckau.", "de") == []
    assert _dates("Der Ortsteil Duben 2024 feierte sein Dorffest.", "de") == []
    assert _dates("Termín je duben 2024 podle plánu.", "cs") == [("2024-04-01", "month")]


def test_korean_jinanhae_three_syllable_deictic():
    # 지난해 (last year) is three syllables — the 2-char peek missed it and
    # pinned the WRONG year (measured). Length-aware peek fixes it.
    assert _dates("지난해 6월 11일 서울에서 회의가 열렸다.", "ko", anchor=date(2025, 1, 15)) == [
        ("2024-06-11", "day")
    ]


def test_hao_classifier_nouns_are_not_dates():
    # 号 is ALSO the universal "No. N" marker: Metro Line 11 / Building 11 /
    # Document No. 11 / Typhoon No. 2 must never become day dates (measured).
    A = date(2025, 1, 15)
    assert _dates("地铁6月11号线正式开通运营。", "zh", anchor=A) == []
    assert _dates("该小区6月11号楼将交付使用。", "zh", anchor=A) == []
    assert _dates("国务院6月11号文件正式印发。", "zh", anchor=A) == []
    assert _dates("今年6月2号台风登陆广东。", "zh", anchor=A) == []
    # ...while the genuine colloquial day forms keep working:
    assert _dates("会议在6月11号举行。", "zh", anchor=A) == [("2025-06-11", "day")]
    assert _dates("活动定于6月11号，请准时。", "zh", anchor=A) == [("2025-06-11", "day")]


def test_kolovoz_roadway_is_gated():
    # kolovoz = "roadway" in Croatian ITSELF: "sletio s kolovoza 20 metara" is
    # standard traffic-accident prose and fabricated Aug 20 (measured).
    assert _dates("Automobil je sletio s kolovoza 20 metara u provaliju.", "hr") == []
    assert _dates("Vozilo je sletjelo s kolovoza 2024. godine u jarak.", None) == []
    assert _dates("Sastanak je bio 5. kolovoza 2024.", "hr") == [("2024-08-05", "day")]


def test_citation_shape_months_are_gated():
    # "(Agosti 2024)" is an author-year citation; Machi/Marso are names.
    assert _dates("Recent work on volcanic tremor (Agosti 2024) confirms.", "en") == []
    assert _dates("The Machi 2024 initiative launched.", "en") == []
    assert _dates("El grupo Marso 11 firmó el contrato.", "es") == []
    # sw/tl corpora keep the recall (language is always passed in production):
    assert _dates("Mkutano wa 5 Agosti 2024 mjini.", "sw") == [("2024-08-05", "day")]


def test_model_year_suffix_suppresses():
    # 2024년형 = model-year-2024: an explicit year token we cannot bind — the
    # anchored guess picked a DIFFERENT year (measured). Suppress, never guess.
    assert _dates("2024년형 6월 11일 출시 모델이 공개됐다.", "ko", anchor=date(2025, 1, 15)) == []


def test_digit_glued_numerals_still_block():
    # A date is never carved out of a longer mixed-script numeral (the \b digit
    # rule is kept for ALL scripts); letter-glued forms are the intended gain.
    assert _dates("رقم ٥٠2024-06-11 في التقرير", "ar") == []
    assert _dates("срок до 11.06.2024г. истекает", "ru") == [("2024-06-11", "day")]


# ---- the diagnostics probe stays in lockstep --------------------------------- #

def test_datediag_probe_sees_what_the_extractor_sees():
    import src.timemap.datediag as dd

    # Korean + glued forms are now PROBED (the field numbers stop undercounting)
    # and extracted, so no phantom gap appears.
    a = dd.analyze_article("회의는 2024년 6월 11일에 열렸다.", language="ko", today=TODAY)
    assert a["probe_by_kind"].get("cjk_date") == 1
    assert a["n_extracted"] == 1 and a["actionable_gap"] == 0
    b = dd.analyze_article("报道于2024-06-11发布。", language="zh", today=TODAY)
    assert b["probe_by_kind"].get("numeric", 0) + b["probe_by_kind"].get("cjk_date", 0) >= 1
    assert b["n_extracted"] == 1
    # An era date is date-like text (probed) AND extracted — no phantom gap.
    c = dd.analyze_article("戦争は昭和20年8月15日に終わった。", language="ja", today=TODAY)
    assert c["probe_by_kind"].get("cjk_date") == 1
    assert c["n_extracted"] == 1 and c["actionable_gap"] == 0
    # The languages whose vocab exists are declared (the flag must not lie).
    for lang in ("el", "uk", "hr", "cs", "ms", "tl", "sw", "sl", "et", "ur"):
        assert lang in dd.MONTH_VOCAB_LANGS, lang
