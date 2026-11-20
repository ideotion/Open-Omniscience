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
* R736 (2026-11-17) adds the PATH: a ``;name=value`` path parameter's value is always masked (the name kept), and a path segment
  shaped like a credential (a UUID; 16+ hex digits; 24+ base64url characters holding a letter and a digit that are not lower-case
  words joined by ``-``/``_``) is masked, a short file extension kept. Slugs, dates, numeric ids and short segments read as they
  are; STATED LIMIT: a short or unusually shaped path token can still appear;
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


# --------------------------------------------------------------------------------------------------------------- R736: the path
#: A UUID, any case (``/feed/3f2b...-...``).
_UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
#: Sixteen or more hex digits and nothing else (a hex token, a digest).
_HEX_TOKEN_RE = re.compile(r"[0-9A-Fa-f]{16,}")
#: Twenty-four or more base64url characters (padding allowed)...
_B64URL_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{24,}={0,2}")
#: ...unless shaped like lower-case words joined by hyphens or underscores (an article slug, ``2026-11-16-climate-report-2025``). A
#: "word" is at most 20 characters: a 30-character run with an underscore before it (``ghp_<30 chars>``) is a token, not a word.
_WORDS_RE = re.compile(r"[a-z0-9]{1,20}(?:[-_][a-z0-9]{1,20})+")
#: A short file extension kept after a masked token (``/feeds/<token>.xml`` -> ``/feeds/***.xml``): the extension tells the format.
_EXTENSION_TAIL_RE = re.compile(r"[A-Za-z0-9]{1,5}")


def _split_extension(text: str) -> tuple[str, str] | None:
    """``(the rest, ".ext")`` when ``text`` ends in a dot and one to five letters or digits after a non-empty rest, else ``None``.
    Split at the last dot, with no backtracking regex over the rest (CodeQL's polynomial-regex alert on the first cut)."""
    rest, dot, ext = text.rpartition(".")
    if dot and rest and _EXTENSION_TAIL_RE.fullmatch(ext):
        return rest, "." + ext
    return None


def _looks_like_a_credential(segment: str) -> bool:
    """R736 (2): a path segment (percent-decoded) shaped like a token: a UUID; sixteen or more hex digits only; or twenty-four or
    more base64url characters holding a letter AND a digit that are not lower-case words joined by ``-``/``_`` (a "word" of twelve
    or more characters mixing letters and digits is not one: ``tok_abcdefghij1234567890``). Slugs, dates, numeric ids and short
    segments read as they are. Over-masking is the accepted cost (R736 (3))."""
    if _UUID_RE.fullmatch(segment) or _HEX_TOKEN_RE.fullmatch(segment):
        return True
    if not _B64URL_TOKEN_RE.fullmatch(segment):
        return False
    if not (any(c.isalpha() for c in segment) and any(c.isdigit() for c in segment)):
        return False
    bare = segment.rstrip("=")
    if not _WORDS_RE.fullmatch(bare):
        return True
    return any(len(w) >= 12 and any(c.isalpha() for c in w) and any(c.isdigit() for c in w) for w in re.split(r"[-_]", bare))


#: What a token is cut at inside a segment (``token=<hex>``, ``u:<hex>``, ``<a>,<b>``, ``x\<uuid>``, a JWT's dots).
_PIECE_SPLIT_RE = re.compile(r"[^A-Za-z0-9_\-]+")
#: Inside a segment: a UUID or a run of sixteen hex digits anywhere (``aaaa<uuid>``, ``<hex>-<hex>`` joined like a slug).
_HEX_INSIDE_RE = re.compile(r"[0-9A-Fa-f]{16,}")
#: The characters a standard-base64 token or a split one carries that base64url does not (``+``, ``/``, ``=``, ``.``, ``~``):
#: taken out, what is left is tested whole (the second security read on R736).
_JOINERS_RE = re.compile(r"[+/=.~]")


def _holds_a_credential(text: str) -> bool:
    """Whether a decoded segment is, or holds, a credential-shaped token (R736 (2), read wide after the security reads): the
    segment whole, a UUID or a sixteen-hex run anywhere in it, any piece of it between characters a token cannot hold, or the
    segment with the joiners of a standard-base64 or split token taken out."""
    if _looks_like_a_credential(text) or _UUID_RE.search(text) or _HEX_INSIDE_RE.search(text):
        return True
    if any(_looks_like_a_credential(piece) for piece in _PIECE_SPLIT_RE.split(text) if piece):
        return True
    joined = _JOINERS_RE.sub("", text)
    return joined != text and _looks_like_a_credential(joined)


def _masked_segment_value(text: str) -> str:
    """One segment's own text (before any ``;`` parameter) masked whole when it is or holds a credential-shaped token; a short
    extension after it kept when the rest alone holds the token (``/feeds/<token>.xml`` -> ``/feeds/***.xml``)."""
    decoded = _decoded(text)
    if not _holds_a_credential(decoded):
        return text
    found = _split_extension(decoded)
    if found and _holds_a_credential(found[0]) and not _holds_a_credential(found[1][1:]):
        return QUERY_VALUE_MASK + found[1]
    return QUERY_VALUE_MASK


def _masked_segment(segment: str) -> str:
    """R736 (1)+(2): a path segment with each ``;name=value`` parameter's VALUE masked (the name kept; a bare ``;item`` masked whole)
    and its own text masked when it is shaped like a credential."""
    own, semi, params = segment.partition(";")
    out = _masked_segment_value(own)
    if not semi:
        return out
    written = []
    for param in params.split(";"):
        name, eq, _value = param.partition("=")
        written.append(name + "=" + QUERY_VALUE_MASK if eq and _NAME_RE.fullmatch(name) else (param and QUERY_VALUE_MASK))
    return out + ";" + ";".join(written)


