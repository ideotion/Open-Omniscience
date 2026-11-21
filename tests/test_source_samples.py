"""TEMPORARY diagnostic: one random article per source in zips of at most 200 KB (2026-11-08; 400 KB since 2026-11-14, 200 KB since 2026-11-15).

Delete with the diagnostic. Driven on an in-memory database through the builder itself; the
route's wiring is pinned by test_diagnostics_package_split.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.api.diagnostics.source_samples import _SECRETISH, build_sample_zip
from src.database.models import Article, Base, FeedFetchState, Source, SourceQualificationAttempt


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[Source.__table__, Article.__table__, SourceQualificationAttempt.__table__,
                                          FeedFetchState.__table__])
    with Session(eng) as s:
        yield s


def _add(db, sid, n, size=200):
    db.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.example"))
    db.flush()
    for i in range(n):
        db.add(Article(url=f"https://s{sid}.example/{i}", canonical_url=f"https://s{sid}.example/{i}",
                       source_id=sid, title=f"t{i}", content="x " * size + f"{sid}-{i}",
                       hash=f"{sid:030d}{i:034d}"))
    db.commit()


def _open(data):
    return zipfile.ZipFile(io.BytesIO(data))


def _ids(data):
    """Every source a zip covers: the sampled ones and the compact list of sources with no stored article."""
    man = json.loads(_open(data).read("manifest.json"))
    return sorted([r["source_id"] for r in man["sources"]] + [r[0] for r in man["sources_without_article"]["rows"]])


def test_one_article_per_source_and_a_manifest_row_for_an_empty_source(db):
    _add(db, 1, 3)
    _add(db, 2, 0)
    data, nxt, covered, total = build_sample_zip(db, after=0, seed=1, cap=4_000_000)
    z = _open(data)
    man = json.loads(z.read("manifest.json"))
    assert (nxt, covered, total) == (None, 2, 2)
    assert [r["source_id"] for r in man["sources"]] == [1]
    # field report 2026-11-14 5.4: ids above the shipped catalogue differ across instances, so each row carries the join key
    assert man["sources_without_article"]["rows"] == [[2, "s2.example", "", 0]]
    assert man["sources_without_article"]["columns"] == ["source_id", "domain", "feed_key", "class"]
    assert man["sources"][0]["domain"] == "s1.example" and man["sources"][0]["feed_key"] == ""
    assert man["sources_in_this_zip"] == 2
    from src.paths import instance_tag

    assert man["instance"] == instance_tag() and len(man["instance"]) == 8   # a hash of the data folder, never its path
    names = z.namelist()
    assert "samples/source-0000001.json" in names and "samples/source-0000002.json" not in names
    doc = json.loads(z.read("samples/source-0000001.json"))
    assert doc["article"]["source_id"] == 1 and doc["source"]["domain"] == "s1.example"
    assert "content" in doc["article"] and not any(_SECRETISH.search(k) for k in doc["article"])


def test_the_pick_is_a_function_of_seed_and_source(db):
    _add(db, 1, 20)
    a = build_sample_zip(db, after=0, seed=7, cap=4_000_000)[0]
    b = build_sample_zip(db, after=0, seed=7, cap=4_000_000)[0]
    pick = lambda d: json.loads(_open(d).read("manifest.json"))["sources"][0]["article_id"]  # noqa: E731
    assert pick(a) == pick(b)


def test_zips_stay_under_the_cap_and_the_cursor_covers_every_source_once(db):
    import os
    for sid in range(1, 41):
        _add(db, sid, 1, size=int.from_bytes(os.urandom(2), "big") % 2000 + 500)
    cap, after, seen, parts = 30_000, 0, [], 0
    while True:
        data, nxt, _c, _t = build_sample_zip(db, after=after, seed=3, cap=cap)
        assert len(data) <= cap, len(data)
        seen += _ids(data)
        parts += 1
        if nxt is None:
            break
        after = nxt
    assert seen == list(range(1, 41)) and parts > 1


def test_a_long_run_of_empty_sources_cannot_push_a_zip_past_the_cap(db):
    for sid in range(1, 3001):
        db.add(Source(id=sid, name=f"S{sid}", domain=f"empty{sid}.example"))
    db.commit()
    cap, after, seen = 20_000, 0, []
    while True:
        data, nxt, _c, _t = build_sample_zip(db, after=after, seed=3, cap=cap)
        assert len(data) <= cap, len(data)
        seen += _ids(data)
        if nxt is None:
            break
        after = nxt
    assert seen == list(range(1, 3001))


def test_a_long_run_of_never_collected_sources_does_not_make_parts_of_its_own(db):
    """The 2026-11-14 press: five parts in a row held only sources with no article. Now one zip reads past the
    5,000-id batch until it is full, so the sampled source after 10,000 empty ones rides in the same first part."""
    for sid in range(1, 10001):
        db.add(Source(id=sid, name=f"S{sid}", domain=f"empty{sid}.example"))
    db.commit()
    _add(db, 10001, 2)
    data, nxt, covered, total = build_sample_zip(db, after=0, seed=3, cap=400_000)
    assert (nxt, covered, total) == (None, 10001, 10001)
    assert _ids(data) == list(range(1, 10002))
    assert "samples/source-0010001.json" in _open(data).namelist()
    assert len(data) < 200_000, len(data)


def _newsletters(db):
    """A mailbox source, a publisher with one auto-attached newsletter, and a web source."""
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    db.add(Source(id=1, name="Mail", domain=NEWSLETTER_SOURCE_DOMAINS[0]))
    db.add(Source(id=2, name="Pub", domain="pub.example"))
    db.add(Source(id=3, name="Web", domain="web.example"))
    db.flush()
    db.add(Article(url="mail://1", canonical_url="mail://1", source_id=1, title="m",
                   content="PRIVATE-MAILBOX-BODY", hash="1" * 64))
    db.add(Article(url="https://pub.example/n", canonical_url="https://pub.example/n", source_id=2, title="n",
                   content="PRIVATE-ATTACHED-BODY", hash="2" * 64, newsletter_attached_via="list-id"))
    db.add(Article(url="https://web.example/a", canonical_url="https://web.example/a", source_id=3, title="w",
                   content="PUBLIC-WEB-BODY", hash="3" * 64))
    db.commit()


def _bodies(data):
    z = _open(data)
    return b"".join(z.read(n) for n in z.namelist())


def test_a_newsletter_body_stays_home_unless_the_operator_switch_is_on(db, monkeypatch):
    """R655: the same gate as /source-quality. A mailbox source's body and an auto-attached newsletter's
    body under a publisher's source are withheld; a public web article's body is written."""
    import importlib

    mod = importlib.import_module("src.api.diagnostics.source_samples")

    _newsletters(db)
    data = build_sample_zip(db, after=0, seed=1, cap=4_000_000)[0]
    blob = _bodies(data)
    assert b"PRIVATE-MAILBOX-BODY" not in blob and b"PRIVATE-ATTACHED-BODY" not in blob
    assert b"PUBLIC-WEB-BODY" in blob
    rows = {r["source_id"]: r for r in json.loads(_open(data).read("manifest.json"))["sources"]}
    assert rows[1].get("body_withheld") and rows[2].get("body_withheld") and not rows[3].get("body_withheld")
    # the operator's switch lets them out, as on /source-quality
    blob = _bodies(build_sample_zip(db, after=0, seed=1, cap=4_000_000, include_newsletters=True)[0])
    assert b"PRIVATE-MAILBOX-BODY" in blob and b"PRIVATE-ATTACHED-BODY" in blob
    # the route reads the switch: off by default
    monkeypatch.delenv("OO_QUALITY_INCLUDE_NEWSLETTER_TEXT", raising=False)
    assert mod.include_newsletter_text() is False
    monkeypatch.setenv("OO_QUALITY_INCLUDE_NEWSLETTER_TEXT", "1")
    assert mod.include_newsletter_text() is True


def test_the_route_passes_the_switch_to_the_builder():
    import importlib
    import inspect as _inspect

    mod = importlib.import_module("src.api.diagnostics.source_samples")

    src = _inspect.getsource(mod.source_samples)
    assert "include_newsletters=include_newsletter_text()" in src


def test_one_huge_article_cannot_push_its_part_past_the_cap(db):
    """The 2026-11-14 delta read: the first source of a part is always admitted, so its text is cut by UTF-8 bytes.
    Random CJK text barely compresses, which is the worst case."""
    import random

    from src.api.diagnostics.source_samples import SAMPLE_ZIP_MAX_BYTES

    rnd = random.Random(5)
    db.add(Source(id=1, name="S1", domain="s1.example"))
    db.flush()
    db.add(Article(url="https://s1.example/a", canonical_url="https://s1.example/a", source_id=1, title="t",
                   content="".join(chr(rnd.randrange(0x4E00, 0x9FFF)) for _ in range(1_000_000)), hash="9" * 64))
    db.commit()
    data, nxt, covered, _t = build_sample_zip(db, after=0, seed=1, cap=SAMPLE_ZIP_MAX_BYTES)
    assert len(data) <= SAMPLE_ZIP_MAX_BYTES, len(data)
    man = json.loads(_open(data).read("manifest.json"))
    assert (nxt, covered) == (None, 1) and man["sources"][0]["text_truncated"] is True


def test_a_source_without_an_article_writes_its_kept_key_masked(db):
    """Row 75's join key on the compact rows: a key kept from before R628 can hold a login, written as the samples write it."""
    from sqlalchemy import text

    db.add(Source(id=1, name="S1", domain="news.example"))
    db.commit()
    # written round the ORM, as a build before R628 left it (the ORM derives a fresh key without the login)
    db.execute(text("UPDATE sources SET feed_key = :k WHERE id = 1"), {"k": "f:alice:hunter2@news.example/rss"})
    db.commit()
    data = build_sample_zip(db, after=0, seed=1, cap=4_000_000)[0]
    assert b"hunter2" not in _open(data).read("manifest.json")
    man = json.loads(_open(data).read("manifest.json"))
    assert man["sources_without_article"]["rows"] == [[1, "news.example", "f:***@news.example/rss", 0]]


