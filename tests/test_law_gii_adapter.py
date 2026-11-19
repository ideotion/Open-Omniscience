"""
The gesetze-im-internet adapter (Q925 = a's second): read, refuse, and wire into tracking.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The two fixtures are byte-for-byte EXCERPTS of the portal's own files (the Grundgesetz and
the BDSG 2018), as archived by an independent daily mirror on 2026-11-19 -- not hand-written,
and not fetched from the host, which the build sandbox cannot reach. See
``tests/fixtures/law/PROVENANCE.md``. Everything else here is built in the test, in memory.
"""

from __future__ import annotations

import io
import struct
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.law.adapters import AdapterRefusal, gii
from src.law.adapters.gii import looks_like_gii, parse_gii, unpack_zip
from src.law.adapters.registry import adapter_for, parse_with

_DIR = Path(__file__).parent / "fixtures" / "law" / "gii"
GG = _DIR / "gg_excerpt.xml"
BDSG = _DIR / "bdsg_2018_excerpt.xml"


def _zip(members: dict[str, bytes], *, method: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def _doc(*norms: str, doknr: str = "BJNRTEST") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" ?>'
        f'<dokumente doknr="{doknr}">' + "".join(norms) + "</dokumente>"
    )


_META = (
    "<norm><metadaten><jurabk>TestG</jurabk><ausfertigung-datum>2001-02-03</ausfertigung-datum>"
    "<langue>Testgesetz</langue></metadaten><textdaten/></norm>"
)


def _unit(kz: str, bez: str, titel: str) -> str:
    return (
        "<norm><metadaten><gliederungseinheit>"
        f"<gliederungskennzahl>{kz}</gliederungskennzahl><gliederungsbez>{bez}</gliederungsbez>"
        f"<gliederungstitel>{titel}</gliederungstitel></gliederungseinheit></metadaten></norm>"
    )


def _para(enbez: str, text: str, *, extra: str = "") -> str:
    return (
        f"<norm><metadaten><enbez>{enbez}</enbez></metadaten><textdaten>"
        f'<text format="XML"><Content><P>{text}</P></Content></text>{extra}</textdaten></norm>'
    )


# ---------------------------------------------------------------------------
# Reading the portal's own files
# ---------------------------------------------------------------------------


def test_the_basic_law_reads_as_its_articles_under_their_section():
    law = parse_gii(GG.read_bytes(), retrieved_on="2026-11-19")
    assert law.format == "gii"
    assert law.title == "Grundgesetz für die Bundesrepublik Deutschland"
    assert [p.number or p.heading for p in law.provisions] == [
        "Eingangsformel",
        "Präambel",
        "I. Die Grundrechte",
        "Art 1",
        "Art 2",
        "Art 3",
    ]
    art1 = law.provisions[3]
    assert art1.path == ("I. Die Grundrechte",)
    assert art1.identifier == "I. Die Grundrechte/Art 1"
    assert art1.text.startswith("(1) Die Würde des Menschen ist unantastbar.")
    # The preamble sits ABOVE the first section: it must not inherit a path it is not under.
    assert law.provisions[1].path == ()
    # Measured, not asserted: the only loss is whitespace where text nodes are joined.
    assert 0.99 <= law.text_recovered_pct <= 1.0
    assert law.unknown_elements == {}


def test_the_dates_are_the_documents_own_and_nothing_is_derived():
    law = parse_gii(GG.read_bytes(), retrieved_on="2026-11-19")
    assert law.enacted_on == "1949-05-23", "ausfertigung-datum, exactly as the portal states it"
    # The file states WHAT last amended it, and when the portal BUILT the file; neither is a
    # point in time the consolidation represents, so there is no validity date to report.
    assert law.valid_on is None
    assert law.retrieved_on == "2026-11-19"
    assert law.document_number == "BJNR000010949"
    assert law.year is None, (
        "no year field is stated; slicing one out of a date would be deriving it"
    )
    assert parse_gii(GG.read_bytes()).retrieved_on is None, (
        "the capture date is the caller's, never invented"
    )


def test_editorial_footnotes_are_left_out_and_COUNTED():
    law = parse_gii(GG.read_bytes())
    assert "Textnachweis" not in law.text, (
        "the documentation service's note is not the enacted text"
    )
    assert law.skipped_parts == {"norms with editorial footnotes": 1}
    assert law.as_dict()["skipped_parts"] == {"norms with editorial footnotes": 1}


