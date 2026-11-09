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
# THE KILL SWITCH'S REFUSAL SENTENCE, defined once (R317). Every site that raises it says it by this name (``src/ingest/__init__.py``,
# ``src/safety/fetcher.py``), and the first alternative of ``_OFFLINE_RE`` below is built from its opening words, so a rewording moves the
# writers and the reader together instead of leaving the reader matching a sentence nobody raises any more. A reader anchors on the HEAD (the
# words before " -- "), which is also what a caller that appends its own detail to the sentence still starts with.
KILL_SWITCH_REFUSAL_HEAD = "network kill switch is active"
KILL_SWITCH_REFUSAL = f"{KILL_SWITCH_REFUSAL_HEAD} -- collection stopped by operator"
# THE PRE-CHECK'S REFUSAL SENTENCE, defined once (R328, the R317 defect in a second place). The routes and loaders that refuse UP FRONT, before any
# request is built (``if kill_switch_active(): raise ...``), said it as a literal each: eight HTTP 409 ``detail``s, the four statistics fetchers, the
# catalogue, entity and ring loaders, the mailbox import (the count is pinned in tests/test_kill_switch_refusal_constant.py). The one reader of the text
# in ``src/`` is ``_wikidataRefusedByAirplaneMode`` in ``src/static/app-insights.js``: it takes a 409 STATUS as the refusal, and a message with no status
# that STARTS with our own sentence (R298), the second branch being a copy of this text that nothing tied to the writers. It is NOT
# ``KILL_SWITCH_REFUSAL`` (the fetcher's sentence, raised in the middle of a fetch) and NOT the socket guard's (``airplane mode is engaged: refusing
# a network connection ...``); ``_OFFLINE_RE`` below does not read it, and a longer sentence a writer builds on it keeps it as its opening words.
NETWORK_REFUSED = "network refused: airplane mode is engaged"
# OUR OWN SENTENCES, recognised at the START of the text, never as a phrase anywhere in it (R298): the same words can appear INSIDE another
# failure's text (a redirect target, a status line a server wrote, a URL), and that failure is the host's, not the person's airplane mode.
#   1. the kill switch's refusal (``KILL_SWITCH_REFUSAL`` above), raised in ``src/ingest/__init__.py`` and ``src/safety/fetcher.py``, optionally
#      led by an exception class a caller prefixed ("FetchFailed: ...");
#   2. the socket guard's refusal (``airplane.py``, an ``AirplaneModeError``), bare, or as ``requests`` wraps it when the switch is engaged
#      AFTER the fetcher's own check passed: "request error for <url>: HTTPSConnectionPool(host='<host>', port=<n>): Max retries exceeded
#      with url: <path> (Caused by NewConnectionError("HTTPSConnection(host='<host>', port=<n>): Failed to establish a new connection: airplane
#      mode is engaged: ...", the cause led by "ProxyError('Unable to connect to proxy', " when the guard refused a proxy that is not on
#      loopback, and the class names urllib3.contrib.socks gives them over a SOCKS proxy (the protected transport, Tor): SOCKSHTTPSConnectionPool
#      and SOCKSHTTPSConnection, SOCKSHTTPConnectionPool and SOCKSConnection. The alternative spells that construction out from its first word
#      with no gap, because a host's OWN words can sit in the same sentence: urllib3 quotes a status line it could not parse (``('Connection
#      aborted.', BadStatusLine('<the host's line>'))``), and a gap (the ``.*`` this alternative had) read a host that wrote the guard's words
#      there as the person's airplane mode (OPEN_QUEUE 2026-11-08 item 42, R616). Every token another party shapes ends where our words begin:
#      the URL is written through ``failure_url`` below (its whitespace percent-encoded, so ``\S+`` is the whole URL and a link that holds
#      spaces cannot continue in our words; its userinfo masked, R620, by a mask that holds no whitespace), the path is the one requests
#      sent (percent-encoded), and the host tokens take no whitespace, quote or backslash (as in 3.);
#   3. the same guard sentence under OUR resolver wrapper (``EthicalFetcher._resolve_cached``), when the switch is engaged between the
#      pre-fetch check and the lookup: "cannot resolve host '<host>': airplane mode is engaged: refusing a network connection ...". The host
#      is the only part another party shapes (a redirect's Location, a feed item's link). Since R622 no host holding whitespace, a backslash or
#      a control character reaches a lookup, and urllib3 refuses an IPvFuture "[v1.<anything>]" host in ``_refuse_parser_mismatch``; the token
#      stays strict as the net beneath: it takes NO whitespace and NO backslash: ``repr`` escapes an inner quote with a backslash,
#      so a host that tries to close the quote early and continue in our words is refused, and a host holding both quote kinds fails SAFE
#      (read as ``dns``). A gaierror's own text ("[Errno -2] ...") between the two never matches;
#   4. the guard's sentence when what it refused was the CONNECT a LOOPBACK HTTP proxy is asked to make to an https target (R620: Privoxy
#      chained to Tor, ``http_proxy = http://127.0.0.1:8118``). The proxy's own connect is loopback and passes; ``_guarded_tunnel``
#      (``airplane.py``) refuses the real destination before any CONNECT byte is sent, called from urllib3's ``connect()`` AFTER
#      ``_new_conn`` returned, so no NewConnectionError is built: the pool wraps the OSError as ``ProtocolError("Connection aborted.",
#      <the error>)`` (``urllib3/connectionpool.py``, the one place urllib3 writes those words, for an OSError or an
#      ``http.client.HTTPException``; requests writes them nowhere), requests re-raises that as its ConnectionError, and the text is
#      "request error for <url>: ('Connection aborted.', AirplaneModeError(\"airplane mode is engaged: refusing a network connection to
#      '<host>'. ...\"))", the quote a single one when the host holds one (measured through the real guard, a loopback proxy, requests
#      2.34 and urllib3 2.7.0 and 2.8.0: tests/test_refusal_r620.py). Before R620 it read as ``connect``, a false "not offline". WHY A
#      HOST CANNOT WRITE IT: urllib3 writes the tuple's second item as the ``repr`` of the exception, and the repr of every OSError and
#      HTTPException on the fetch path opens with the class's own name (BaseException's repr does; the four classes that override it,
#      the IncompleteRead of http.client and of urllib3, urllib3's InvalidChunkLength and urllib.error's HTTPError, open with their
#      name too), so a host's words arrive inside the quotes AFTER a class name it cannot choose: its status line as
#      ``BadStatusLine('<its line>')``, a proxy's refusal as ``OSError('Tunnel connection failed: <code> <its words>')``. The one class
#      named AirplaneModeError is ours, and its one writer, ``_guard``, opens with our words. So this alternative, like 2., is spelled
#      from its first word with no gap, and its URL token is whole for the reason 2. gives.
# READ BY TYPE FIRST (R620, after Steward 3's note: "classified by type and never by words"). The one writer of "request error for" is
# ``EthicalFetcher._fetch_locked`` (src/ingest/__init__.py), and before it writes that sentence it walks the live requests exception for an
# ``AirplaneModeError`` INSTANCE (``_carries_airplane_refusal``: ``__cause__``, the exceptions in ``args``, urllib3's ``MaxRetryError.reason``;
# bounded, never through text). NOT ``__context__``: Python sets it on the first exception the request raises to whatever the caller's thread
# is handling at that moment, so a fetch made inside an ``except`` that holds a refusal (a fallback fetch after a Stopped one) would read its
# own host's failure as the switch's (the independent read's S1); every real shape is reached without it. When it finds one it raises
# ``KILL_SWITCH_REFUSAL``, read by 1., at once: no retry and no host's text. That covers 2. and 4. as they happen, and one shape no
# alternative here reads: a plain ``http://`` request line refused at a loopback proxy by R619's ``putrequest`` guard (PR #1855), which
# urllib3 writes as "(Caused by ProxyError('Unable to connect to proxy', AirplaneModeError(...)))" inside its pool sentence, with no
# NewConnectionError and no "Connection aborted.". That shape is read by type ONLY (measured at #1855's head;
# tests/test_refusal_by_type_r620.py). A host cannot produce the type: the class has one
# constructor, ``airplane._guard``, which raises only while the switch is engaged (the airplane half armed, the host not local, no egress
# window open), before any byte reaches the destination, and a host's bytes become the libraries' own classes. Which shape is read how:
#   - by TYPE, in the fetcher: the socket guard's refusal anywhere inside a requests error, whether direct (R616), at a loopback proxy's
#     CONNECT (R620) or in a request line sent to a loopback proxy (R619). Over SOCKS, urllib3.contrib.socks raises its NewConnectionError
#     ``from`` the guard's error, so the same walk finds it there; that path is not exercised here, because PySocks is not installed;
#   - by WORDS, here: 1. (our own sentence, wherever it is passed on), 3. (our resolver wrapper's sentence, written outside the requests
#     handler), and 2. and 4. as the net under the typed read. No live path needs 2. or 4. now, since the typed read runs first at their
#     one writer, and no stored record needs them, since every caller classifies the text of a live exception and none re-reads a stored
#     one. They stay for two reasons: R616 and R620(a) rule them, and if the bounded walk ever missed a link, the text would still carry
#     the real instance's repr, which a host cannot write (the argument under 4.).
#   The preflights (``src/monitoring/preflight.py``, ``feed_preflight.py``) call ``_guarded_redirect_get`` directly and so get no typed
#   read: the safe direction (at worst a refusal reads there as the host's failure, never a host's failure as the switch's), and they
#   read ``kill_switch_active()`` beside 1.
# No ``re.DOTALL`` (R620): no ``.`` in the pattern stands outside a class or an escape, so the flag changed nothing, and a ``.`` added
# later must not span lines because of a flag nobody needed.
_OFFLINE_RE = re.compile(
    r"^\s*(?:[\w.]+:\s*)?(?:" + re.escape(KILL_SWITCH_REFUSAL_HEAD) + r"|airplane mode is engaged: refusing a network connection)\b"
    r"|^\s*request error for \S+: (?:SOCKS)?HTTPS?ConnectionPool\(host='[^'\s\\]*', port=\d+\): Max retries exceeded with url: \S* "
    r"\(Caused by (?:ProxyError\('Unable to connect to proxy', )?NewConnectionError\([\"'](?:SOCKS(?:HTTPS)?|HTTPS?)Connection\(host='[^'\s\\]*', port=\d+\): "
    r"Failed to establish a new connection: "
    r"airplane mode is engaged: refusing a network connection"
    r"|^\s*cannot resolve host (?:'[^'\s\\]*'|\"[^\"\s\\]*\"): airplane mode is engaged: refusing a network connection"
    r"|^\s*request error for \S+: \('Connection aborted\.', AirplaneModeError\([\"']airplane mode is engaged: refusing a network connection",
    re.IGNORECASE,
)


