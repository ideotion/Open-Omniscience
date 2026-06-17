"""Tests for explicit-date extraction from article text (temporal map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

from src.timemap.dateextract import extract_dates

TODAY = date(2026, 6, 9)


def _dates(text):
    return [(c["date"], c["precision"]) for c in extract_dates(text, today=TODAY)]


def test_iso_and_full_forms():
    assert ("2001-09-11", "day") in _dates("It happened on 2001-09-11 downtown.")
    assert ("2001-09-11", "day") in _dates("On 11 September 2001 the towers fell.")
    assert ("2001-09-11", "day") in _dates("On September 11, 2001 the towers fell.")
    assert ("2001-09-11", "day") in _dates("Filed 11th September 2001 by our desk.")


def test_month_precision_and_abbreviations():
    assert ("2003-03-01", "month") in _dates("The invasion began in March 2003.")
    assert ("2003-03-01", "month") in _dates("Back in Mar. 2003 things changed.")
    # 'sept' must win over 'sep'
    assert ("2001-09-01", "month") in _dates("Sept 2001 was a turning point.")


def test_day_match_suppresses_inner_month_match():
    # 'September 11, 2001' should yield ONE day candidate, not also 'September 2001'
    got = _dates("September 11, 2001 is remembered.")
    assert got == [("2001-09-11", "day")]


def test_no_bare_years_or_relative():
    assert _dates("Revenue hit 2000 units and the 1945 bombing is history.") == []
    assert _dates("It happened last Tuesday, the report said.") == []
    assert _dates("See page 1999 for details.") == []


def test_invalid_dates_rejected():
    # 'Month DD, YYYY' with an impossible day and no bare 'Month YYYY' adjacency -> nothing
    assert _dates("Dated February 30, 2001 supposedly.") == []
    # an impossible 'DD Month YYYY' degrades to the month it still names — never a bad day,
    # never dropped entirely (honest: the text does reference that month).
    assert _dates("The 31 February 2001 memo.") == [("2001-02-01", "month")]


def test_out_of_range_year_rejected():
    assert _dates("A prophecy for January 3000.") == []  # too far ahead
    assert _dates("Filed 2099-01-01 in the system.") == []  # >today+5


def test_dedup_and_order_and_provenance():
    text = "First March 2003, later 2003-03-01 again, then April 2004."
    cands = extract_dates(text, today=TODAY)
    iso = [c["date"] for c in cands]
    # 2003-03-01 appears via both 'March 2003' (month) and ISO (day) -> distinct precisions kept,
    # but ordered by first appearance; April 2004 comes last.
    assert iso[-1] == "2004-04-01"
    assert all("text" in c and c["text"] for c in cands)  # provenance snippet present


def test_empty_and_limit():
    assert extract_dates("", today=TODAY) == []
    many = " ".join(f"{i} January 2001" for i in range(1, 20))
    assert len(extract_dates(many, today=TODAY, limit=3)) == 3


# --------------------------------------------------------------------------- #
#  Extractor optimization (maintainer 2026-06-11: "so little dates aggregated")
#  — multilingual months, numeric formats, anchored resolution.
# --------------------------------------------------------------------------- #
def test_multilingual_months_extract():
    got = _dates("Le sommet du 11 juin 2026 suivra la réunion del 5 de mayo de 2026 "
                 "und dem Treffen am 3. Dezember 2026, e l'incontro del 7 ottobre 2026.")
    assert ("2026-06-11", "day") in got
    assert ("2026-05-05", "day") in got
    assert ("2026-12-03", "day") in got
    assert ("2026-10-07", "day") in got


def test_additional_language_months_extract():
    """date-diagnostics 2026-06-17: these UI/corpus languages had no month
    vocabulary (coverage near-zero despite real article volume). Each writes a
    representative native date; the day/year context makes extraction safe."""
    cases = [
        ("Raportul a fost depus pe 31 august 2026.", "2026-08-31"),          # Romanian
        ("Toplantı 5 Mayıs 2024 tarihinde yapıldı.", "2024-05-05"),          # Turkish
        ("Mødet var den 5. maj 2024 i byen.", "2024-05-05"),                  # Danish
        ("Spotkanie odbyło się 5 maja 2024 roku.", "2024-05-05"),            # Polish (genitive)
        ("Stretnutie bolo 5. mája 2024 v meste.", "2024-05-05"),             # Slovak (genitive)
        ("Kokous pidettiin 5. toukokuuta 2024.", "2024-05-05"),              # Finnish (partitive)
        ("Sastanak je bio 5. septembar 2024.", "2024-09-05"),                # Serbian (Latin)
        ("Састанак је био 5. мај 2024.", "2024-05-05"),                       # Serbian (Cyrillic)
        ("Срещата беше на 5 май 2024 г.", "2024-05-05"),                      # Bulgarian (Cyrillic)
        ("A találkozó 2024. október 23. napján volt.", "2024-10-23"),        # Hungarian (year-first)
    ]
    for text, expected in cases:
        got = _dates(text)
        assert (expected, "day") in got, f"{text!r} -> {got!r}"


def test_rtl_and_indic_month_names():
    """Arabic / Hindi / Bengali Gregorian month names (UI locales the date-diag
    flagged at ~0% coverage). Native digits (Eastern-Arabic ٠-٩, Devanagari,
    Bengali) parse via \\d + int(); a month only fires next to a day/year, so
    'مارس' (=March, but also 'practised') never invents a date from prose."""
    from datetime import date

    from src.timemap.dateextract import extract_dates

    def d(text, anchor=None):
        return [(c["date"], c["precision"]) for c in extract_dates(text, today=TODAY, anchor=anchor)]

    assert ("2001-09-11", "day") in d("وقع الحدث في ١١ سبتمبر ٢٠٠١ في المدينة.")  # ar, eastern digits
    assert ("2024-05-05", "day") in d("اجتمعوا في 5 مايو 2024.")  # ar, ascii digits
    assert ("2003-03-01", "month") in d("في مارس 2024.".replace("2024", "2003"))  # ar month+year
    assert ("2001-09-11", "day") in d("बैठक ११ सितंबर २००१ को हुई।")  # hi, devanagari digits
    assert ("2001-09-11", "day") in d("সভা ১১ সেপ্টেম্বর ২০০১ সালে।")  # bn, bengali digits
    # 'مارس' inside 'يمارس' (practises), even before a year, must NOT match (word boundary)
    assert d("هو يمارس 2024 ساعة.") == []
    assert d("هو يمارس الرياضة كل يوم.") == []  # no adjacent number at all


def test_cjk_dates_year_month_day_markers():
    """Chinese/Japanese dates use the 年/月/日 ideographs as unambiguous markers
    (date-diag 2026-06-17 probes for 'cjk_date'). Half-width AND full-width digits
    resolve; a year-less 月日 needs the anchor; month-only 年月 is month precision."""
    from datetime import date

    from src.timemap.dateextract import extract_dates

    def d(text, anchor=None):
        return [(c["date"], c["precision"]) for c in extract_dates(text, today=TODAY, anchor=anchor)]

    assert d("会议于2024年5月11日举行。") == [("2024-05-11", "day")]  # zh
    assert d("2001年9月11日に発生した。") == [("2001-09-11", "day")]  # ja
    assert d("２０２４年５月１１日") == [("2024-05-11", "day")]  # full-width digits
    assert ("2003-03-01", "month") in d("2003年3月、戦争が始まった。")  # year+month only
    assert ("2024-05-11", "day") in d("5月11日に会談", anchor=date(2024, 6, 1))  # anchored
    assert d("活動は5月11日に") == []  # no year + no anchor -> never guessed
    assert d("2024年5月11日") == [("2024-05-11", "day")]  # day match suppresses the month


def test_added_months_do_not_invent_dates_without_a_number():
    """Precision guard for the new vocabulary: a month-word in running prose with
    NO adjacent day/year must NOT yield a date (the 'better to miss than invent'
    ethos). Romanian 'mai' = 'more', Turkish 'ocak' = 'hearth', and Spanish/
    Italian 'marca' = 'brand' (deliberately omitted from the table)."""
    assert _dates("Suntem printre cele mai tolerante națiuni.") == []      # ro 'mai' = more
    assert _dates("Evde eski bir ocak vardı, çok güzeldi.") == []          # tr 'ocak' = hearth
    assert _dates("Presentaron la marca 2024 de coches nuevos.") == []     # es 'marca' = brand


def test_month_lookup_never_raises_on_casefold_mismatch():
    """A regex hit whose str.lower() does not round-trip to the table key (the
    Turkish DOTLESS ı: 'MAYIS'.lower() == 'mayis' but the table stores 'mayıs')
    must be skipped gracefully, never KeyError-abort the whole extraction."""
    # All-caps ASCII-I Turkish: simply must not raise (recall loss on this rare
    # casing is acceptable; the normal 'Mayıs' form below still resolves).
    assert _dates("Toplantı 5 MAYIS 2024 tarihinde yapıldı.") == []
    assert ("2024-05-05", "day") in _dates("Toplantı 5 Mayıs 2024.")


def test_numeric_dates_language_disambiguated():
    from src.timemap.dateextract import extract_dates

    fr = extract_dates("Réunion le 11/06/2026.", language="fr")
    assert fr and fr[0]["date"] == "2026-06-11"          # DMY for French
    en = extract_dates("Meeting on 06/11/2026.", language="en")
    assert en and en[0]["date"] == "2026-06-11"          # MDY for English
    none = extract_dates("On 06/11/2026 something happened.")
    assert none == []                                     # ambiguous + no hint: SKIPPED
    sure = extract_dates("Am 25.12.2026 ist es soweit.")
    assert sure and sure[0]["date"] == "2026-12-25"       # day>12 disambiguates alone


def test_anchored_relative_and_weekday_resolution():
    from datetime import date

    from src.timemap.dateextract import extract_dates

    anchor = date(2026, 6, 10)  # a Wednesday
    got = {(c["date"], c["text"][:14]) for c in extract_dates(
        "Hier, la ville était calme. Mardi, les frappes ont repris. "
        "Tomorrow the talks resume; a summit on June 12 follows.",
        anchor=anchor, language="fr", limit=10)}
    dates = {d for d, _ in got}
    assert "2026-06-09" in dates   # hier = anchor - 1 AND mardi (most recent Tuesday)
    assert "2026-06-11" in dates   # tomorrow
    assert "2026-06-12" in dates   # day+month, year resolved from the anchor
    # Without an anchor, none of these resolve — never guessed.
    bare = extract_dates("Hier, mardi, tomorrow, June 12.", language="fr")
    assert bare == []


# --------------------------------------------------------------------------- #
#  Location extractor — the spatial twin (maintainer-ruled 2026-06-11)
# --------------------------------------------------------------------------- #
def test_extract_locations_cities_countries_and_disambiguation():
    from src.timemap.locextract import extract_locations

    text = ("Fighting intensified near Gaza while Iran and Israël traded warnings. "
            "In Paris, officials met; Paris later confirmed. The summit moved to Berlin.")
    got = extract_locations(text, source_country="fr", limit=8)
    names = {(e["name"], e["kind"]) for e in got}
    assert ("Iran", "country") in names
    assert ("Israël", "country") in names or ("Israel", "country") in names
    assert ("Paris", "city") in names
    paris = next(e for e in got if e["name"] == "Paris")
    assert paris["mentions"] == 2 and paris["country"] == "fr"
    assert "lat" in paris and "deduced" in paris["note"]
    # Case sensitivity guards common-word collisions: 'turkey' the bird ≠ Turkey.
    assert extract_locations("the turkey was delicious") != []  # country matches case-insensitively...
    # ...but a CITY name must be capitalised as written:
    assert all(e["kind"] != "city" for e in extract_locations("a paris of possibilities"))


def test_reader_shows_both_metadata_classes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import Article, SessionLocal, Source

    with TestClient(app) as c:  # startup creates the schema first
        s = SessionLocal()
        try:
            src = Source(name="Meta source", domain="meta.test", country="fr")
            s.add(src)
            s.flush()
            a = Article(
                url="https://meta.test/1", canonical_url="https://meta.test/1",
                source_id=src.id, title="Metadata classes", hash="meta-h1", language="fr",
                content="Le 11 juin 2026, des frappes près de Gaza. À Paris, réunion d'urgence.",
                published_at=__import__("datetime").datetime(2026, 6, 10),
                created_at=__import__("datetime").datetime(2026, 6, 11),
            )
            s.add(a)
            s.commit()
            aid = a.id
        finally:
            s.close()
        html = c.get(f"/api/articles/{aid}/view").text
        assert "From the source" in html
        assert "Deduced by this app — less reliable" in html
        assert "Event dates in text" in html and "2026-06-11" in html
        assert "Places in text" in html and "Gaza" in html
        assert "never a confirmed fact" in html


# --------------------------------------------------------------------------- #
#  Entity extractor — people vs organizations, the WHO axis
#  (maintainer-ruled 2026-06-11: separate classes by design)
# --------------------------------------------------------------------------- #
def test_extract_entities_people_and_orgs_separate():
    from src.timemap.entextract import extract_entities

    text = ("Yesterday, President Macron met Chancellor Scholz in Berlin. "
            "The talks, said Ursula Leyenberg, will continue. NATO observers "
            "attended, and NATO later issued a statement. The Finance Ministry "
            "and Acme Corp declined to comment.")
    got = extract_entities(text)
    people = {p["name"] for p in got["people"]}
    orgs = {o["name"] for o in got["organizations"]}
    assert "Macron" in people and "Scholz" in people
    assert "Ursula Leyenberg" in people               # mid-sentence shape rule
    assert "NATO" in orgs                             # repeated acronym
    assert "Finance Ministry" in orgs and "Acme Corp" in orgs
    assert not people & orgs                          # never double-classed
    assert all("deduced" in e["note"] for e in got["people"] + got["organizations"])
    assert all(e["snippet"] for e in got["people"] + got["organizations"])


def test_extract_entities_guards():
    from src.timemap.entextract import extract_entities

    # A single-occurrence acronym is NOT promoted to an organization.
    one = extract_entities("The report cited UNHCR once in passing.")
    assert all(o["name"] != "UNHCR" for o in one["organizations"])
    # Stoplisted acronyms never count, however often they repeat.
    stop = extract_entities("The USA and the EU met; the USA and the EU agreed.")
    assert stop["organizations"] == []
    # Sentence-initial TitleCase pairs are not mistaken for people.
    lead = extract_entities("Many Happy Returns was the headline. Nothing else here.")
    assert lead["people"] == []
    # A word claimed by an organization never doubles as a person:
    # 'World Bank' (org) blocks the person-shape 'Bank Moreau'.
    mixed = extract_entities(
        "Funding from the World Bank arrived, and analyst Bank Moreau agreed."
    )
    assert any("World Bank" in o["name"] for o in mixed["organizations"])
    assert all("Bank" not in p["name"] for p in mixed["people"])
    assert extract_entities("") == {"people": [], "organizations": []}


def test_reader_shows_entity_rows():
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import Article, SessionLocal, Source

    with TestClient(app) as c:
        s = SessionLocal()
        try:
            src = Source(name="Ent source", domain="ent.test", country="us")
            s.add(src)
            s.flush()
            a = Article(
                url="https://ent.test/1", canonical_url="https://ent.test/1",
                source_id=src.id, title="Entity classes", hash="ent-h1", language="en",
                content=("President Macron spoke as NATO met; NATO confirmed. "
                         "The Finance Ministry sent observers."),
                published_at=__import__("datetime").datetime(2026, 6, 10),
                created_at=__import__("datetime").datetime(2026, 6, 11),
            )
            s.add(a)
            s.commit()
            aid = a.id
        finally:
            s.close()
        html = c.get(f"/api/articles/{aid}/view").text
        assert "People in text" in html and "Macron" in html
        assert "Organizations in text" in html and "NATO" in html
