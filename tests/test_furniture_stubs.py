"""
Page furniture + stub signals (source-qualification review, 2026-10-17).

The four specimens are the stored bodies of four real pages that passed the ingest gate before
this change (Fjordabladet, Borgåbladet, Hufvudstadsbladet, Ilkka-Pohjalainen). The NEGATIVE SPACE
matters most: a false positive hides a real article.
"""

from __future__ import annotations

from src.ingest.furniture import is_menu_like, strip_furniture, stub_verdict
from src.ingest.non_article import classify_non_article

MENU = [
    "Hopp til Hovedinnhold",
    "Nyhende",
    "Sport",
    "Kultur",
    "Meiningar",
    "Eigedom",
    "Næringsliv",
    "Cruise",
    "Skipstrafikken",
    "eAvis",
    "Nattmodus",
    "Vel mørk eller lys utsjånad på avisa:",
    "På",
    "Auto",
    "Av",
    "Søk",
    "Seksjonar",
    "Nyhende",
    "Sport",
    "Kultur",
    "Meiningar",
    "Eigedom",
    "Næringsliv",
    "Cruise",
    "Vêret live",
    "Skipstrafikken",
    "Spel",
    "eAvis",
    "Kundar",
    "Bli abonnent",
    "Kundeservice",
    "Annonsering",
    "Personvernpolicy",
    "Kontakt oss",
    "Har gitt utsett spreiefrist for husdyrgjødsel - varslar innskjerping",
    "Allerede abonnent?",
    "Logg inn",
]
FJORD = "\n\n".join(MENU)
FJORD_URL = "https://www.fjordabladet.no/nyhende/n/2pQoWa/har-gitt-utsett-spreiefrist"

BBL = (
    "Det är en lugn och koncentrerad Olivia Kindstedt som går uppför den lilla backen mot "
    "frisbeegolfbanan i Tolkis i Borgå. Banan invigdes för bara några veckor sedan.\n\n"
    "Annons\n\nAnnons\n\nAnnons\n\nOlivia Kindstedt har siktet inställt på VM-guld\n\n"
    "Borgåbon Olivia Kindstedt går från klarhet till klarhet på frisbeegolfbanan. Målet är "
    "klart: en dag ska hon stå överst på prispallen som världsmästare.\n\nAnnons\n\nAnnons"
)
HBL_BANNER = (
    "För att din app ska fortsätta fungera som det är tänkt behöver du uppdatera till nyaste "
    "versionen. Klicka på knappen för att uppdatera!"
)


def test_fjordabladet_menu_body_is_a_menu_stub():
    assert is_menu_like(FJORD)
    verdict = classify_non_article(FJORD_URL, text=FJORD, word_count=len(FJORD.split()), language="no")
    assert verdict is not None and verdict.signal == "menu_stub"


def test_swedish_prenumerant_prompt_is_a_paywall_stub():
    text = "Rubriken\n\nRedan prenumerant? Logga in för att läsa vidare."
    signal, _ = stub_verdict(text)
    assert signal == "paywall_stub"


def test_ad_placeholders_and_app_banner_are_stripped_from_teasers():
    cleaned, removed = strip_furniture(BBL)
    assert removed == 5 and "Annons" not in cleaned
    assert "frisbeegolfbanan" in cleaned
    cleaned, removed = strip_furniture("Första stycket.\n\n" + HBL_BANNER + "\n\nUppdatera nu!")
    assert removed == 1 and cleaned.startswith("Första stycket.")


def test_the_teaser_prose_itself_is_kept():
    cleaned, _ = strip_furniture(BBL)
    assert classify_non_article(
        "https://www.bbl.fi/sport/olivia-kindstedt-har-siktet-installt-pa-vm-guld/",
        text=cleaned, word_count=len(cleaned.split()), language="sv",
    ) is None


def test_text_without_furniture_comes_back_unchanged():
    text = "Ett vanligt stycke.\n\nEtt till."
    assert strip_furniture(text) == (text, 0)


def test_a_paragraph_that_only_contains_the_word_is_kept():
    text = "Annons i tidningen kostade tusen kronor.\n\nAnnonsen togs bort."
    assert strip_furniture(text) == (text, 0)


def test_short_real_brief_with_few_paragraphs_is_not_a_menu():
    brief = "Kort.\n\nTre.\n\nOrd."
    assert not is_menu_like(brief)
    assert stub_verdict(brief) is None


def test_list_of_full_sentences_is_not_a_menu():
    text = "\n\n".join(f"Dette er setning nummer {i} i en vanlig sak." for i in range(15))
    assert not is_menu_like(text)



def test_quarantine_batch_marks_stubs_but_only_by_stamp_and_only_when_writing():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.analytics.quarantine_job import default_quarantine_candidates_batch
    from src.database.models import Article, Base, Source

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        src = Source(name="S", domain="fjordabladet.no")
        s.add(src)
        s.commit()
        for i, (url, text) in enumerate([
            (FJORD_URL, FJORD),
            ("https://www.bbl.fi/sport/olivia-kindstedt-har-siktet-installt-pa-vm-guld/", BBL),
        ]):
            s.add(Article(url=url, canonical_url=url, source_id=src.id, content=text, hash=f"h{i}",
                          word_count=len(text.split()), language="no", title=f"t{i}"))
        s.commit()
    with Session() as s:
        dry = default_quarantine_candidates_batch(s)
        assert dry["by_reason"] == {"menu_stub": 1} and dry["newly_written"] == 0
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 0
        off = default_quarantine_candidates_batch(s, include_stubs=False)
        assert off["quarantined"] == 0
        done = default_quarantine_candidates_batch(s, write=True, criteria_version="v-test")
        assert done["newly_written"] == 1
        row = s.query(Article).filter(Article.quarantined.is_(True)).one()
        assert row.quarantine_reason == "menu_stub" and row.quarantine_criteria_version == "v-test"
        # Idempotent: a second write stamps nothing new and the teaser prose row is untouched.
        assert default_quarantine_candidates_batch(s, write=True)["newly_written"] == 0