def test_every_address_column_is_written_as_a_report_writes_it(db):
    """Row 104 on R734/R736: the sample's own rows (the source's feed address, its catalogue baseline's, the article's two
    addresses) hide their query values and path tokens; the article's body is the sample and is left as stored."""
    import json as _json

    uuid = "3f2b9c1e-1a2b-4c3d-8e9f-0123456789ab"
    db.add(Source(id=1, name="S1", domain="s1.example", rss_url="https://s1.example/rss?token=SourceTokenAAAA1111",
                  catalog_baseline=_json.dumps({"rss_url": "https://s1.example/rss?key=BaselineTokenBBBB2222", "region": "EU"})))
    db.flush()
    db.add(Article(url="https://s1.example/a?sid=ArticleTokenCCCC3333", canonical_url=f"https://s1.example/p/{uuid}",
                   source_id=1, title="t", content="body keeps https://s1.example/x?sid=BodyLinkDDDD4444", hash="1" * 64))
    db.commit()
    data = build_sample_zip(db, after=0, seed=1, cap=4_000_000)[0]
    everything = b"".join(_open(data).read(n) for n in _open(data).namelist())
    for secret in (b"SourceTokenAAAA1111", b"BaselineTokenBBBB2222", b"ArticleTokenCCCC3333", uuid.encode()):
        assert secret not in everything, secret
    assert b"BodyLinkDDDD4444" in everything, "the article's body is the sample: its words are kept"
    assert b'"region": "EU"' in everything or b'\\"region\\": \\"EU\\"' in everything, "the baseline's other fields were lost"


