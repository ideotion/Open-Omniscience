"""Fetch-failure reason classification (src.ingest.fetch_verdict).

Turns the raw fetch_failed count into an honest per-reason breakdown so a report
can say WHY (Tor-403 reality vs a real transport/DB problem), never a mystery
number. Pure — no feedparser/network — so it runs in the sandbox and CI.

The message fixtures mirror the actual `raise FetchFailed(...)` sites in
src/ingest/__init__.py; if a raise message changes, the matching test should too.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.ingest.fetch_verdict import (
    FETCH_FAIL_REASONS,
    classify_fetch_failure,
    fetch_failed_reasons,
    fetch_reason_key,
)


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("network kill switch is active -- collection stopped by operator", "offline"),
        ("FetchFailed: network kill switch is active -- collection stopped by operator", "offline"),
        ("  Network Kill Switch is active -- collection stopped by operator", "offline"),
        # The words INSIDE another failure's text are that failure's, never the person's airplane mode (R296 control cases).
        ("HTTP 503 for https://h.test/a (server said: network kill switch is active)", "http_5xx"),
        ("request error for https://h.test/kill switch is active: timed out", "connect"),
        ("redirect to unsupported URL: 'ftp://h.test/network kill switch is active'", "bad_url"),
        ("some brand-new error: the kill switch of the CDN fired", "other"),
        # The socket guard's own sentence (R298): bare, and as requests wraps it when the switch is engaged AFTER the fetcher's check.
        (
            "airplane mode is engaged: refusing a network connection to 'h.test'. No packet leaves the machine while offline",
            "offline",
        ),
        (
            "request error for https://h.test/x: HTTPSConnectionPool(host='h.test', port=443): Max retries exceeded with url: /x "
            "(Caused by NewConnectionError(\"HTTPSConnection(host='h.test', port=443): Failed to establish a new connection: "
            "airplane mode is engaged: refusing a network connection to 'h.test'. No packet leaves the machine while offline\"))",
            "offline",
        ),
        (
            "HTTP 503 for https://h.test/a (server said: airplane mode is engaged: refusing a network connection to 'h.test')",
            "http_5xx",
        ),
        (
            "HTTP 502 for https://h.test/a: Failed to establish a new connection: airplane mode is engaged: refusing a network connection",
            "http_5xx",
        ),
        # The same guard sentence under OUR resolver wrapper (R300), and the controls that must stay a DNS failure or an HTTP error.
        (
            "cannot resolve host 'h.test': airplane mode is engaged: refusing a network connection to 'h.test'. No packet leaves the machine while offline",
            "offline",
        ),
        ("cannot resolve host 'h.test': [Errno -2] airplane mode is engaged: refusing a network connection to 'h.test'", "dns"),
        (
            "HTTP 502 for https://h.test/a (server said: cannot resolve host 'x': airplane mode is engaged: refusing a network connection)",
            "http_5xx",
        ),
        ("HTTP 403 for https://reuters.com/x", "http_403"),
        ("HTTP 401 for https://x", "http_401"),
        ("HTTP 429 for https://x", "http_429"),
        ("HTTP 404 for https://x", "http_4xx"),
        ("HTTP 503 for https://x", "http_5xx"),
        ("cannot resolve host 'gone.example': NameResolutionError", "dns"),
        ("request error for https://x: ConnectionResetError(104)", "connect"),
        ("non-HTML content ('application/pdf') for https://x", "not_html"),
        ("response exceeds 5000000 bytes for https://x", "too_large"),
        ("declared length 9000000 exceeds 5000000 bytes for https://x", "too_large"),
        ("body read exceeded 300s for https://x (a slow or trickling response)", "slow_body"),
        ("unsupported or malformed URL: 'javascript:void'", "bad_url"),
        ("too many redirects for https://x", "bad_url"),
        ("missing host", "bad_url"),
        ("redirect to unsupported URL: 'ftp://x'", "bad_url"),
        ("some brand-new error we do not recognise", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_classify_covers_every_fetchfailed_site(detail, expected):
    got = classify_fetch_failure(detail)
    assert got == expected
    assert got in FETCH_FAIL_REASONS  # every result is a declared bucket


def test_reason_key_prefix():
    assert fetch_reason_key("http_403") == "ff:http_403"


def test_rollup_sums_to_fetch_failed_and_orders_desc():
    last = {
        "tally": {
            "stored": 10,
            "fetch_failed": 6,
            "ff:http_403": 4,
            "ff:dns": 1,
            "ff:connect": 1,
        }
    }
    reasons = fetch_failed_reasons(last)
    assert reasons == {"http_403": 4, "dns": 1, "connect": 1}  # dict insertion = desc order
    assert list(reasons)[0] == "http_403"  # most common first
    assert sum(reasons.values()) == last["tally"]["fetch_failed"]  # nothing dropped


def test_rollup_honest_empty_cases():
    assert fetch_failed_reasons(None) == {}
    assert fetch_failed_reasons({}) == {}
    assert fetch_failed_reasons({"tally": {"stored": 3}}) == {}  # no failures -> empty
