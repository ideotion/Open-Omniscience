"""Which text encoding a fetched page's bytes are in (R699, cause 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The 2026-10-06 keyword triage found Chinese keywords such as ``гҗӯ`` and
``еӣҫе`` (``docs/ledger/OPEN_QUEUE.md``, "WHAT THE KEYWORD TRIAGE RUN EXPOSED", cause 2):
UTF-8 Chinese read as a single-byte Cyrillic charset. ``еӣҫзүҮ`` is exactly what the UTF-8
bytes of 图片 give under ``ptcp154``, and that is what ``charset_normalizer`` answers for a
UTF-8 page carrying ONE stray invalid byte, or a body cut off in the middle of a character
(measured 2026-11-14: a 2 KB Chinese page answers ``utf_8`` whole and ``ptcp154`` with one
byte broken). The fetcher asked the guesser whenever a server sent no charset, and never
read the page's own ``<meta charset>``.

THE ORDER, strongest evidence first:

1. a byte-order mark -- it cannot be there by accident;
2. a UTF-16/UTF-32 charset the server declared -- such a body is never mistaken for UTF-8
   by the test below, so the declaration is the only evidence;
3. the bytes ARE UTF-8: they hold multi-byte UTF-8 sequences and at most one invalid
   sequence per :data:`UTF8_MIN_VALID_PER_INVALID` valid non-ASCII characters. Text in a
   single-byte charset almost never forms valid UTF-8 sequences (a Cyrillic or Western
   letter byte above 0x7F would need the right continuation bytes after it), so this
   overrides even a declared single-byte charset -- a server's default header is the most
   common way a UTF-8 page gets mislabelled;
4. a charset the server declared, unless it is the ISO-8859-1 that ``requests`` reports
   for ANY unlabelled text response (the previous code's rule, kept);
5. the page's own ``<meta charset>`` / ``http-equiv`` declaration in its first bytes;
6. ``charset_normalizer``'s guess;
7. UTF-8.

Every answer is a name ``codecs.lookup`` knows, so ``bytes.decode`` cannot raise
``LookupError`` on it.
"""

from __future__ import annotations

import codecs
import re

#: How many valid non-ASCII characters the body must hold per invalid UTF-8 sequence for
#: it to read as UTF-8. One broken byte in a long page (a truncated tail, a stray Latin-1
#: character pasted in) does not make the other thousands wrong; a single-byte page fails
#: on nearly every non-ASCII byte and is nowhere near this ratio.
UTF8_MIN_VALID_PER_INVALID = 50

#: A page this rich in valid UTF-8 survives ONE invalid sequence even below the ratio above
#: (a short Chinese page with one stray byte). A single-byte page that happens to form this
#: many valid multi-byte sequences is the double-encoded mojibake case, already broken text.
UTF8_MIN_VALID_FOR_ONE_INVALID = 8

#: How far into the body a ``<meta>`` declaration is looked for (the HTML standard's
#: prescan reads 1,024 bytes; pages with long preambles put it later, so a little more).
META_PRESCAN_BYTES = 4096

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

# ``charset=`` inside a <meta> tag, quoted or not. Bounded input (META_PRESCAN_BYTES) and a
# single [^>] run per tag, so it is linear in practice and bounded in the worst case.
_META_CHARSET = re.compile(
    rb"<meta\b[^>]{0,512}?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:\-]{1,40})", re.IGNORECASE
)

#: ``codecs``' name for ISO-8859-1, which ``requests`` reports for ANY text response whose
#: header names no charset, so it is not evidence of anything.
_UNRELIABLE_DECLARED = {"iso8859-1"}


def _canonical(name: str | None) -> str | None:
    """``codecs``' own name for an encoding label, or ``None`` when it knows none."""
    if not name:
        return None
    try:
        return codecs.lookup(name.strip().strip("\"'")).name
    except (LookupError, TypeError, ValueError):
        return None


def _is_wide(name: str) -> bool:
    return name.startswith(("utf-16", "utf-32", "utf_16", "utf_32"))


def looks_like_utf8(raw: bytes) -> bool:
    """True when ``raw`` holds non-ASCII UTF-8 text with (almost) no invalid sequences.

    An incomplete character at the very END is not counted as invalid: a body cut at the
    size cap, or by a dropped connection, ends mid-character. Elsewhere one invalid
    sequence is allowed per :data:`UTF8_MIN_VALID_PER_INVALID` valid non-ASCII characters,
    and a lone one once the page holds at least :data:`UTF8_MIN_VALID_FOR_ONE_INVALID`.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(raw, final=False)  # a cut-off final character stays buffered
    replaced = text.count("\ufffd")
    invalid = replaced - raw.count(b"\xef\xbf\xbd")  # a real U+FFFD in the page is not an error
    non_ascii = len(text) - len(text.encode("ascii", errors="ignore"))
    valid = non_ascii - replaced
    if valid <= 0:
        return False
    if invalid <= 0:
        return True
    allowed = valid // UTF8_MIN_VALID_PER_INVALID
    if valid >= UTF8_MIN_VALID_FOR_ONE_INVALID:
        allowed = max(1, allowed)
    return invalid <= allowed


def meta_charset(raw: bytes) -> str | None:
    """The encoding a page declares in a ``<meta>`` tag near its start, if it names one."""
    m = _META_CHARSET.search(raw[:META_PRESCAN_BYTES])
    if not m:
        return None
    name = _canonical(m.group(1).decode("ascii", errors="ignore"))
    # A page cannot declare a wide encoding about itself in ASCII-compatible bytes; the
    # HTML standard reads such a declaration as UTF-8.
    if name and _is_wide(name):
        return "utf-8"
    return name


def _sniffed(raw: bytes) -> str | None:
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        return _canonical(best.encoding) if best else None
    except Exception:  # noqa: BLE001 - detection is best-effort
        return None


def choose_encoding(raw: bytes, declared: str | None) -> str:
    """The encoding to decode ``raw`` with; ``declared`` is what the server's header said."""
    for bom, name in _BOMS:
        if raw.startswith(bom):
            return name
    header = _canonical(declared)
    if header and _is_wide(header):
        return header
    if looks_like_utf8(raw):
        return "utf-8"
    if header and header not in _UNRELIABLE_DECLARED:
        return header
    return meta_charset(raw) or _sniffed(raw) or "utf-8"