def test_a_never_collected_source_says_why_by_class_and_the_first_zip_counts_the_whole_set(db):
    """Row 248 (from row 39): about 25,000 sources of one press had no article and the list could not say why. Each row now
    indexes a class (enabled, status, via tag, has a feed, last qualification verdict, last feed HTTP status), and the
    first zip counts every never-collected source by class. Booleans and short codes only: no address leaves (R734)."""
    from datetime import datetime

    _add(db, 1, 2)
    db.add(Source(id=2, name="Cand", domain="cand.example", enabled=False, status="unqualified",
                  tags="news,via:wikidata-discovery"))
    db.add(Source(id=3, name="Cand2", domain="cand2.example", enabled=False, status="unqualified",
                  tags="via:wikidata-discovery"))
    db.add(Source(id=4, name="Dead", domain="dead.example", enabled=True, status="qualified",
                  rss_url="https://alice:hunter2@dead.example/rss?token=abc", tags="via:curated"))
    db.flush()
    db.add(SourceQualificationAttempt(source_id=3, attempted_at=datetime(2026, 11, 1), verdict="no_evidence",
                                      criteria_version="v"))
    db.add(FeedFetchState(source_id=4, last_status=404, last_checked_at=datetime(2026, 11, 2)))
    db.commit()

    data, nxt, _c, _t = build_sample_zip(db, after=0, seed=1, cap=4_000_000)
    assert nxt is None
    raw = _open(data).read("manifest.json")
    assert b"hunter2" not in raw and b"token=abc" not in raw   # the feed key keeps its own R734 mask; a class says only True
    man = json.loads(raw)
    block = man["sources_without_article"]
    assert block["classes"]["columns"] == ["enabled", "status", "via", "has_feed", "last_qualification",
                                           "last_feed_status", "sources_in_this_zip"]
    by_id = {r[0]: block["classes"]["rows"][r[3]] for r in block["rows"]}
    assert by_id[2] == [False, "unqualified", "wikidata-discovery", False, None, None, 1]
    assert by_id[3] == [False, "unqualified", "wikidata-discovery", False, "no_evidence", None, 1]
    assert by_id[4] == [True, "qualified", "curated", True, None, 404, 1]
    tally = man["never_collected_in_set"]
    assert tally["sources"] == 3 and tally["columns"][-1] == "sources"
    assert sorted(tally["rows"], key=str) == sorted([r[:-1] + [1] for r in block["classes"]["rows"]], key=str)