def test_a_nested_act_keeps_its_part_and_chapter_and_drops_its_table_of_contents():
    law = parse_gii(BDSG.read_bytes())
    assert law.title == "Bundesdatenschutzgesetz"
    assert law.enacted_on == "2017-06-30"
    paras = [p for p in law.provisions if p.number]
    assert [p.number for p in paras] == ["§ 1", "§ 2", "§ 3"]
    teil = "Teil 1 Gemeinsame Bestimmungen"
    assert paras[0].path == (teil, "Kapitel 1 Anwendungsbereich und Begriffsbestimmungen")
    # Chapter 2 REPLACES chapter 1 under the same part; it does not nest inside it.
    assert paras[2].path == (
        teil,
        "Kapitel 2 Rechtsgrundlagen der Verarbeitung personenbezogener Daten",
    )
    assert paras[0].heading == "Anwendungsbereich des Gesetzes"
    assert "Inhaltsübersicht" not in [p.number for p in law.provisions]
    assert law.skipped_parts["table of contents"] == 1


def test_a_list_marker_does_not_run_into_its_item():
    law = parse_gii(BDSG.read_bytes())
    s1 = next(p for p in law.provisions if p.number == "§ 1").text
    assert "durch 1. öffentliche Stellen des Bundes, 2. öffentliche Stellen der Länder" in s1
    assert "1.öffentliche" not in s1


# ---------------------------------------------------------------------------
# The archive the portal actually serves
# ---------------------------------------------------------------------------


def test_the_archive_reads_exactly_like_the_xml_inside_it():
    xml = GG.read_bytes()
    zipped = _zip({"BJNR000010949.xml": xml, "BJNR000010949.gif": b"GIF89a"})
    assert looks_like_gii(zipped)
    assert parse_gii(zipped).text == parse_gii(xml).text


@pytest.mark.parametrize(
    "members,reason",
    [
        ({"a.gif": b"GIF89a"}, "archive does not hold exactly one XML file"),
        (
            {"a.xml": b"<dokumente/>", "b.xml": b"<dokumente/>"},
            "archive does not hold exactly one XML file",
        ),
    ],
)
def test_an_archive_without_exactly_one_xml_is_refused_by_name(members, reason):
    with pytest.raises(AdapterRefusal) as err:
        unpack_zip(_zip(members))
    assert err.value.reason == reason


def test_a_member_larger_than_the_cap_is_refused_before_it_is_inflated(monkeypatch):
    monkeypatch.setattr(gii, "MAX_XML_BYTES", 1000)
    with pytest.raises(AdapterRefusal) as err:
        unpack_zip(_zip({"a.xml": GG.read_bytes()}))
    assert err.value.reason == "XML member too large"


def test_a_header_that_UNDERSTATES_the_size_cannot_smuggle_a_bigger_member(monkeypatch):
    """The header is the archive's own claim. Rewrite it to say 10 bytes: the bounded read
    must still stop the inflation (or the CRC must refuse the truncation), never hand back
    a member bigger than the cap or a partial act."""
    monkeypatch.setattr(gii, "MAX_XML_BYTES", 1000)
    data = bytearray(_zip({"a.xml": GG.read_bytes()}))
    # local file header: uncompressed size at offset 22
    struct.pack_into("<I", data, 22, 10)
    cd = data.rfind(b"PK\x01\x02")
    struct.pack_into("<I", data, cd + 24, 10)  # central directory: uncompressed size
    with pytest.raises(AdapterRefusal):
        parse_gii(bytes(data))


def test_a_corrupt_or_encrypted_looking_archive_is_a_refusal_not_a_crash():
    good = _zip({"a.xml": GG.read_bytes()})
    with pytest.raises(AdapterRefusal):
        parse_gii(good[:60])  # truncated: magic intact, everything else gone
    flipped = bytearray(good)
    flipped[6] |= 0x01  # the "encrypted" general-purpose flag
    cd = flipped.rfind(b"PK\x01\x02")
    flipped[cd + 8] |= 0x01
    with pytest.raises(AdapterRefusal):
        parse_gii(bytes(flipped))


def test_too_many_members_is_not_an_acts_archive(monkeypatch):
    monkeypatch.setattr(gii, "MAX_MEMBERS", 3)
    members = {f"img{i}.gif": b"GIF89a" for i in range(4)} | {"a.xml": GG.read_bytes()}
    with pytest.raises(AdapterRefusal) as err:
        unpack_zip(_zip(members))
    assert err.value.reason == "archive has too many members"


# ---------------------------------------------------------------------------
# Refusals and the recovery floor
# ---------------------------------------------------------------------------


def test_an_unknown_root_is_refused():
    with pytest.raises(AdapterRefusal) as err:
        parse_gii("<html><body>Wartungsarbeiten</body></html>")
    assert err.value.reason == "not a gesetze-im-internet document"


