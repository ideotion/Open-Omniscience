"""R736 (2026-11-17): path tokens in an address written to a report, field data, a diagnostics bundle or a log line are masked by the
R734 helper (``src.database.address_mask``), by SHAPE: a ``;name=value`` path parameter's value always, and a segment shaped like a
credential. Slugs, dates, numeric ids and short segments read as they are; over-masking is the accepted cost.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.database.address_mask import QUERY_VALUE_MASK, masked_address, masked_path, query_secrets
from src.database.feed_key import shown_feed_key
from src.ingest.fetch_verdict import address_secrets, failure_url, reported_url, shown_url

M = QUERY_VALUE_MASK


@pytest.mark.parametrize(
    ("address", "written"),
    [
        # R736 (4): a token in the path
        ("https://h.example/rss/ghp_abcdefghijklmnopqrstuvwxyz0123", f"https://h.example/rss/{M}"),
        ("https://h.example/rss/AbCdEfGhIjKlMnOpQrStUvWx12", f"https://h.example/rss/{M}"),
        ("https://h.example/f/0123456789abcdef0123/rss", f"https://h.example/f/{M}/rss"),
        ("https://h.example/feed/3f2b1c4d-1a2b-3c4d-5e6f-0123456789ab", f"https://h.example/feed/{M}"),
        ("https://h.example/feeds/AbCdEfGhIjKlMnOpQrStUvWx12.xml", f"https://h.example/feeds/{M}.xml"),  # the extension stays
        # R736 (1): path parameters, the value only
        ("https://h.example/rss;jsessionid=ABC;x=1?page=2", f"https://h.example/rss;jsessionid={M};x={M}?page=2"),
        ("https://h.example/rss;bare", f"https://h.example/rss;{M}"),
        # R736 (4): what stays readable
        ("https://h.example/news/2026/11/16/climate-report-2025-cop30-update", None),  # a long slug with digits, a dated path
        ("https://h.example/item/123456789012345", None),  # a numeric id under sixteen digits
        ("https://h.example/2026-11-16/x", None),
        ("https://h.example/a/the_quick_brown_fox_jumps_over_2025", None),
        ("https://h.example/rss", None),
        ("https://h.example", None),
        ("https://h.example/", None),
    ],
)
def test_a_path_is_masked_by_shape(address, written):
    assert masked_address(address) == (address if written is None else written)


def test_a_long_numeric_id_is_hex_shaped_and_masked_over_masking_is_the_accepted_cost():
    """Sixteen or more digits are also sixteen hex digits: masked, as R736 (3) accepts."""
    assert masked_address("https://h.example/item/1234567890123456") == f"https://h.example/item/{M}"


def test_the_authority_is_never_read_as_a_path():
    host = "abcdefghijklmnopqrstuvwxyz0123456789.example"
    assert masked_address(f"https://{host}/rss") == f"https://{host}/rss"
    assert masked_address(f"//{host}/rss") == f"//{host}/rss"


def test_masking_is_stable_and_never_raises():
    url = "https://h.example/rss/AbCdEfGhIjKlMnOpQrStUvWx12;s=1"
    assert {masked_address(url) for _ in range(5)} == {f"https://h.example/rss/{M};s={M}"}
    assert masked_path("/a\ud800/b") == "/a\ud800/b"


def test_every_report_writer_masks_the_path_and_the_ui_answer_does_not():
    url = "https://alice:pw@h.example/rss/AbCdEfGhIjKlMnOpQrStUvWx12?token=abcdef"
    assert failure_url(url) == f"https://***@h.example/rss/{M}?token={M}"
    assert reported_url(url) == failure_url(url)
    assert shown_feed_key("f:h.example/rss/AbCdEfGhIjKlMnOpQrStUvWx12") == f"f:h.example/rss/{M}"
    assert shown_url(url) == "https://***@h.example/rss/AbCdEfGhIjKlMnOpQrStUvWx12?token=abcdef"  # R637's form, an edit form sends it back


def test_the_scrub_takes_out_a_masked_path_token_in_every_spelling():
    url = "https://h.example/rss/AbCdEfGhIjKlMnOpQrStUvWx12;jsessionid=SESSION99/x?token=abcdef"
    secrets = set(address_secrets(url))
    assert {"AbCdEfGhIjKlMnOpQrStUvWx12", "SESSION99", "abcdef"} <= secrets
    assert "rss" not in secrets and "x" not in secrets
    assert "3f2b1c4d-1a2b-3c4d-5e6f-0123456789ab" in query_secrets("https://h.example/f/3f2b1c4d-1a2b-3c4d-5e6f-0123456789ab.xml")


_U = "3f2b9c1e-1a2b-4c3d-8e9f-0123456789ab"
_B = "AbCdEf0123456789ghIjKlMnOp"


@pytest.mark.parametrize(
    "address",
    [
        f"https://h/{_U}%2F{_U}",  # an encoded slash between two tokens
        f"https://h/{_U},{_U}",
        f"https://h/{_B}!",
        f"https://h/aaaaaaaaaa{_U}",  # a prefixed token
        "https://h/0123456789abcdef-0123456789abcdef",  # hex runs joined like a slug
        "https://h/tok_abcdefghij1234567890_abcdefghij1234567890",  # long mixed "words"
        "https://h/ab12CD34ef56%2BGH78ij90KL12mn34",  # standard base64
        "https://h/eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",  # a JWT
        "https://h/abcdEFGH1234ijkl~mnopQRST5678uvwx",  # a token split by ~
        "https://h/feed/token=0123456789abcdef0123",
        "https://h/feed/u:0123456789abcdef01",
        "https://h/x\\" + _U,
    ],
)
def test_a_token_inside_a_segment_is_masked_the_security_reads(address):
    from src.database.address_mask import QUERY_VALUE_MASK, masked_address

    written = masked_address(address)
    assert QUERY_VALUE_MASK in written and "0123456789" not in written and "eyJ" not in written, written


def test_a_feed_keys_path_that_opens_with_two_slashes_is_still_a_path():
    """The first security read on R736: ``feed_key`` keeps a doubled slash, and the part from the path on was read as an authority."""
    from src.database.feed_key import feed_key, shown_feed_key

    assert shown_feed_key(feed_key(f"https://host//{_U}/rss")) == "f:host//***/rss"


@pytest.mark.parametrize(
    "address",
    [
        "https://h/2026/11/16/the-climate-report-2025-final.html",
        "https://h/news/12345/story-about-covid19-in-2025",
        "https://h/rss/news.xml",
        "https://h/Annual-Report.pdf",
    ],
)
def test_ordinary_paths_stay_readable_after_the_widening(address):
    from src.database.address_mask import masked_address

    assert masked_address(address) == address
