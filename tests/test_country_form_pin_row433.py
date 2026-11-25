"""Row 433: one article's index pass reads the store's country form once, not once per bound country.

``CountryCode.process_bind_param`` asked ``store_form()`` for every country value it bound; each ask resolved the data
folder and took the settings lock twice, which was 13% of the drain writer's time (row 431's profile, 2k articles).
``index_article`` now runs inside ``form_pinned_for_this_write``: the first bind of the pass reads the form (on the
connection the pass holds, after R788's per-connection recheck), and the later binds of the same pass use that answer.

Pinned here:
- inside a block, many binds read the form once; outside, every bind reads it, exactly as before;
- a refusal is never kept: the next bind asks again and raises again;
- ``writing_in`` still wins inside a block, a nested block keeps the outer answer, and nothing crosses threads or
  outlives the block;
- only binds use the kept answer: ``store_form()`` called directly inside a block still reads;
- ``index_article`` reads the form once per article and writes exactly the rows it wrote before, in an alpha-3 store.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.analytics import store
from src.analytics.extract import BaselineExtractor
from src.database import country_form
from src.database.country_form import (
    CountryCode,
    MigrationUnfinished,
    form_pinned_for_this_write,
    writing_in,
)
from src.database.models import Article, Base, Source
from tests._app_engine import app_sqlite_engine


class _Counter:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        answer = self.answers[min(self.calls, len(self.answers)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _bind(value: str):
    return CountryCode().process_bind_param(value, None)


def test_inside_a_block_many_binds_read_the_form_once(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _Counter(["alpha3"])
    monkeypatch.setattr(country_form, "store_form", reads)
    with form_pinned_for_this_write():
        assert [_bind(v) for v in ("fr", "de", "us", "fr")] == ["FRA", "DEU", "USA", "FRA"]
    assert reads.calls == 1


def test_outside_a_block_every_bind_reads_the_form_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _Counter(["alpha3"])
    monkeypatch.setattr(country_form, "store_form", reads)
    assert [_bind(v) for v in ("fr", "de", "us")] == ["FRA", "DEU", "USA"]
    assert reads.calls == 3


def test_a_new_block_reads_again(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _Counter(["alpha3", "alpha2"])
    monkeypatch.setattr(country_form, "store_form", reads)
    with form_pinned_for_this_write():
        assert _bind("fr") == "FRA"
    with form_pinned_for_this_write():
        assert _bind("fr") == "fr"
    assert reads.calls == 2


def test_a_refusal_is_never_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _Counter([MigrationUnfinished("a run began and did not end"), MigrationUnfinished("still"), "alpha3"])
    monkeypatch.setattr(country_form, "store_form", reads)
    with form_pinned_for_this_write():
        with pytest.raises(MigrationUnfinished):
            _bind("fr")
        with pytest.raises(MigrationUnfinished):
            _bind("fr")
        assert _bind("fr") == "FRA"
        assert _bind("de") == "DEU"
    assert reads.calls == 3


def test_writing_in_still_wins_inside_a_block(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _Counter(["alpha3"])
    monkeypatch.setattr(country_form, "store_form", reads)
    with form_pinned_for_this_write():
        assert _bind("fr") == "FRA"
        with writing_in("alpha2"):
            assert _bind("fr") == "fr"
        assert _bind("fr") == "FRA"
    assert reads.calls == 1


def test_a_nested_block_keeps_the_outer_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _Counter(["alpha3", "alpha2"])
    monkeypatch.setattr(country_form, "store_form", reads)
    with form_pinned_for_this_write():
        assert _bind("fr") == "FRA"
        with form_pinned_for_this_write():
            assert _bind("de") == "DEU"
        assert _bind("us") == "USA"
    assert reads.calls == 1


def test_nothing_crosses_threads_or_outlives_the_block(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = _Counter(["alpha3"])
    monkeypatch.setattr(country_form, "store_form", reads)
    seen: list[str] = []
    with form_pinned_for_this_write():
        _bind("fr")
        t = threading.Thread(target=lambda: seen.append(_bind("de")))
        t.start()
        t.join()
    assert seen == ["DEU"]
    assert reads.calls == 2  # the other thread read for itself
    _bind("us")
    assert reads.calls == 3  # and after the block every bind reads again


def test_only_binds_use_the_kept_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A direct ``store_form()`` call (``alpha2_order`` building a query, a diagnostics read) may run before the caller
    holds a connection, so it never takes a kept answer: it reads, as it always did."""
    calls = {"n": 0}

    def _read():
        calls["n"] += 1
        return "alpha3"

    from src.config import kv_store

    def _kv(key):
        if key != country_form.KEY:
            return None
        _read()
        return {"form": "alpha3"}

    monkeypatch.setattr(kv_store, "kv_get_json_checked", _kv)
    with form_pinned_for_this_write():
        country_form.store_form()
        country_form.store_form()
    assert calls["n"] == 2


def test_index_article_is_the_block() -> None:
    assert getattr(store.index_article, "__wrapped__", None) is not None


_TEXT = (
    "President Emmanuel Macron met the World Health Organization in Geneva on 3 March 2024. Paris and Berlin agreed "
    "on trade, energy prices and the budget. Minister John Smith spoke in Lagos about inflation and growth."
)


def _session():
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    for i in range(3):
        s.add(Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title=f"T{i}", content=_TEXT,
            hash=f"h{i}", language="en", country="fr", published_at=datetime(2024, 6, 1, tzinfo=UTC),
            created_at=datetime.now(UTC),
        ))
    s.commit()
    return s


_TABLES = ("keyword_mentions", "article_mentioned_places", "article_entities", "articles")


def _rows(s) -> dict:
    """Every column but the clocks (two runs cannot share one), every row, in id order."""
    out = {}
    for table in _TABLES:
        cols = [r[1] for r in s.execute(text(f"PRAGMA table_info({table})")) if not r[1].endswith("_at")]
        out[table] = s.execute(text(f"SELECT {', '.join(cols)} FROM {table} ORDER BY id")).all()
    return out


def test_index_article_reads_the_form_once_per_article_and_writes_the_same_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """In an alpha-3 store, every country a pass binds is converted; with the pin the conversion is the same and the
    form is read once per article instead of once per bound value."""
    real = country_form.store_form
    results = {}
    reads = {"n": 0}

    def _alpha3():
        reads["n"] += 1
        return "alpha3"

    monkeypatch.setattr(country_form, "store_form", _alpha3)
    for label, fn in (("before", store.index_article.__wrapped__), ("after", store.index_article)):
        s = _session()
        reads["n"] = 0  # the setup's own inserts bind countries too; count only the passes
        for a in s.query(Article).order_by(Article.id).all():
            fn(s, a, extractor=BaselineExtractor(), country="fr", city="Paris")
        results[label] = (_rows(s), reads["n"])
        s.close()
    monkeypatch.setattr(country_form, "store_form", real)
    (before_rows, before_reads), (after_rows, after_reads) = results["before"], results["after"]
    assert before_rows == after_rows
    assert {r.country for r in before_rows["keyword_mentions"]} == {"FRA"}
    assert after_reads == 3, "one read of the form per article"
    assert before_reads > 3 * 10, "the unpinned pass read it once per bound country"
