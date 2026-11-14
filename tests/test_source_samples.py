"""TEMPORARY diagnostic: one random article per source in zips of at most 400 KB (2026-11-08; 400 KB since 2026-11-14).

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
from src.database.models import Article, Base, Source


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[Source.__table__, Article.__table__])
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
    assert man["sources_without_article"]["rows"] == [[2, "s2.example"]]
    assert man["sources_in_this_zip"] == 2
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
    5,000-id batch until it is full, so the sampled source after 12,000 empty ones rides in the same first part."""
    for sid in range(1, 12001):
        db.add(Source(id=sid, name=f"S{sid}", domain=f"empty{sid}.example"))
    db.commit()
    _add(db, 12001, 2)
    data, nxt, covered, total = build_sample_zip(db, after=0, seed=3, cap=400_000)
    assert (nxt, covered, total) == (None, 12001, 12001)
    assert _ids(data) == list(range(1, 12002))
    assert "samples/source-0012001.json" in _open(data).namelist()
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
    import inspect as _inspect

    import importlib

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