_WHITESPACE_RE = re.compile(r"\s")
#: What stands in for a URL's userinfo and its ``@`` in a failure sentence (R620). FIXED, so the length of a secret is not told; the user
#: name goes with the password, because a token is often carried AS the user name (``https://<token>@host/``); none of ``:/?#[]@`` and
#: no whitespace, so the masked URL still has its host, port and path for any parser and stays one ``\S+`` token for the reader above;
#: the ``@`` is kept, so a person reading a 401 still sees that the URL carried credentials.
USERINFO_MASK = "***@"
#: What the sentence carries in place of a URL that could not be read (an argument that is not a string, a string that raises): one
#: ``\S+`` token, never the input, because a URL that could not be read is a URL whose credentials could not be taken out.
UNREADABLE_URL = "<url-withheld>"
#: Taken out wherever they stand before ``urllib.parse`` parses a URL (``_UNSAFE_URL_BYTES_TO_REMOVE``), so an authority they split is
#: still one for it: ``https:/\t/alice:pw@host`` is ``https://alice:pw@host``.
_URLSPLIT_DROPS = frozenset("\t\r\n")


def _userinfo_span(url: str) -> tuple[int, int] | None:
    """Where the authority's userinfo AND its ``@`` stand in ``url`` (start, end), or ``None`` when it has none. Plain string work, no
    parser, so it cannot raise for a string a parser refuses (``https://u:p@[::1/x`` is a ``ValueError`` to ``urlsplit``).

    The reading is WIDER than each parser's, never narrower (R620): the characters ``urllib.parse`` drops are skipped, then leading
    whitespace and C0 controls; the scheme is anything before the first ``:`` that holds none of ``/?#@`` (``urlsplit`` asks for a valid
    scheme; a URL whose scheme it rejects is still masked here); an authority is the text after the ``//`` that follows it (or that opens
    the string) up to the first ``/``, ``?`` or ``#``, the backslash included; the userinfo is everything before the LAST ``@`` in it.
    That covers what ``urlsplit`` calls the userinfo (the parser the fetcher's own checks use, and the one requests reads the Basic
    credentials it sends from, ``get_auth_from_url``) and what urllib3 calls it (its authority ends at a backslash as well, so it is never
    longer), and it leaves an ``@`` in a path, a query or a fragment where it is. Not masked, stated: a string with no ``//`` authority
    (``mailto:a@b``, a path, a scheme-less ``user@host`` that urllib3 alone would read with one; requests refuses to send a URL with no
    scheme, and the fetcher refuses one before any request), and a "credential" holding a raw ``/``, ``?`` or ``#``, which every parser
    ends the authority at, so it is not a credential of that URL.

    Wider also means it can take more than the userinfo, stated (R620, the independent read's N1): with a backslash in the authority,
    ``https://u:p@evil.example\\@good.example/x`` is masked to ``https://***@good.example/x``, which removes the host urllib3 reads
    (``evil.example``, whose authority ends at the backslash). That is the safe choice for the secret: ``urlsplit`` reads ``u:p@evil.example\\``
    as the userinfo, so a narrower mask would leave a credential in the sentence for one parser or the other. No request is made for such
    a URL: ``EthicalFetcher._refuse_parser_mismatch`` refuses an authority holding a backslash (as it refuses one the two parsers read as
    different hosts) before any request, the robots read's included."""
    kept = [i for i, ch in enumerate(url) if ch not in _URLSPLIT_DROPS]
    seen = "".join(url[i] for i in kept)
    lead = 0
    while lead < len(seen) and (seen[lead] <= " " or seen[lead].isspace()):
        lead += 1
    scheme_end = lead
    colon = seen.find(":", lead)
    if colon >= 0 and not any(ch in "/?#@" for ch in seen[lead:colon]):
        scheme_end = colon + 1
    if seen[scheme_end : scheme_end + 2] != "//":
        return None
    start = scheme_end + 2
    end = len(seen)
    for stop in "/?#":
        found = seen.find(stop, start)
        if 0 <= found < end:
            end = found
    at = seen.rfind("@", start, end)
    if at < 0:
        return None
    # from just after the second "/" (a dropped character between it and the userinfo goes with the userinfo) to just after the "@"
    return kept[start - 1] + 1, kept[at] + 1


