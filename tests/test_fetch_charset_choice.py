"""A fetched page's bytes are decoded in the encoding they are in (R699, cause 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-10-06 keyword triage found Chinese keywords such as ``еӣҫе``: UTF-8 Chinese read as
the Kazakh single-byte charset ``ptcp154``. ``charset_normalizer`` answers exactly that for a
UTF-8 page with one stray invalid byte or a body cut mid-character, and the fetcher asked it
whenever a server named no charset. These tests pin the order of evidence in
``src/ingest/charset.py`` and drive the fetcher's own body reader end to end.
"""

from __future__ import annotations

import codecs

import requests

from src.ingest import EthicalFetcher
from src.ingest.charset import choose_encoding, looks_like_utf8, meta_charset

ZH_PAGE = (
    '<html><head><title>新闻</title><script>var a=1;</script></head><body>'
    + '<div class="x">' * 30
    + "<p>图片来源：新华社。中国国务院今天发布了关于经济发展的新政策。</p>"
    + "</div>" * 30
    + "</body></html>"
).encode("utf-8")
ZH_WITH_STRAY_BYTE = ZH_PAGE.replace(b"</body>", b"\xff</body>")
ZH_CUT_MID_CHARACTER = ZH_PAGE + "图".encode()[:2]
RU_CP1251 = (
    "<html><body><p>Правительство России в четверг представило проект бюджета на следующий "
    "год, в котором расходы на социальные программы увеличены.</p></body></html>"
).encode("cp1251")


# --------------------------------------------------------------------------- #
# the decision
# --------------------------------------------------------------------------- #
def test_a_utf8_page_with_one_stray_byte_is_still_utf8():
    assert choose_encoding(ZH_WITH_STRAY_BYTE, None) == "utf-8"
    assert choose_encoding(ZH_CUT_MID_CHARACTER, None) == "utf-8"
    assert "图片来源" in ZH_WITH_STRAY_BYTE.decode(choose_encoding(ZH_WITH_STRAY_BYTE, None), "replace")


def test_requests_default_latin1_does_not_override_utf8():
    assert choose_encoding(ZH_PAGE, "ISO-8859-1") == "utf-8"


def test_a_utf8_body_overrides_a_declared_single_byte_charset():
    assert choose_encoding(ZH_PAGE, "windows-1251") == "utf-8"


def test_a_real_single_byte_page_keeps_its_declared_charset():
    assert not looks_like_utf8(RU_CP1251)
    assert choose_encoding(RU_CP1251, "windows-1251") == "cp1251"


def test_an_unlabelled_single_byte_page_reads_its_meta_declaration():
    page = b'<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1251">' + RU_CP1251
    assert meta_charset(page) == "cp1251"
    assert choose_encoding(page, None) == "cp1251"
    assert choose_encoding(page, "ISO-8859-1") == "cp1251"


def test_a_byte_order_mark_wins():
    body = codecs.BOM_UTF16_LE + "新闻 news".encode("utf-16-le")
    assert choose_encoding(body, "windows-1251") == "utf-16"
    assert choose_encoding(codecs.BOM_UTF8 + ZH_PAGE, None) == "utf-8-sig"


def test_a_declared_utf16_body_is_honoured():
    assert choose_encoding("news only".encode("utf-16-le"), "UTF-16LE") == "utf-16-le"


def test_a_meta_declaring_utf16_reads_as_utf8():
    assert meta_charset(b'<meta charset="utf-16">') == "utf-8"


def test_an_unknown_label_is_ignored():
    assert meta_charset(b'<meta charset="no-such-charset">') is None
    assert choose_encoding(ZH_PAGE, "no-such-charset") == "utf-8"


def test_every_answer_is_a_codec_python_knows():
    for raw, declared in [
        (ZH_PAGE, None), (RU_CP1251, None), (b"", None), (b"\x80\x81\x82", "x-weird"),
    ]:
        codecs.lookup(choose_encoding(raw, declared))


# --------------------------------------------------------------------------- #
# the fetcher's body reader, end to end
# --------------------------------------------------------------------------- #
class _Streamed:
    def __init__(self, body: bytes, encoding: str | None):
        self._body = body
        self.encoding = encoding
        self.headers = {"Content-Type": "text/html"}

    def iter_content(self, chunk_size=16384):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        pass


def _read(body: bytes, encoding: str | None) -> str:
    # A real requests.Session selects the streamed branch real fetches take; nothing is
    # sent, because _read_body is handed the response directly.
    f = EthicalFetcher(min_interval_s=0.0, session=requests.Session())
    text, _ = f._read_body(_Streamed(body, encoding), "https://example.com/a")
    return text


def test_the_fetcher_decodes_a_unlabelled_utf8_page_with_a_stray_byte_as_utf8():
    text = _read(ZH_WITH_STRAY_BYTE, None)
    assert "图片来源" in text
    assert "еӣҫ" not in text


def test_the_fetcher_decodes_a_latin1_defaulted_utf8_page_as_utf8():
    assert "中国国务院" in _read(ZH_CUT_MID_CHARACTER, "ISO-8859-1")


def test_the_fetcher_still_reads_a_declared_single_byte_page():
    assert "Правительство" in _read(RU_CP1251, "windows-1251")
