"""How a feed or source ADDRESS is written where it leaves the running app's own answers: a report, a field data file, a diagnostics
bundle, a log line (R734, 2026-11-16).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R637 masks an address's USERINFO wherever it is shown. A token is as often carried in the QUERY (``?token=...``, ``?apikey=...``,
``?sig=...``), and R637 left the query as written, so a report the person hands to someone else carried it. R734 rules, for those
writers, that:

* every query VALUE is written as :data:`QUERY_VALUE_MASK`, except the value of a parameter whose NAME is on the small reviewed
  allowlist :data:`HARMLESS_QUERY_NAMES` AND whose value has the plain form :data:`_KEPT_VALUE_RE` reads (a word, a number);
* the FRAGMENT is dropped;
* it FAILS CLOSED: an unknown name is masked, a name that does not read as a plain name is masked WITH its value, a bare item (no
  ``=``) is kept only when it is an allowlisted name;
* it is STABLE: the same address gives the same text on every instance (no salt, no per-run state), so rows of two instances' reports
  still match on domain + the written key. Stated limit: two addresses that differ only in a masked value are written the same.

The UI's own answers are not on this list: an edit form sends the shown address back (``url_to_store``), and a masked query sent back
would be stored as typed. They keep R637's form (``src.ingest.fetch_verdict.shown_url``).

This module imports no ``src`` module (the feed identity module imports it, and ``src.analytics.engine_identity`` triages both).
Nothing here raises: a text it cannot read is written as :data:`QUERY_VALUE_MASK` from its first ``?`` on.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote

#: What stands in for a query value (and for a whole item whose name does not read as a plain name). Fixed, so its length tells nothing;
#: none of ``&;=#?/@`` and no whitespace, so a masked address is still one ``\\S+`` token with its host and path for any parser.
QUERY_VALUE_MASK = "***"

#: Parameter names whose VALUE is kept (compared percent-decoded and lower-cased). Reviewed for R734: each names a presentation or
#: selection choice a public feed takes (its format, language, page, section), never who asks. A name is added here only after the
#: same review; a name not here is masked, so forgetting one costs a less specific report, never a leaked token. ``id``, ``q``,
#: ``user``, ``key`` and anything like them stay off: an id or a search can be personal. ``feed``, ``rss`` and ``channel`` were dropped by
#: the first security read: a private feed plausibly carries its token under one of them.
HARMLESS_QUERY_NAMES = frozenset(
    {
        "format",
        "fmt",
        "output",
        "type",
        "feedtype",
        "lang",
        "language",
        "hl",
        "locale",
        "edition",
        "region",
        "country",
        "page",
        "limit",
        "per_page",
        "sort",
        "order",
        "orderby",
        "view",
        "section",
        "category",
        "cat",
        "tag",
        "topic",
    }
)

#: A name written as a plain name (letters, digits, ``_.-[]`` and percent escapes). Anything else is masked together with its value: a
#: name can itself be the token (``?3f9a...``).
_NAME_RE = re.compile(r"[A-Za-z0-9_.\-\[\]%]{1,64}")
#: A kept value has a plain form too: an allowlisted name holding a long or oddly-shaped value is masked all the same. At most 16
#: characters: a language, a page, a sort order or a format fits, a token (``ghp_...``, a 32-hex id) does not.
_KEPT_VALUE_RE = re.compile(r"[A-Za-z0-9_.,+\-]{0,16}")
_SEPARATOR_RE = re.compile(r"([&;])")


def _is_harmless(name: str) -> bool:
    try:
        return unquote(name).strip().lower() in HARMLESS_QUERY_NAMES
    except Exception:  # noqa: BLE001 - a name that cannot be read is not a harmless one
        return False


def _masked_item(item: str) -> str:
    if not item:
        return item
    name, eq, value = item.partition("=")
    if not _NAME_RE.fullmatch(name):
        return QUERY_VALUE_MASK
    harmless = _is_harmless(name)
    if not eq:
        return item if harmless else QUERY_VALUE_MASK
    if harmless and _KEPT_VALUE_RE.fullmatch(value):
        return item
    return name + "=" + QUERY_VALUE_MASK


def _decoded(part: str) -> str:
    try:
        return unquote(part)
    except Exception:  # noqa: BLE001 - the raw form is still taken out
        return part


def masked_query(query: str) -> str:
    """``query`` (the text after ``?``, without it) with each ``&``- or ``;``-separated item written as R734 rules: an allowlisted
    name's plain value kept, every other value as :data:`QUERY_VALUE_MASK`, a name that is not a plain name masked whole. The
    separators are kept as written. NEVER raises."""
    try:
        parts = _SEPARATOR_RE.split(query)
        return "".join(part if i % 2 else _masked_item(part) for i, part in enumerate(parts))
    except Exception:  # noqa: BLE001 - written from inside reports and failures; a query it cannot read is withheld whole
        return QUERY_VALUE_MASK


def masked_address(text: str) -> str:
    """``text`` (an address, or a feed key's body) with its fragment dropped and its query masked by :func:`masked_query`. The query
    starts at the FIRST ``?`` (an authority cannot hold one: every parser ends it there), the fragment at the first ``#``. Everything
    before the query is returned as given, so the userinfo mask the caller applies is its own concern. NEVER raises."""
    try:
        head = text.split("#", 1)[0]
        base, mark, query = head.partition("?")
        return base + mark + masked_query(query) if mark else base
    except Exception:  # noqa: BLE001 - see masked_query
        return QUERY_VALUE_MASK


#: The characters requests leaves unquoted when it re-quotes an address before quoting it in its own exception text
#: (``requests.utils.requote_uri``); ``%`` is in the first set only, as there.
_REQUOTE_SAFE = "!#$%&'()*+,/:;=?@[]~"
_REQUOTE_SAFE_NO_PERCENT = "!#$&'()*+,/:;=?@[]~"
_HEX_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")


def _written_forms(part: str) -> list[str]:
    """Every spelling of ``part`` a library may quote back in an exception (the first security read on R734 proved requests writes a
    re-quoted one): as written, percent-decoded, with tab/CR/LF taken out (urllib drops them), re-quoted the requests way, fully
    quoted, and with its escapes in upper and lower case."""
    out: list[str] = []
    for base in (part, _decoded(part)):
        for form in (base, re.sub(r"[\t\r\n]", "", base)):
            out.append(form)
            for safe in (_REQUOTE_SAFE, _REQUOTE_SAFE_NO_PERCENT, ""):
                try:
                    out.append(quote(form, safe=safe))
                except Exception:  # noqa: BLE001,S112 - one spelling it cannot write is one fewer, never a raise
                    continue
    for form in list(out):
        out.append(_HEX_ESCAPE_RE.sub(lambda m: m.group(0).upper(), form))
        out.append(_HEX_ESCAPE_RE.sub(lambda m: m.group(0).lower(), form))
    return out


def query_secrets(text: str, *, floor: int = 4) -> tuple[str, ...]:
    """The query values :func:`masked_address` masks in ``text``, each as written and percent-decoded, for a scrub to take out of an
    exception's text that quotes the address in its own words (requests writes ``url: /rss?token=...``). Only values of at least
    ``floor`` characters (the scrub withholds a WHOLE text that holds a part under its floor, so passing a short one would withhold
    every failure of an address carrying ``?x=1``). STATED LIMIT: a masked value under ``floor`` characters can therefore stay in an
    exception's text (the address itself, written by :func:`masked_address`, never shows it). Each value is given in every spelling
    :func:`_written_forms` lists. Empty when there is no query or it cannot be read. NEVER raises."""
    try:
        query = text.split("#", 1)[0].partition("?")[2]
        if not query:
            return ()
        out: list[str] = []
        for item in _SEPARATOR_RE.split(query)[::2]:
            name, eq, value = item.partition("=")
            if not eq:
                if item and not (_NAME_RE.fullmatch(item) and _is_harmless(item)):
                    out.append(item)
                continue
            if not _NAME_RE.fullmatch(name):
                out += (name, value)
            elif not (_is_harmless(name) and _KEPT_VALUE_RE.fullmatch(value)):
                out.append(value)
        forms: list[str] = []
        for part in out:
            forms += _written_forms(part)
        return tuple(dict.fromkeys(p for p in forms if len(p) >= floor))
    except Exception:  # noqa: BLE001 - written from inside a failure; no secret is better than a raise that replaces it
        return ()