def failure_url(url: str) -> str:
    """The URL as the fetcher writes it into its failure sentence ("request error for <url>: ..."): the userinfo masked and every
    whitespace character percent-encoded (its UTF-8 bytes), nothing else changed. NEVER raises.

    A caller's URL can hold spaces (a feed item's link, a redirect target) and the reader above takes the URL token as everything up to
    the first whitespace, so a raw space let the rest of a link be read as our own words (R616). ``\\s`` here is the reader's ``\\S``
    turned around, so the two cannot disagree on what ends the token. A URL can also hold credentials (``https://user:pass@host/x``),
    and the sentence is stored, served and shown, so the userinfo is replaced by :data:`USERINFO_MASK` first (R620; the span is
    :func:`_userinfo_span`'s). A URL that cannot be read is written as :data:`UNREADABLE_URL`, never as it came. The request itself is
    unchanged: requests quotes the URL it sends on its own, and sends the credentials it carries."""
    try:
        span = _userinfo_span(url)
        if span is not None:
            url = url[: span[0]] + USERINFO_MASK + url[span[1] :]
        return _WHITESPACE_RE.sub(lambda m: "".join(f"%{b:02X}" for b in m.group().encode("utf-8", "surrogatepass")), url)
    except Exception:  # noqa: BLE001 - a failure sentence is written from inside a failure; a URL it cannot read is withheld whole
        return UNREADABLE_URL


