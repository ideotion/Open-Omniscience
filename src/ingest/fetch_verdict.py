"""Classify a fetch-failure message into an honest reason bucket.

The collector records every network failure as ``IngestResult.FETCH_FAILED`` with
the raw ``FetchError`` text in ``detail`` — but the per-pass tally then kept only
the *count*, so a report could say "13,678 fetch_failed" without telling the
operator WHY. That raw count hides the difference between the expected Tor-403
reality (premium news blocks Tor) and something that would be a real bug.

This maps the ``FetchError`` message (see the ``raise FetchFailed(...)`` sites in
``src/ingest/__init__.py``) to a small, stable set of buckets so the tally can be
broken down per reason. It is DESCRIPTIVE, never a score, and deliberately does
NOT assert "Tor" for a 403 (a 403 has many causes) — it reports the HTTP status
and lets the operator read it against their transport.

No heavy imports on purpose: kept out of ``pipeline`` (which pulls feedparser) so
it is unit-testable anywhere.
"""

from __future__ import annotations

import re

# The buckets, each tied to a FetchFailed raise site. Order matters only for the
# HTTP status split; the string checks below are mutually exclusive in practice.
FETCH_FAIL_REASONS = (
    "offline",  # kill switch / airplane engaged — not a failure of the source
    "http_403",  # forbidden (often a Tor-block on premium news; NOT asserted here)
    "http_401",  # auth required
    "http_429",  # rate limited
    "http_4xx",  # other client error
    "http_5xx",  # server error
    "dns",  # host does not resolve
    "connect",  # connection refused / reset / timeout (transient transport)
    "not_html",  # fetched, but the body was not HTML
    "too_large",  # response exceeded the byte cap
    "bad_url",  # malformed URL / missing host / redirect loop / unsupported redirect
    "other",  # anything unrecognised (keeps the total honest)
)

_HTTP_RE = re.compile(r"\bHTTP (\d{3})\b")


def classify_fetch_failure(detail: str | None) -> str:
    """Map a FetchError message to one of :data:`FETCH_FAIL_REASONS`.

    Unknown / empty messages return ``"other"`` so the per-reason counts always
    sum to the raw ``fetch_failed`` total (nothing is silently dropped).
    """
    if not detail:
        return "other"
    d = detail.lower()

    if "kill switch" in d:
        return "offline"

    m = _HTTP_RE.search(detail)
    if m:
        code = int(m.group(1))
        if code == 403:
            return "http_403"
        if code == 401:
            return "http_401"
        if code == 429:
            return "http_429"
        if 400 <= code < 500:
            return "http_4xx"
        if 500 <= code < 600:
            return "http_5xx"

    if "cannot resolve host" in d:
        return "dns"
    if d.startswith("request error for") or "request error for" in d:
        return "connect"
    if "non-html content" in d:
        return "not_html"
    if "exceeds" in d and "byte" in d:
        return "too_large"
    if (
        "malformed url" in d
        or "missing host" in d
        or "too many redirects" in d
        or "redirect to unsupported" in d
        or "unsupported or malformed" in d
    ):
        return "bad_url"
    return "other"


def fetch_reason_key(reason: str) -> str:
    """The flat tally key for a reason bucket (kept int-valued so the scheduler's
    scalar tally-aggregation sums it across sources with no special handling)."""
    return "ff:" + reason


def fetch_failed_reasons(last_result: dict | None) -> dict[str, int]:
    """Roll the flat ``ff:<reason>`` keys of a scheduler ``last_result`` tally into
    a clean ``{reason: count}`` map, ordered most-common first. Empty when the last
    pass recorded no fetch failures. The per-reason counts sum to ``fetch_failed``.
    """
    tally = last_result.get("tally") if isinstance(last_result, dict) else None
    if not isinstance(tally, dict):
        return {}
    out = {
        k[3:]: v
        for k, v in tally.items()
        if isinstance(k, str) and k.startswith("ff:") and isinstance(v, int)
    }
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
