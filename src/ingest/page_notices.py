"""
Page notices, leading menu runs and code titles: what the extractor keeps that is not the article.

Field report 2026-11-14 (sections 5.2 and 10 P2 item 8, open-on-main row 66) found pages stored as
articles whose body was a server's PHP error dump (polonia1.tv: Drupal "Deprecated function ...
(line N of .../ControllerResolver.php)"), a "requires javascript" notice (lesswrong.com), an audio
player's Flash "Update Required" notice (radiosabadell.fm), a run of menu entries before the
headline, and titles that were JavaScript code (ajol.info). Each rule here is EXPLICIT and narrow,
with a disclosed reason, never a score:

* :func:`strip_notices` removes LINES that are, in full, one of those notices. It never touches a
  line that merely mentions PHP, JavaScript or Flash in a sentence: a PHP error line must carry the
  interpreter's own "in FILE.php on line N" or Drupal's "(line N of FILE.php)" shape, and a
  JavaScript or Flash notice must be a short line. The caller judges what is left: a body that was
  only notices is not an article, and that is a COUNTED outcome at the ingest door, never a silent
  drop.
* :func:`strip_leading_nav` removes a run of menu entries at the very TOP of the body (at least
  ``NAV_RUN_MIN_LINES`` short, unpunctuated, digit-free lines before the first line that is not
  one), and only when what remains is still a body.
* :func:`is_code_title` says a title is JavaScript, so the caller stores NO title rather than code.

Precision first, as in :mod:`src.ingest.furniture`: a false positive changes a real article.
Only pages ingested from now on pass through here; stored articles are not re-extracted.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re

# A PHP diagnostic line, as PHP itself prints it ("Deprecated: X in /var/www/a.php on line 12") or
# as Drupal's error handler does ("Deprecated function: X in Y() (line 12 of /var/www/core/a.php)").
_PHP_LEVEL = r"(?:PHP\s+)?(?:Deprecated(?:\s+function)?|Warning|Notice|Fatal\s+error|Parse\s+error|Strict\s+Standards|User\s+(?:deprecated|warning|notice|error))"
_PHP_FILE = r"\S+\.(?:php|inc|module|theme|install|engine)"
_PHP_ERROR_RE = re.compile(
    rf"^\s*{_PHP_LEVEL}\s*:.*(?:\bin\s+{_PHP_FILE}\s+on\s+line\s+\d+|\(line\s+\d+\s+of\s+{_PHP_FILE}\))",
    re.IGNORECASE,
)
# A stack-trace frame under such an error ("#0 /var/www/core/lib/a.php(123): f()").
_PHP_FRAME_RE = re.compile(rf"^\s*#\d+\s+(?:{_PHP_FILE}\(\d+\)|\{{main\}}|\[internal function\])", re.IGNORECASE)

# A SHORT line that is a "this page needs JavaScript" notice.
_JS_NOTICE_PHRASES = (
    "requires javascript", "javascript is required", "javascript is disabled", "enable javascript",
    "javascript must be enabled", "needs javascript", "turn on javascript", "javascript enabled to",
    "without javascript",
)
_JS_NOTICE_MAX_WORDS = 25

# A SHORT line that is a media player's Flash notice ("Update Required: To play the media you will
# need to either update your browser to a recent version or update your Flash plugin.").
_FLASH_RE = re.compile(r"\bflash\s+(?:plugin|player|plug-in)\b", re.IGNORECASE)
_FLASH_VERB_RE = re.compile(r"\b(?:update|install|download|enable|required|need)\b", re.IGNORECASE)
_FLASH_HEADINGS = frozenset({"update required", "flash required", "flash player required"})
_FLASH_MAX_WORDS = 40

_EDGE = " \t .:;!?-–—·•|"


def notice_kind(line: str) -> str | None:
    """``"php_error"``, ``"js_required"`` or ``"flash_required"`` when ``line`` is, in full, one of
    those notices; ``None`` otherwise (including for any sentence that only mentions them)."""
    text = line.strip()
    if not text:
        return None
    if _PHP_ERROR_RE.search(text) or _PHP_FRAME_RE.search(text):
        return "php_error"
    words = len(text.split())
    low = text.casefold()
    if words <= _JS_NOTICE_MAX_WORDS and "javascript" in low and any(p in low for p in _JS_NOTICE_PHRASES):
        return "js_required"
    if low.strip(_EDGE) in _FLASH_HEADINGS:
        return "flash_required"
    if words <= _FLASH_MAX_WORDS and _FLASH_RE.search(text) and _FLASH_VERB_RE.search(text):
        return "flash_required"
    return None


def strip_notices(text: str) -> tuple[str, dict[str, int]]:
    """``(text without notice lines, {kind: lines removed})``. Every other line is kept byte for
    byte; text without notices comes back identical, with an empty dict."""
    lines = (text or "").splitlines(keepends=True)
    kept: list[str] = []
    removed: dict[str, int] = {}
    for line in lines:
        kind = notice_kind(line)
        if kind is None:
            kept.append(line)
        else:
            removed[kind] = removed.get(kind, 0) + 1
    if not removed:
        return text, {}
    return "".join(kept).strip(), removed


NAV_RUN_MIN_LINES = 8   # a byline, a date and a photo credit make three short lines; a menu makes many
NAV_ENTRY_MAX_CHARS = 25
_SENTENCE_END = ".!?…:;»\"”’)"


def _is_nav_entry(line: str) -> bool:
    text = line.strip()
    return (
        0 < len(text) <= NAV_ENTRY_MAX_CHARS
        and not text.endswith(tuple(_SENTENCE_END))
        and not any(ch.isdigit() for ch in text)  # a date, a score or a time is data, not a menu entry
    )


def strip_leading_nav(text: str, *, keep_min_chars: int) -> tuple[str, int]:
    """``(text without its leading menu run, entries removed)``. A run is at least
    ``NAV_RUN_MIN_LINES`` consecutive menu-entry lines (blank lines between them do not break it)
    starting at the first line of the body. It goes only when at least ``keep_min_chars`` of body
    remain after it; otherwise the text comes back unchanged, so this never makes a stub."""
    lines = (text or "").splitlines(keepends=True)
    entries = 0
    cut = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if not _is_nav_entry(line):
            cut = i
            break
        entries += 1
    else:
        return text, 0  # the whole body is short lines: a menu page, which is not this function's call
    if entries < NAV_RUN_MIN_LINES:
        return text, 0
    rest = "".join(lines[cut:]).strip()
    if len(rest) < keep_min_chars:
        return text, 0
    return rest, entries


# A title that is JavaScript: a keyword of the language AND code punctuation, which a headline about
# JavaScript ("Why JavaScript frameworks keep changing") does not carry.
_CODE_TOKEN_RE = re.compile(
    r"\bfunction\s*\(|=>|\b(?:var|let|const)\s+[\w$]+\s*=|\b(?:window|document)\.\w|\bgtag\(|\bdataLayer\b"
    r"|\$\(\s*(?:document|function|['\"])|\breturn\s+[\w$!]+\s*;"
)
_CODE_PUNCT = frozenset("{}();=")


def is_code_title(title: str | None) -> bool:
    if not title:
        return False
    return bool(_CODE_TOKEN_RE.search(title)) and sum(ch in _CODE_PUNCT for ch in title) >= 3