def test_entity_expansion_is_refused_as_unsafe():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><dokumente>&b;</dokumente>'
    )
    with pytest.raises(AdapterRefusal) as err:
        parse_gii(bomb)
    assert err.value.reason == "unsafe xml refused"


def test_the_portals_own_doctype_line_is_accepted_and_never_fetched():
    """Every real file starts with a DOCTYPE naming the portal's DTD by URL. defusedxml reads
    past it without resolving it; the fixture parsing at all is that proof."""
    assert GG.read_text(encoding="utf-8").count("gii-norm.dtd") == 1
    assert parse_gii(GG.read_bytes()).provisions


def test_a_norm_of_a_shape_the_adapter_does_not_classify_COSTS_recovered_text():
    """The floor is a real check: text under ``textdaten`` that is not in a ``text`` element
    counts in the denominator, so a document made mostly of it is refused."""
    odd = "<anlage>" + "Unbekannter Anlagetext. " * 200 + "</anlage>"
    doc = _doc(_META, _para("§ 1", "Kurz.", extra=odd))
    with pytest.raises(AdapterRefusal) as err:
        parse_gii(doc)
    assert err.value.reason == "too little of the document was recovered"


def test_an_unknown_element_is_counted_and_its_text_is_kept():
    doc = _doc(_META, _para("§ 1", "Erster <neu>besonderer</neu> Satz."))
    law = parse_gii(doc)
    assert law.unknown_elements == {"neu": 1}
    assert law.provisions[0].text == "Erster besonderer Satz."


def test_no_provisions_is_a_refusal():
    with pytest.raises(AdapterRefusal) as err:
        parse_gii(_doc(_META))
    assert err.value.reason == "no provisions found"


def test_the_depth_is_read_from_the_kennzahl_prefix():
    doc = _doc(
        _META,
        _unit("010", "Teil 1", "Eins"),
        _unit("010010", "Kapitel 1", "A"),
        _para("§ 1", "Text eins."),
        _unit("010020", "Kapitel 2", "B"),
        _para("§ 2", "Text zwei."),
        _unit("020", "Teil 2", "Zwei"),
        _para("§ 3", "Text drei."),
    )
    law = parse_gii(doc)
    assert [p.path for p in law.provisions if p.number] == [
        ("Teil 1 Eins", "Kapitel 1 A"),
        ("Teil 1 Eins", "Kapitel 2 B"),
        ("Teil 2 Zwei",),
    ]


def test_a_unit_heading_is_part_of_the_tracked_text_so_a_rename_is_ONE_change():
    def doc(title: str) -> str:
        return _doc(_META, _unit("010", "Teil 1", title), _para("§ 1", "Text eins."))

    before, after = parse_gii(doc("Alt")).text, parse_gii(doc("Neu")).text
    assert "Teil 1 Alt" in before and "Teil 1 Neu" in after
    assert before.replace("Alt", "Neu") == after


def test_an_annex_belongs_to_the_act_not_to_the_last_chapter():
    law = parse_gii(
        _doc(
            _META,
            _unit("010", "Kapitel 15", "Übergangsvorschriften"),
            _para("§ 99", "Letzter Paragraph."),
            _para("Anlage 1", "Anlagentext."),
            _para("Anhang EV", "Maßgaben."),
        )
    )
    by = {p.number: p for p in law.provisions if p.number}
    assert by["§ 99"].path == ("Kapitel 15 Übergangsvorschriften",)
    assert by["Anlage 1"].path == () and by["Anlage 1"].identifier == "Anlage 1"
    assert by["Anhang EV"].path == ()


def test_nesting_past_the_bound_is_refused_and_paths_are_SHARED_not_copied():
    deep = [_unit("1" * (i + 1), f"E{i}", "x") for i in range(gii.MAX_DEPTH + 1)]
    with pytest.raises(AdapterRefusal) as err:
        parse_gii(_doc(_META, *deep, _para("§ 1", "Text.")))
    assert err.value.reason == "structure nested too deeply"

    ok = [_unit("1" * (i + 1), f"E{i}", "x") for i in range(10)]
    law = parse_gii(_doc(_META, *ok, *(_para(f"§ {n}", "Text.") for n in range(1, 50))))
    paths = [p.path for p in law.provisions if p.number]
    assert len(paths[0]) == 10
    assert all(p is paths[0] for p in paths), (
        "one tuple per open structure, never one per provision"
    )


def test_a_deeply_nested_body_does_not_exhaust_the_stack():
    nested = "<P>" * 5000 + "tief" + "</P>" * 5000
    law = parse_gii(_doc(_META, _para("§ 1", nested)))
    assert law.provisions[0].text == "tief"


