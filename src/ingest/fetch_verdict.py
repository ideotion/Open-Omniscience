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
    "slow_body",  # the body trickled past the wall-clock read deadline (a tarpit)
    "bad_url",  # malformed URL / missing host / redirect loop / unsupported redirect
    "other",  # anything unrecognised (keeps the total honest)
)

_HTTP_RE = re.compile(r"\bHTTP (\d{3})\b")
# OUR OWN SENTENCES, recognised at the START of the text, never as a phrase anywhere in it (R298): the same words can appear INSIDE another
# failure's text (a redirect target, a status line a server wrote, a URL), and that failure is the host's, not the person's airplane mode.
#   1. the kill switch's refusal, raised verbatim in ``src/ingest/__init__.py`` and ``src/safety/fetcher.py``, optionally led by an exception
#      class a caller prefixed ("FetchFailed: ...");
#   2. the socket guard's refusal (``airplane.py``, an ``AirplaneModeError``), bare, or as ``requests`` wraps it when the switch is engaged
#      AFTER the fetcher's own check passed: "request error for <url>: ...Failed to establish a new connection: airplane mode is engaged: ...".
#      That wrapped text is built locally by requests/urllib3 (the URL in it is percent-encoded, so it cannot carry these words);
#   3. the same guard sentence under OUR resolver wrapper (``EthicalFetcher._resolve_cached``), when the switch is engaged between the
#      pre-fetch check and the lookup: "cannot resolve host '<host>': airplane mode is engaged: refusing a network connection ...". The host
#      is the only part another party shapes (a redirect's Location, a feed item's link: an IPvFuture "[v1.<anything>]" host reaches a lookup
#      with spaces, colons and quotes in it), so the token takes NO whitespace and NO backslash: ``repr`` escapes an inner quote with a backslash,
#      so a host that tries to close the quote early and continue in our words is refused, and a host holding both quote kinds fails SAFE
#      (read as ``dns``). A gaierror's own text ("[Errno -2] ...") between the two never matches.
_OFFLINE_RE = re.compile(
    r"^\s*(?:[\w.]+:\s*)?(?:network kill switch is active|airplane mode is engaged: refusing a network connection)\b"
    r"|^\s*request error for \S+: .*Failed to establish a new connection: airplane mode is engaged: refusing a network connection"
    r"|^\s*cannot resolve host (?:'[^'\s\\]*'|\"[^\"\s\\]*\"): airplane mode is engaged: refusing a network connection",
    re.IGNORECASE | re.DOTALL,
)


def is_kill_switch_refusal(text: str | None) -> bool:
    """True when ``text`` IS one of our refusal sentences (see above). One definition for every caller that must tell the person's
    own airplane mode apart from a host's failure; a phrase search over the text is not an equivalent."""
    return text is not None and _OFFLINE_RE.match(text) is not None


def classify_fetch_failure(detail: str | None) -> str:
    """Map a FetchError message to one of :data:`FETCH_FAIL_REASONS`.

    Unknown / empty messages return ``"other"`` so the per-reason counts always
    sum to the raw ``fetch_failed`` total (nothing is silently dropped).
    """
    if not detail:
        return "other"
    d = detail.lower()

    if is_kill_switch_refusal(detail):
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
    if "body read exceeded" in d:
        return "slow_body"
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