def failure_netloc(netloc: str) -> str:
    """A bare authority (``user:pw@host:port``, a ``urlparse`` netloc) written as :func:`failure_url` writes a URL: its userinfo masked,
    its whitespace percent-encoded. It is read as the authority it is (:func:`_userinfo_span` finds one only after a ``//``), and
    :data:`UNREADABLE_URL` stands in for one that cannot be read. NEVER raises."""
    try:
        out = failure_url("//" + netloc)
        return out[2:] if out.startswith("//") else out
    except Exception:  # noqa: BLE001 - written from inside a failure; an authority it cannot read is withheld whole
        return UNREADABLE_URL


def userinfo_secrets(url: str) -> tuple[str, ...]:
    """The credentials ``url`` carries, as the secrets a scrub takes out of an exception's text written AFTER the URL (R620, Steward 3
    #1): the whole userinfo, then the user and the password apart (split at the first ``:``), each also with the characters
    ``urllib.parse`` drops taken out, all read from :func:`_userinfo_span`'s span. :func:`failure_url` masks the URL token, but an
    exception's text is not that token: requests writes ``Failed to parse: https://u:pw@...``, so the sentence hands these to
    ``record_text`` or ``log_failure`` beside the exception. A part under the scrub's floor (``MIN_SECRET_CHARS``, four characters) is
    not taken out of free text; a text that holds one is WITHHELD whole instead (``secret_scrub``'s rule, not this one's). Empty when the
    URL has no userinfo or cannot be read. NEVER raises."""
    try:
        span = _userinfo_span(url)
        if span is None:
            return ()
        raw = url[span[0] : span[1] - 1]
        out: list[str] = []
        for userinfo in (raw, "".join(ch for ch in raw if ch not in _URLSPLIT_DROPS)):
            user, _, password = userinfo.partition(":")
            out += (userinfo, user, password)
        return tuple(dict.fromkeys(part for part in out if part))
    except Exception:  # noqa: BLE001 - written from inside a failure; no secret is better than a raise that replaces it
        return ()


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