def test_the_whole_set_tally_rides_in_the_first_zip_only_and_one_class_is_written_once(db):
    for sid in range(1, 301):
        db.add(Source(id=sid, name=f"S{sid}", domain=f"c{sid}.example", enabled=False, tags="via:wikidata-discovery"))
    db.commit()
    first, nxt, _c, _t = build_sample_zip(db, after=0, seed=3, cap=6_000)
    assert nxt is not None
    man = json.loads(_open(first).read("manifest.json"))
    assert man["never_collected_in_set"]["rows"] == [[False, "unqualified", "wikidata-discovery", False, None, None, 300]]
    assert len(man["sources_without_article"]["classes"]["rows"]) == 1
    assert {r[3] for r in man["sources_without_article"]["rows"]} == {0}
    later, _n, _c, _t = build_sample_zip(db, after=nxt, seed=3, cap=6_000)
    assert "never_collected_in_set" not in json.loads(_open(later).read("manifest.json"))
    assert len(first) <= 6_000 and len(later) <= 6_000


def test_a_via_tag_is_a_code_or_other_never_free_text():
    from src.api.diagnostics.source_samples import _via

    assert _via("news,via:wikidata-discovery") == "wikidata-discovery"
    assert _via("via:Some Free Text, typed") == "other"
    assert _via("news") is None and _via(None) is None
    # Review of #2203: a lowercase slug a catalogue entry typed itself is not copied out, a tag that merely
    # contains "via:" is not a provenance, and the known codes win over an unknown one on the same row.
    assert _via("via:alice-hunter2-at-host") == "other"
    assert _via("via:some free text") == "other"
    assert _via("trivia:quiz") is None
    assert _via("via:curated,via:zz-token") == "curated"
    assert _via("x, via:legal-generated ") == "legal-generated"


def test_the_whole_set_tally_lists_its_largest_classes_and_counts_the_rest(db, monkeypatch):
    import importlib

    ss = importlib.import_module("src.api.diagnostics.source_samples")

    monkeypatch.setattr(ss, "_TALLY_MAX_CLASSES", 2)
    # three never-collected classes: by feed (2 sources), by status (1), and the plain one (3)
    for sid in range(1, 4):
        db.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.example"))
    for sid in range(4, 6):
        db.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.example", rss_url=f"https://s{sid}.example/rss"))
    db.add(Source(id=6, name="S6", domain="s6.example", status="disqualified"))
    db.commit()
    tally = ss.never_collected_in_set(db)
    assert [r[-1] for r in tally["rows"]] == [3, 2]
    assert tally["classes_left_out"] == 1 and tally["sources_in_classes_left_out"] == 1
    assert tally["sources"] == 6 and "null = the collector never checked" in tally["feed_status_note"]