def test_images_are_counted_and_a_sentence_number_does_not_fuse_with_its_word():
    law = parse_gii(
        _doc(_META, _para("§ 1", '(1) <SUP>1</SUP>Natürliche Personen <IMG SRC="a.gif"/>.'))
    )
    assert law.skipped_parts == {"images": 1}
    assert "1Natürliche" not in law.provisions[0].text
    assert "(1) 1 Natürliche Personen" in law.provisions[0].text


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_adapter_is_reached_through_the_registry():
    assert adapter_for("gii") is parse_gii
    assert parse_with("GII", GG.read_bytes()).format == "gii"


# ---------------------------------------------------------------------------
# Wired into tracking
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, content: str, raw: bytes | None, content_type: str = "application/zip"):
        self.content = content
        self.content_type = content_type
        self.raw_content = raw


def test_the_tracker_reads_the_archive_on_its_RAW_bytes():
    from src.law.track import _document_text

    zipped = _zip({"BJNR000010949.xml": GG.read_bytes()})
    # The text decode of an archive is noise; only the raw bytes can be read.
    text, reason, parsed = _document_text(
        _Result(zipped.decode("latin-1"), zipped), retrieved_on="2026-11-19"
    )
    assert reason == "gii"
    assert parsed is not None and parsed.enacted_on == "1949-05-23"
    assert text == parse_gii(GG.read_bytes()).text


def test_a_refused_archive_stores_NOTHING_rather_than_its_decoded_bytes():
    from src.law.track import _document_text

    junk = _zip({"a.gif": b"GIF89a"})
    text, reason, parsed = _document_text(_Result(junk.decode("latin-1"), junk))
    assert text is None and parsed is None
    assert "refused" in reason and "exactly one XML" in reason


def test_a_refused_bare_xml_is_NOT_stored_as_a_web_page():
    from src.law.track import _document_text

    odd = "<anlage>" + "Unbekannter Anlagetext. " * 200 + "</anlage>"
    xml = _doc(_META, _para("§ 1", "Kurz.", extra=odd))
    text, reason, parsed = _document_text(_Result(xml, xml.encode("utf-8"), "application/xml"))
    assert text is None and parsed is None
    assert reason.startswith("gesetze-im-internet XML refused: too little of the document was recovered")


def test_the_bare_xml_is_read_too_and_html_is_untouched():
    from src.law.track import _document_text

    xml = GG.read_text(encoding="utf-8")
    _t, reason, _p = _document_text(_Result(xml, xml.encode("utf-8"), "application/xml"))
    assert reason == "gii"
    html = "<html><body><main>" + "Ein Absatz über Gesetze. " * 20 + "</main></body></html>"
    _t, reason, parsed = _document_text(_Result(html, html.encode("utf-8"), "text/html"))
    assert reason == "ok" and parsed is None


@pytest.fixture()
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_a_tracked_act_is_baselined_from_its_archive_with_its_signing_date(db, monkeypatch):
    from src.database.models import LawDocument
    from src.ingest import FetchResult
    from src.law import track

    monkeypatch.setattr(track, "_ingest_to_corpus", lambda *a, **k: None)
    monkeypatch.setattr(track, "_record_lane", lambda *a, **k: "recorded")
    zipped = _zip({"BJNR000010949.xml": GG.read_bytes()})

    class _Fetcher:
        def fetch(self, url, *, require_html=True, keep_bytes=False, **_kw):
            assert require_html is False and keep_bytes is True
            return FetchResult(
                requested_url=url,
                final_url=url,
                status_code=200,
                content=zipped.decode("latin-1"),
                content_type="application/zip",
                fetched_at=datetime.now(UTC),
                raw_content=zipped,
            )

    doc = LawDocument(
        jurisdiction="de", title="GG", url="https://www.gesetze-im-internet.de/gg/xml.zip"
    )
    db.add(doc)
    db.commit()
    assert track.track_document(db, _Fetcher(), doc)["status"] == "baseline"
    assert doc.enacted_on == "1949-05-23"
    assert doc.baseline_text.startswith("Eingangsformel")
    assert "PK" not in doc.baseline_text[:10]


# ---------------------------------------------------------------------------
# The catalogue: new stores read the XML, existing stores are not given a second copy
# ---------------------------------------------------------------------------


def test_the_german_acts_are_tracked_from_the_portals_xml():
    from src.law.catalog import load_legal_catalog

    docs = [
        d
        for d in load_legal_catalog()["documents"]
        if "gesetze-im-internet.de" in str(d.get("url"))
    ]
    assert docs, "control: the catalogue tracks German acts"
    for d in docs:
        assert d["url"].endswith("/xml.zip"), d["url"]
        assert any(u.endswith(".html") for u in d.get("previous_urls") or ()), (
            "the old address must be named"
        )