def _path_start(base: str) -> int:
    """Where the path of ``base`` (an address without its query and fragment) starts: after the authority when there is one
    (``scheme://`` or ``//``), else at 0 (a feed key's body after its host, or a bare path)."""
    found = base.find("://")
    if found >= 0 and "/" not in base[:found]:
        slash = base.find("/", found + 3)
        return len(base) if slash < 0 else slash
    if base.startswith("//"):
        slash = base.find("/", 2)
        return len(base) if slash < 0 else slash
    return 0


def masked_path(path: str) -> str:
    """``path`` with every segment written by :func:`_masked_segment` (R736). The ``/`` separators are kept as written. NEVER raises."""
    try:
        return "/".join(_masked_segment(segment) for segment in path.split("/"))
    except Exception:  # noqa: BLE001 - written from inside reports and failures; a path it cannot read is withheld whole
        return QUERY_VALUE_MASK


def masked_address(text: str, *, authority: bool = True) -> str:
    """``text`` (an address, or a feed key's body) with its fragment dropped, its query masked by :func:`masked_query` (R734) and its
    path by :func:`masked_path` (R736). The query starts at the FIRST ``?`` (an authority cannot hold one: every parser ends it there),
    the fragment at the first ``#``. The authority is returned as given, so the userinfo mask the caller applies is its own concern.
    ``authority=False`` for a text that is already the part from the path on (a feed key's, whose path can open with ``//``: the
    first security read on R736 found its first segment read as a host). NEVER raises."""
    try:
        head = text.split("#", 1)[0]
        base, mark, query = head.partition("?")
        start = _path_start(base) if authority else 0
        base = base[:start] + masked_path(base[start:])
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


def _path_secrets(path: str) -> list[str]:
    """The path tokens and path-parameter values :func:`masked_path` masks (R736), as written in ``path``."""
    out: list[str] = []
    for segment in path.split("/"):
        own, semi, params = segment.partition(";")
        if _masked_segment_value(own) != own:
            decoded = _decoded(own)
            out.append(own)
            found = _split_extension(decoded)
            if found:
                out.append(found[0])
            # each piece that is itself a token, for a library that quotes only part of the segment
            out += [piece for piece in _PIECE_SPLIT_RE.split(decoded) if piece and _holds_a_credential(piece)]
        if semi:
            for param in params.split(";"):
                name, eq, value = param.partition("=")
                out += [value] if eq and _NAME_RE.fullmatch(name) else [param]
                if param:
                    out.append(";" + param)  # row 107: the value in its context, so a short one leaves with its name
    return [p for p in out if p]


def query_secrets(text: str, *, floor: int = 4, authority: bool = True) -> tuple[str, ...]:
    """The query values :func:`masked_address` masks in ``text``, for a scrub to take out of an exception's text that quotes the
    address in its own words (requests writes ``url: /rss?token=...``). Each value is given alone AND in its context: the whole item
    (``pin=123``) and the item behind each separator a library writes before it (``?pin=123``, ``&pin=123``, ``;pin=123``), every one
    in every spelling :func:`_written_forms` lists.

    WHY THE CONTEXT (row 107): the scrub takes a secret out of free text only from ``floor`` characters up, and WITHHOLDS a whole text
    that holds a shorter one, since a one-to-three-character needle cannot be cut out of a sentence without cutting other words. A
    value alone under the floor (``?pin=123``) was therefore left out, and it stayed readable in the exception's text. Libraries quote
    the address in one piece, so the value is cut out with its name around it instead: ``pin=123`` reaches the floor where ``123``
    does not, and the rest of the sentence is kept. A value whose every context is still under the floor (``?1``) is handed over
    short, ON PURPOSE: the scrub then withholds that text, which is the fail-closed answer for the rare address that short.

    Empty when there is no query or it cannot be read. NEVER raises."""
    try:
        base, _mark, query = text.split("#", 1)[0].partition("?")
        out: list[str] = _path_secrets(base[_path_start(base) if authority else 0 :])
        for item in (_SEPARATOR_RE.split(query)[::2] if query else []):
            name, eq, value = item.partition("=")
            if not eq:
                if item and not (_NAME_RE.fullmatch(item) and _is_harmless(item)):
                    out += _in_context(item)
                continue
            if not _NAME_RE.fullmatch(name):
                out += (name, value, *_in_context(item))
            elif not (_is_harmless(name) and _KEPT_VALUE_RE.fullmatch(value)):
                out += [value, *_in_context(item)]
        forms: list[str] = []
        short: list[str] = []
        for part in out:
            written = [p for p in _written_forms(part) if p]
            forms += written
            if part[:1] in _CONTEXT_MARKS:
                # a value whose context is still under the floor (``?7``): handed over short, so the scrub withholds the text
                short += [p for p in written if len(p) < floor]
        return tuple(dict.fromkeys([p for p in forms if len(p) >= floor] + short))
    except Exception:  # noqa: BLE001 - written from inside a failure; no secret is better than a raise that replaces it
        return ()


#: The separators a library writes before a query item when it quotes the address (row 107).
_CONTEXT_MARKS = ("?", "&", ";")


def _in_context(item: str) -> list[str]:
    """``item`` (``name=value`` as written) behind each separator that can stand before it in a quoted address (row 107)."""
    return [item, *(mark + item for mark in _CONTEXT_MARKS)]
