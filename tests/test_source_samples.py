"""TEMPORARY diagnostic: one random article per source in zips of at most 4 MB (2026-11-08).

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


def test_one_article_per_source_and_a_manifest_row_for_an_empty_source(db):
    _add(db, 1, 3)
    _add(db, 2, 0)
    data, nxt, covered, total = build_sample_zip(db, after=0, seed=1, cap=4_000_000)
    z = _open(data)
    man = json.loads(z.read("manifest.json"))
    assert (nxt, covered, total) == (None, 2, 2)
    assert [r["source_id"] for r in man["sources"]] == [1, 2]
    assert man["sources"][1]["article_id"] is None
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
        seen += [r["source_id"] for r in json.loads(_open(data).read("manifest.json"))["sources"]]
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
        seen += [r["source_id"] for r in json.loads(_open(data).read("manifest.json"))["sources"]]
        if nxt is None:
            break
        after = nxt
    assert seen == list(range(1, 3001))