def _catalog(tmp_path, extra: str = "") -> tuple[Path, Path]:
    cat = tmp_path / "cat.yml"
    cat.write_text(
        "sources: []\n"
        "documents:\n"
        "- {jurisdiction: DEU, title: GG, country: DEU, language: de, "
        "url: 'https://www.gesetze-im-internet.de/gg/xml.zip', "
        f"previous_urls: ['https://www.gesetze-im-internet.de/gg/BJNR000010949.html']{extra}}}\n",
        encoding="utf-8",
    )
    return cat, tmp_path / "no-such-generated.yml"


def test_a_store_that_tracked_the_html_keeps_THAT_row_and_gets_no_second_copy(db, tmp_path):
    from src.database.models import LawDocument
    from src.law.catalog import register_documents

    old = LawDocument(
        jurisdiction="DEU",
        title="GG",
        url="https://www.gesetze-im-internet.de/gg/BJNR000010949.html",
    )
    db.add(old)
    db.commit()
    cat, gen = _catalog(tmp_path)
    out = register_documents(db, path=cat, generated_path=gen)
    assert out["created"] == 0
    rows = db.query(LawDocument).all()
    assert [r.url for r in rows] == ["https://www.gesetze-im-internet.de/gg/BJNR000010949.html"], (
        "re-pointing the row would record the change of format as an amendment"
    )
    assert rows[0].language == "de", "the old row is still healed as the same document"


def test_a_new_store_registers_the_xml_address(db, tmp_path):
    from src.database.models import LawDocument
    from src.law.catalog import register_documents

    cat, gen = _catalog(tmp_path)
    assert register_documents(db, path=cat, generated_path=gen)["created"] == 1
    assert [r.url for r in db.query(LawDocument).all()] == [
        "https://www.gesetze-im-internet.de/gg/xml.zip"
    ]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://x.test/a.html", ["https://x.test/a.html"]),
        (42, []),
        ([None, "", 7, " https://x.test/b.html "], ["https://x.test/b.html"]),
        ({"a": 1}, []),
        (None, []),
    ],
)
def test_a_malformed_previous_urls_is_ignored_rather_than_raised(value, expected):
    """Registration runs on the boot path: a catalogue typo must not stop it."""
    from src.law.catalog import _previous_urls

    assert _previous_urls({"previous_urls": value}) == expected


def test_nested_footnotes_are_walked_ONCE_not_once_per_level():
    """A crafted file nesting <fussnoten> thousands deep cost time quadratic in the depth
    when every descendant was searched (8,000 levels, 188 KB of XML, 0.6 KB zipped: 25 s).
    Only the placements the format uses are excluded now; a nested copy is ordinary text,
    so it stays in the denominator, and the document is refused on the floor instead."""
    depth = 20_000
    nested = "<fussnoten>t" * depth + "</fussnoten>" * depth
    doc = _doc(_META, _para("§ 1", "Kurz.", extra="<anlage>" + nested + "</anlage>"))
    with pytest.raises(AdapterRefusal) as err:
        parse_gii(doc)
    assert err.value.reason == "too little of the document was recovered"


def test_the_pre_check_wants_dokumente_as_the_FIRST_element():
    assert looks_like_gii(GG.read_bytes())
    assert looks_like_gii(GG.read_text(encoding="utf-8"))
    assert not looks_like_gii("<html><body><pre>&lt;dokumente&gt; <dokumente></pre></body></html>")
    assert not looks_like_gii("<p>see <dokumente> below</p>")


def test_a_head_of_many_empty_comments_is_answered_in_linear_time():
    """A regular expression with repeated optional comment groups took ~2x longer per extra
    empty comment (22 comments: 4.8 s); a 600-character head holds about 85. The pre-check
    runs on every tracked law body, so it must not be a way to hang the tracking pass."""
    import time

    hostile = "<!---->" * 85 + "<x"
    t0 = time.monotonic()
    assert not looks_like_gii(hostile)
    assert looks_like_gii("<!---->" * 80 + "<dokumente>")  # 571 chars, inside the 600 read
    assert time.monotonic() - t0 < 1.0
    assert looks_like_gii(
        '<?xml version="1.0"?><!-- c --><!DOCTYPE dokumente SYSTEM "x.dtd"><dokumente doknr="1">'
    )
    assert not looks_like_gii("<dokumenteX>")
    assert not looks_like_gii("<!-- never closed <dokumente>")
