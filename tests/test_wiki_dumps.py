"""
Tests for the offline Wikipedia dump downloader (resumable, no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from src.wiki.dumps import DumpDownloadManager, dump_url


def test_dump_url():
    assert (
        dump_url("en")
        == "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2"
    )
    assert "frwiki" in dump_url("FR")


class FakeResp:
    def __init__(self, *, status_code=200, length=0, chunks=(), headers=None):
        self.status_code = status_code
        self._chunks = list(chunks)
        self.headers = headers or {"Content-Length": str(length)}

    def raise_for_status(self):
        return None

    def iter_content(self, _chunk):
        yield from self._chunks


def test_full_download(tmp_path):
    payload = [b"abc", b"defgh", b"ij"]  # 10 bytes

    def http_get(url, headers):
        assert "Range" not in headers  # first run: no resume
        return FakeResp(status_code=200, length=10, chunks=payload)

    m = DumpDownloadManager(base_dir=tmp_path, http_get=http_get)
    entry = m._entry_for("en", "pages-articles")
    res = m._download(entry)
    assert res.status == "done"
    assert res.downloaded_bytes == 10 and res.total_bytes == 10
    assert Path(res.dest).read_bytes() == b"abcdefghij"
    # state persisted
    assert any(e["status"] == "done" for e in m.list())


def test_resume_appends(tmp_path):
    m = DumpDownloadManager(base_dir=tmp_path, http_get=None)
    entry = m._entry_for("fr", "pages-articles")
    Path(entry.dest).write_bytes(b"HEAD")  # 4 bytes already on disk

    def http_get(url, headers):
        assert headers.get("Range") == "bytes=4-"  # resumes from offset
        return FakeResp(status_code=206, length=3, chunks=[b"TAI", b"L"])

    m._http_get = http_get
    res = m._download(entry)
    assert res.status == "done"
    assert Path(res.dest).read_bytes() == b"HEADTAIL"
    assert res.total_bytes == 4 + 3  # resume + Content-Length of the partial


def test_pause_via_stop_event(tmp_path):
    import threading

    def http_get(url, headers):
        return FakeResp(status_code=200, length=100, chunks=[b"x" * 10 for _ in range(10)])

    m = DumpDownloadManager(base_dir=tmp_path, http_get=http_get)
    entry = m._entry_for("de", "pages-articles")
    stop = threading.Event()
    stop.set()  # already requested -> stop immediately
    res = m._download(entry, stop_event=stop)
    assert res.status == "paused"


def test_probe_and_delete(tmp_path):
    def http_head(url):
        return FakeResp(headers={"Content-Length": "12345"})

    m = DumpDownloadManager(base_dir=tmp_path, http_head=http_head)
    assert m.probe_size("en") == 12345
    entry = m._entry_for("en", "pages-articles")
    Path(entry.dest).write_bytes(b"data")
    assert m.delete(entry.key) is True
    assert not Path(entry.dest).exists()
    assert m.list() == []
