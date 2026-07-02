"""Date-extractor recall slice C: relative words + weekdays beyond en/fr/de.

What this pins — each gap verified missing (or each fabrication verified
firing) before the change:

  * RELATIVE-WORD breadth: ru/ar/hi/bn/el/pl/ro/nl/sv/da/sr/tr/id-ms had no
    yesterday/today/tomorrow vocabulary at all.
  * PER-TOKEN LANGUAGE GATES (the _MONTH_LANG_OVERRIDES policy applied to
    relative words): da "mandag morgen" = Monday MORNING extracted "tomorrow"
    (measured live false positive) — "morgen" is now de/nl-gated; jutro
    (sr/hr/bs "morning"), Latin sutra (the en loan noun), tr short words,
    id/ms short words are gated the same way. No hint -> skip, never guess.
  * WEEKDAY breadth with COLLOCATION gates: bare ru/sr среда = "environment",
    sr недеља / id minggu = "week", tr pazar = "market" — those resolve ONLY
    inside their unambiguous collocations ("в среду", "hari Minggu", "pazar
    günü"); sv definite-past "i fredags" = LAST Friday (the bare-token regex
    cannot even see it: the trailing -s is a word character).
  * APPOSITIVE GUARD: a weekday adjacent to an already-claimed explicit date
    ("2024年6月11日（星期二）", "Tuesday, June 16, 2026") names THAT date — the
    anchored resolution would invent a second, different date.
  * CJK/KO relatives + weekdays are boundary-free (ideographs/Hangul are \\w,
    so \\b never fires) and language-gated; zh [上下本]周X uses CALENDAR-week
    semantics (上周二 = Tuesday of the previous Monday-start week, up to a week
    apart from the English "last Tuesday" reading); 周日 is deliberately NOT
    accepted (上周日本首相 = 上周+日本).
  * ENGLISH anchored offsets: "N days ago" (full phrase — bare "ago" is
    Italian for "needle") and the last/next/this month family at month
    precision; "the last month (of the war)" excluded.

Pure module — runs in the sandbox and CI.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap.dateextract import extract_dates

TODAY = date(2026, 6, 22)
ANCHOR = date(2026, 6, 10)  # a Wednesday; ISO week Mon 2026-06-08 .. Sun 2026-06-14


def _dates(text, lang=None, anchor=ANCHOR):
    return [
        (c["date"], c["precision"])
        for c in extract_dates(text, today=TODAY, anchor=anchor, language=lang)
    ]


# ---- relative words: new languages ------------------------------------------- #

def test_relative_words_new_languages():
    assert _dates("Он сказал вчера, что завтра будет заявление.", "ru") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("Η κυβέρνηση ανακοίνωσε σήμερα νέα μέτρα.", "el") == [("2026-06-10", "day")]
    assert _dates("Premier powiedział wczoraj, że jutro będzie spotkanie.", "pl") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("قال أمس إن الاجتماع سيعقد غدا.", "ar") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("তিনি গতকাল বলেছেন, আগামীকাল সভা হবে।", "bn") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("Он је јуче рекао да ће сутра бити седница.", "sr") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("Presiden kemarin mengatakan besok ada rapat.", "id") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("Rapporten kom igår; beslutet fattas i morgon.", "sv") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]


def test_relative_words_are_anchored_only():
    assert _dates("Он сказал вчера.", "ru", anchor=None) == []
    assert _dates("他昨天表示反对。", "zh", anchor=None) == []


def test_morgen_gate_fixes_the_danish_morning_false_positive():
    # da "mandag morgen" = Monday MORNING: only the weekday resolves (the most
    # recent Monday), never a fabricated "tomorrow".
    assert _dates("Mødet begyndte mandag morgen i København.", "da") == [("2026-06-08", "day")]
    # The da tomorrow is the PHRASE "i morgen"; de keeps the bare word.
    assert _dates("Statsministeren taler i morgen.", "da") == [("2026-06-11", "day")]
    assert _dates("Wir sehen uns morgen früh.", "de") == [("2026-06-11", "day")]
    # No language hint -> a gated token is skipped, never guessed.
    assert _dates("Wir sehen uns morgen früh.", None) == []


def test_gated_homograph_relatives_skip_outside_their_language():
    assert _dates("Sunčano jutro u Zagrebu donosi mir.", "hr") == []      # morning, not pl tomorrow
    assert _dates("Jutro odbędzie się posiedzenie.", "pl") == [("2026-06-11", "day")]
    assert _dates("The Lotus Sutra was chanted at dawn.", "en") == []     # the loan noun
    assert _dates("Bu senin kararın olmalı.", "tr") == []                 # tr "your", not id Monday


def test_turkish_relatives_and_headline_casefold_guard():
    assert _dates("Bakan dün açıklama yaptı; yarın toplantı var.", "tr") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    # "YARIN".lower() == "yarin" != the dotless-ı key: skipped, never a crash.
    assert _dates("BAKAN YARIN KONUŞACAK", "tr") == []


# ---- weekdays: new languages + collocation gates ------------------------------ #

def test_weekday_breadth_new_languages():
    assert _dates("Sejm zbierze się w środę.", "pl") == [("2026-06-10", "day")]
    assert _dates("يعقد الاجتماع يوم الاثنين المقبل.", "ar") == [("2026-06-08", "day")]
    assert _dates("बैठक सोमवार को होगी।", "hi") == [("2026-06-08", "day")]
    assert _dates("সভা শুক্রবার অনুষ্ঠিত হবে।", "bn") == [("2026-06-05", "day")]
    assert _dates("Ședința are loc vineri la Palat.", "ro") == [("2026-06-05", "day")]
    assert _dates("De vergadering vond woensdag plaats.", "nl") == [("2026-06-10", "day")]
    assert _dates("Заседание прошло в четверг.", "ru") == [("2026-06-04", "day")]


def test_collocation_only_weekday_homographs():
    # ru Wednesday is a DELIBERATE OMISSION (second-round verifier finding):
    # even the collocation "в среду" is also accusative "into the environment"
    # ("внедрение в среду разработки" is everyday tech prose) — miss over invent.
    assert _dates("Совещание прошло в среду.", "ru") == []
    assert _dates("Компания объявила о внедрении системы в среду разработки.", "ru") == []
    assert _dates("Это естественная среда обитания тигров.", "ru") == []
    # sr keeps its prepositional collocation (sr "middle/milieu" is средина).
    assert _dates("Седница је одржана у среду.", "sr") == [("2026-06-10", "day")]
    # id "minggu" = week: only "hari Minggu" is the weekday.
    assert _dates("Acara digelar hari Minggu di Jakarta.", "id") == [("2026-06-07", "day")]
    assert _dates("Proyek selesai dalam dua minggu.", "id") == []
    # tr "pazar" = market / "cuma": only the "günü" collocations resolve.
    assert _dates("Toplantı cuma günü yapılacak.", "tr") == [("2026-06-05", "day")]
    assert _dates("Kapalı pazar çok kalabalıktı.", "tr") == []


def test_gated_weekday_tokens():
    # id "senin" = Monday; tr "senin" = "your" — language-gated.
    assert _dates("Rapat digelar Senin di Jakarta.", "id") == [("2026-06-08", "day")]
    # sr/BCS "petak" = Friday; id "petak" = a plot/compartment — gated.
    assert _dates("Sednica je zakazana za petak.", "sr") == [("2026-06-05", "day")]
    assert _dates("Mereka tinggal di rumah petak.", "id") == []


def test_swedish_definite_past_weekdays_resolve_last_week():
    # "i fredags" = LAST Friday — said on a Wednesday, that is 5 days back,
    # never the upcoming one; the bare token cannot claim it (trailing -s).
    assert _dates("Beslutet fattades i fredags.", "sv") == [("2026-06-05", "day")]
    # Said ON the same weekday, it means a full week back.
    assert _dates("Beslutet fattades i onsdags.", "sv") == [("2026-06-03", "day")]


def test_weekday_appositive_of_an_explicit_date_is_not_a_second_date():
    # The weekday NAMES the explicit date; anchored resolution would invent a
    # different one (2026-06-16 is a Tuesday; the most recent Tuesday from the
    # anchor is 2026-06-09 — extracting both would be a fabrication).
    assert _dates("The summit opens Tuesday, June 16, 2026.", "en") == [("2026-06-16", "day")]
    assert _dates("La réunion aura lieu mardi 16 juin.", "fr") == [("2026-06-16", "day")]
    # ...while a standalone weekday still resolves (the news convention).
    assert _dates("Strikes resumed Tuesday across the region.", "en") == [("2026-06-09", "day")]


# ---- CJK + Korean relatives and weekdays -------------------------------------- #

def test_cjk_relative_words():
    assert _dates("他昨天表示反对，明天公布结果。", "zh") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("首相は昨日、会見した。明日は国会だ。", "ja") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    # Proper-noun compounds never match: Asuka, Toutiao, Tomorrow Holding.
    assert _dates("明日香村で発掘調査が行われた。", "ja") == []
    assert _dates("今日头条发布了新的报告。", "zh") == []
    assert _dates("明天系的资产被接管。", "zh") == []
    # Language-gated: CJK relative words never fire outside zh/ja.
    assert _dates("他昨天表示反对。", "en") == []


def test_cjk_weekdays_and_calendar_week_modifiers():
    assert _dates("会议在星期二举行。", "zh") == [("2026-06-09", "day")]
    assert _dates("活动定在星期天举行。", "zh") == [("2026-06-07", "day")]
    assert _dates("会見は金曜日に行われた。", "ja") == [("2026-06-05", "day")]
    assert _dates("月曜に発表される。", "ja") == [("2026-06-08", "day")]
    # [上下本]周X = CALENDAR-week semantics (anchor Wed 2026-06-10, week of
    # Jun 8): 上周二 = Tue of the PREVIOUS week (Jun 2, not "most recent" Jun 9);
    # 下周五 = Fri of NEXT week (Jun 19, not the upcoming Jun 12).
    assert _dates("上周二股市大跌。", "zh") == [("2026-06-02", "day")]
    assert _dates("下周五公布数据。", "zh") == [("2026-06-19", "day")]
    assert _dates("本周五举行发布会。", "zh") == [("2026-06-12", "day")]


def test_cjk_weekday_segmentation_traps():
    # 这个星期天气 = "this week the WEATHER" (星期天 + 气 would be Sunday).
    assert _dates("这个星期天气很好。", "zh") == []
    # 上周日本首相 = 上周 + 日本 ("last week, Japan's PM") — 周日 deliberately out.
    assert _dates("上周日本首相访问了北京。", "zh") == []
    assert _dates("上周日经指数上涨。", "zh") == []
    # The appositive guard covers the standard dateline format.
    assert _dates("会议于2024年6月11日（星期二）举行。", "zh") == [("2024-06-11", "day")]


def test_korean_relatives_and_weekdays():
    assert _dates("정부는 어제 발표했고 내일 회의가 열린다.", "ko") == [
        ("2026-06-09", "day"), ("2026-06-11", "day")]
    assert _dates("회의는 화요일에 열렸다.", "ko") == [("2026-06-09", "day")]
    # Compound substrings never match: 안내일정 (guidance schedule) contains
    # 내일; 내일신문 is a newspaper; 오늘날 = "nowadays".
    assert _dates("행사 안내일정은 홈페이지에 있다.", "ko") == []
    assert _dates("내일신문 기자가 보도했다.", "ko") == []
    assert _dates("오늘날 한국 사회는 변했다.", "ko") == []
    # Particle attachments DO match (어제는 / 오늘도 / 내일부터).
    assert _dates("오늘도 협상이 이어졌다.", "ko") == [("2026-06-10", "day")]
    # Appositive: the weekday names the explicit date.
    assert _dates("회의는 2024년 6월 11일 화요일에 열렸다.", "ko") == [("2024-06-11", "day")]


# ---- English anchored offsets -------------------------------------------------- #

def test_english_days_ago():
    assert _dates("The attack happened three days ago near the border.", "en") == [
        ("2026-06-07", "day")]
    assert _dates("Officials confirmed it 10 days ago.", "en") == [("2026-05-31", "day")]
    # The FULL phrase is required; Italian "ago" (needle) never fires.
    assert _dates("L'ago della bilancia si è spostato.", "it") == []
    # en-gated: quoted English inside another language's article stays out.
    assert _dates("He said it two days ago.", "de") == []
    assert _dates("Three days ago it rained.", "en", anchor=None) == []


def test_english_month_offsets():
    assert _dates("Inflation eased last month, data showed.", "en") == [("2026-05-01", "month")]
    assert _dates("Elections are next month.", "en") == [("2026-07-01", "month")]
    assert _dates("The law passed earlier this month.", "en") == [("2026-06-01", "month")]
    # "the last month (of the war)" is a duration / rolling window — excluded.
    assert _dates("It was the last month of the war.", "en") == []


def test_english_month_offsets_cross_year():
    assert _dates("Inflation eased last month.", "en", anchor=date(2026, 1, 15)) == [
        ("2025-12-01", "month")]
    assert _dates("Elections are next month.", "en", anchor=date(2025, 12, 15)) == [
        ("2026-01-01", "month")]


# ---- adversarial rounds (verifier-reproduced defects in the first cut) --------- #

def test_round2_gated_script_twins_and_urdu_humidity():
    # Cyrillic сутра gated {sr}: ru "Алмазная сутра" (the Buddhist text) and the
    # colloquial "сутра" (= "с утра", since morning) fabricated tomorrow.
    assert _dates("Алмазная сутра — один из важнейших буддийских текстов.", "ru") == []
    assert _dates("Он работал сутра до самого вечера.", "ru") == []
    # Urdu امس = humidity ("گرمی اور امس" is stock weather prose) → ar-gated.
    assert _dates("شہر میں گرمی اور امس نے لوگوں کو بے حال کر دیا۔", "ur") == []
    assert _dates("قال أمس إن الاجتماع انعقد.", "ar") == [("2026-06-09", "day")]


def test_round2_cjk_segmentation_and_brand_traps():
    assert _dates("這個星期天氣非常好，適合出遊。", "zh") == []      # traditional 天氣
    assert _dates("这个星期日元兑美元汇率大幅下跌。", "zh") == []     # 日元 = yen
    assert _dates("调查显示上周六成受访者支持该计划。", "zh") == []   # 六成 = 60%
    assert _dates("本周五金行业迎来涨价潮。", "zh") == []            # 五金 = hardware
    assert _dates("本周一些地区将有暴雨。", "zh") == []              # 一些 = some
    assert _dates("下周一系列活动将举行。", "zh") == []              # 一系列 = a series
    assert _dates("上周三名工人受伤。", "zh") == []                  # 三名 = three (workers)
    assert _dates("这些话题早已成为明日黄花。", "zh") == []          # the "outdated" idiom
    assert _dates("今日俄罗斯电视台播出了这段采访。", "zh") == []     # RT's zh name
    # ...while the genuine readings keep working:
    assert _dates("上周六成交量创下新高。", "zh") == [("2026-06-06", "day")]   # 成交量
    assert _dates("本周五金融市场波动加剧。", "zh") == [("2026-06-12", "day")]  # 金融
    assert _dates("本周一召开会议。", "zh") == [("2026-06-08", "day")]


def test_round2_weekday_place_names():
    assert _dates("Środa Wielkopolska liczy około 30 tysięcy mieszkańców.", "pl") == []
    assert _dates("Murska Sobota je mesto na severovzhodu Slovenije.", "sl") == []
    assert _dates("Çarşamba ilçesinde sel felaketi yaşandı.", "tr") == []


def test_round2_appositive_agreement_keeps_weekday_lists():
    # The guard suppresses ONLY an AGREEING adjacent date: weekday lists are
    # independent references (consecutive days never agree) and a non-matching
    # neighbour date must not swallow the weekday (2026-06-08 is a Monday).
    A = date(2026, 6, 17)
    assert _dates("The festival runs Friday, Saturday and Sunday.", "en", A) == [
        ("2026-06-12", "day"), ("2026-06-13", "day"), ("2026-06-14", "day")]
    assert _dates("Markets fell Monday, Tuesday brought relief.", "en", A) == [
        ("2026-06-15", "day"), ("2026-06-16", "day")]
    assert _dates("Tuesday, yesterday's vote failed.", "en", date(2026, 6, 19)) == [
        ("2026-06-16", "day"), ("2026-06-18", "day")]
    assert _dates("After the vote of 2026-06-08, Friday's session will decide.", "en") == [
        ("2026-06-08", "day"), ("2026-06-05", "day")]
    # A weekday agreeing with an adjacent RELATIVE day is a true appositive.
    assert _dates("The vote is Friday, tomorrow.", "en", date(2026, 6, 18)) == [
        ("2026-06-19", "day")]


def test_round2_swedish_danish_coming_weekday():
    # "på fredag" is grammatically the COMING Friday (the past is "i fredags") —
    # the bare-token most-recent fallback inverted the direction.
    assert _dates("Mötet hålls på fredag.", "sv") == [("2026-06-12", "day")]
    assert _dates("Rättegången inleds på måndag.", "sv") == [("2026-06-15", "day")]
    assert _dates("Kampen spilles på fredag.", "da") == [("2026-06-12", "day")]
    # da/nb definite-past spellings joined the sv table.
    assert _dates("Beslutningen blev truffet i lørdags.", "da") == [("2026-06-06", "day")]


def test_round2_english_offset_guards():
    # A compound duration's tail is not an offset ("two years and three days").
    assert _dates("The treaty was signed two years and three days ago.", "en") == []
    # Possessives flip last/next month to "the final month of a period".
    assert _dates("He spent his last month in office traveling abroad.", "en") == []
    assert _dates("It was the company's last month of operations.", "en") == []
    # The old fixed-width lookbehind let a double space through.
    assert _dates("Prices rose in the  last month.", "en") == []


def test_round2_indonesian_week_collocation_tail():
    # "setiap hari minggu ini" = "every day THIS WEEK" (minggu = week).
    assert _dates("Hujan turun setiap hari minggu ini di Jakarta.", "id") == []


# ---- third adversarial round (defects found in the FIXES themselves) ----------- #

def test_round3_repeated_dateline_appositive_survives_dedup():
    # found[] dedups by (date, precision) keeping the FIRST pos, so the second
    # occurrence's claimed span looked date-less to the agreement check and its
    # weekday anchor-resolved (measured: an invented 2026-06-09). The per-span
    # day record survives the dedup.
    assert _dates("On June 16, 2026 they met. Again: June 16, 2026, Tuesday, they signed.",
                  "en") == [("2026-06-16", "day")]
    assert _dates("They met on June 16. Later on June 16, Tuesday, they signed.",
                  "en") == [("2026-06-16", "day")]


def test_round3_cjk_continuations_second_pass():
    # 三分之一 (a third) / 一半 (half) / 三大 (the big three) still fabricated.
    assert _dates("上周三分之一的门店关闭。", "zh") == []
    assert _dates("本周一半的员工休假。", "zh") == []
    assert _dates("上周三大运营商发布财报。", "zh") == []
    # One-sided refinements keep the weekday-side news patterns alive:
    assert _dates("上周三人民银行宣布降息。", "zh") == [("2026-06-03", "day")]  # PBoC
    assert _dates("本周三大会开幕。", "zh") == [("2026-06-10", "day")]          # 大会
    assert _dates("上周三分析师发布报告。", "zh") == [("2026-06-03", "day")]     # 分析
    assert _dates("上周三人被捕。", "zh") == []  # three people — still blocked


def test_round3_english_guard_overreach():
    # A bare comma is ordinary prose, not a compound-duration tail.
    assert _dates("However, five days ago the dam failed.", "en") == [("2026-06-05", "day")]
    assert _dates("It happened, three days ago, near the port.", "en") == [("2026-06-07", "day")]
    assert _dates("It took two years, three days ago it ended.", "en") == []  # duration comma
    # "one last month" = one FINAL month, not the previous calendar month.
    assert _dates("They gave it one last month to work.", "en") == []


# ---- the diagnostics probe stays in lockstep ----------------------------------- #

def test_datediag_probe_mirrors_the_gates():
    import src.timemap.datediag as dd

    # A gated token outside its language is NOT date-like there — no phantom
    # gap on every Danish morning article / Turkish "senin" sentence.
    a = dd.analyze_article("Mødet begyndte mandag morgen i København.",
                           language="da", anchor=ANCHOR, today=TODAY)
    assert a["probe_by_kind"] == {"weekday": 1} and a["actionable_gap"] == 0
    assert dd.analyze_article("Bu senin kararın olmalı.", language="tr",
                              anchor=ANCHOR, today=TODAY)["probe_by_kind"] == {}
    # The new CJK/Korean/en-offset families are probed AND extracted in their
    # languages (no undercount, no phantom gap).
    for lang, txt in (("zh", "会议在星期二举行。"), ("ko", "회의는 화요일에 열렸다."),
                      ("en", "It happened three days ago.")):
        r = dd.analyze_article(txt, language=lang, anchor=ANCHOR, today=TODAY)
        assert r["n_extracted"] == 1 and r["actionable_gap"] == 0, (lang, r)
    # ...and are NOT probed outside them (the extractor's own gates mirrored).
    r = dd.analyze_article("他昨天表示反对。", language="en", anchor=ANCHOR, today=TODAY)
    assert r["probe_by_kind"] == {}
    # The appositive suppression is mirrored too — standard datelines (in both
    # month-first and day-first orders, and CJK) report NO phantom gap.
    for lang, txt in (("en", "The summit opens Tuesday, June 16, 2026."),
                      ("fr", "La réunion aura lieu mardi 16 juin."),
                      ("pl", "Posiedzenie odbyło się we wtorek, 11 czerwca 2024."),
                      ("zh", "会议于2024年6月11日（星期二）举行。"),
                      ("ko", "회의는 2024년 6월 11일 화요일에 열렸다.")):
        r = dd.analyze_article(txt, language=lang, anchor=ANCHOR, today=TODAY)
        assert r["n_extracted"] == 1 and r["actionable_gap"] == 0, (lang, r)
    # ...while an independent weekday list is probed AND extracted 3/3.
    r = dd.analyze_article("The festival runs Friday, Saturday and Sunday.",
                           language="en", anchor=date(2026, 6, 17), today=TODAY)
    assert r["probe_by_kind"] == {"weekday": 3} and r["n_extracted"] == 3
    assert r["actionable_gap"] == 0
