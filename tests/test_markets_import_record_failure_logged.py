"""A failed append to ``import_results.jsonl`` is on the record, and the import it describes still stands (R386; the shape of #1647 and #1621).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``POST /api/markets/feeds/import-all`` appends the outcome of every Load/Refresh click to ``import_results.jsonl`` (the debug bundle's ``imports`` member, ruled
2026-06-10). That append sat under ``except Exception: pass``: with a full disk or an unwritable file the click simply never appeared in the bundle, and nothing said why.
The file is made unwritable here by being a DIRECTORY (a real ``IsADirectoryError`` from the real ``open``, no patch of a shared module, R376).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("feedparser", reason="the markets API imports the ingest pipeline (feedparser)")

from src.api import markets
from src.markets.feed_catalog import Feed

FEEDS = [Feed(key="g1", name="G", symbol="G1", category="metals", url="https://f.example/g.csv", currency="USD", unit="t", market="m")]


@pytest.fixture(autouse=True)
def _data(monkeypatch, tmp_path):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.markets.feed_catalog.feeds_for_category", lambda category=None: FEEDS)

    def _fails(*_a, **_k):
        raise RuntimeError("blocked")

    monkeypatch.setattr("src.markets.csv_feeds.import_feed", _fails)


def _run():
    return markets.import_all_feeds(db=SimpleNamespace(rollback=lambda: None))


def test_a_record_that_cannot_be_appended_is_logged_and_the_import_result_is_unchanged(tmp_path, caplog):
    (tmp_path / "import_results.jsonl").mkdir()
    with caplog.at_level("WARNING"):
        out = _run()
    assert out["feeds"] == 1 and out["failed"] == 1, "the import's own result is untouched"
    assert "import_results.jsonl could not be appended" in caplog.text and "IsADirectoryError" in caplog.text, "the lost record is on the record"


def test_with_a_writable_file_nothing_is_logged_and_the_record_is_written(tmp_path, caplog):
    """The control: the same click with a normal file logs nothing and leaves its line."""
    with caplog.at_level("WARNING"):
        _run()
    assert "could not be appended" not in caplog.text
    assert (tmp_path / "import_results.jsonl").read_text(encoding="utf-8").count("\n") == 1
