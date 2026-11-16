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

# A line that is, IN FULL, a "this page needs JavaScript" notice: the notice's own wording from the
# start of the line, a short tail with no clause break (no comma or semicolon), and a word cap. A news
# sentence that only mentions JavaScript ("The exploit works even when JavaScript is disabled,
# researchers said") does not start with the notice and is kept.
_JS_NOTICE_RES = (
    # "Enable JavaScript to view this site." / "You need to enable JavaScript to run this app."
    re.compile(r"^(?:please\s+)?(?:you\s+(?:need|have|must)\s+(?:to\s+)?)?(?:enable|turn\s+on|activate|allow)\s+javascript\b[^,;]{0,60}$"),
    # "LessWrong requires JavaScript to run." / "This site needs JavaScript to work properly."
    re.compile(r"^[^,;]{1,40}?\s(?:requires|needs)\s+javascript(?:\s+(?:to|in\s+order\s+to)\s+[^,;]{1,40})?$"),
    # "JavaScript is disabled in your browser." / "JavaScript must be enabled to view this page."
    re.compile(r"^javascript\s+(?:is\s+(?:required|disabled|not\s+enabled|not\s+available|turned\s+off)|must\s+be\s+(?:enabled|turned\s+on))\b[^,;]{0,60}$"),
    # The framework template line: "We're sorry but X doesn't work properly without JavaScript enabled."
    re.compile(r"^we['’]re\s+sorry\s+but\s+[^,;]{1,40}\s+doesn['’]?t\s+work\s+properly\s+without\s+javascript\s+enabled\b[^,;]{0,60}$"),
)
_JS_NOTICE_MAX_WORDS = 16

# A line that is, IN FULL, a media player's Flash notice ("To play the media you will need to either
# update your browser to a recent version or update your Flash plugin."). "Adobe ended support for
# Flash Player in 2020, and users no longer need to install it" is a sentence, not the notice.
_FLASH_NOTICE_RES = (
    re.compile(r"^(?:to\s+(?:play|view|watch|see|listen\s+to)\b[^,;]{0,120}?\s)?(?:update|install|download|enable|upgrade)\s+(?:the\s+|your\s+)?(?:latest\s+(?:version\s+of\s+)?)?(?:adobe\s+)?flash\s+(?:player|plugin|plug-in)\b[^,;]{0,40}$"),
    re.compile(r"^you\s+(?:need|must\s+have|will\s+need)\s+(?:to\s+(?:install|update|download|enable)\s+)?(?:the\s+)?(?:latest\s+(?:version\s+of\s+)?)?(?:adobe\s+)?flash\s+(?:player|plugin|plug-in)\b[^,;]{0,60}$"),
    re.compile(r"^this\s+(?:content|video|media|player|page|site)\s+requires\s+(?:the\s+)?(?:latest\s+)?(?:adobe\s+)?flash\b[^,;]{0,60}$"),
)
_FLASH_HEADINGS = frozenset({"update required", "flash required", "flash player required"})
_FLASH_MAX_WORDS = 40

PHP_ERROR_ONLY = frozenset({"php_error"})

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
    low = text.casefold().strip(_EDGE)
    if words <= _JS_NOTICE_MAX_WORDS and any(r.search(low) for r in _JS_NOTICE_RES):
        return "js_required"
    if low in _FLASH_HEADINGS:
        return "flash_required"
    for heading in _FLASH_HEADINGS:  # "Update Required: To play the media ... Flash plugin." on one line
        if low.startswith(heading) and low[len(heading):len(heading) + 1] in (":", ".", " ", "-", "–", "—"):
            low = low[len(heading):].strip(_EDGE)
            break
    if words <= _FLASH_MAX_WORDS and any(r.search(low) for r in _FLASH_NOTICE_RES):
        return "flash_required"
    return None


def strip_notices(text: str, *, kinds: frozenset[str] | None = None) -> tuple[str, dict[str, int]]:
    """``(text without its notice lines, {kind: lines removed})``.

    Only the notice lines at the TOP and the BOTTOM of the body go (a run from either edge; blank
    lines do not break it), which is where a server prints its error dump and a page its notice. A
    notice line quoted in the middle of an article (a PHP tutorial showing the warning it explains)
    is the article's text and stays, and so does a closing run that the line before it introduces
    ("Running the script prints:"). ``kinds`` limits which notices may go (all by default). Every
    kept line is byte for byte; text without notices comes back identical, with an empty dict."""
    lines = (text or "").splitlines(keepends=True)
    found = [notice_kind(line) for line in lines]
    if kinds is not None:
        found = [k if k in kinds else None for k in found]
    start = 0
    while start < len(lines) and (found[start] is not None or not lines[start].strip()):
        start += 1
    end = len(lines)
    while end > start and (found[end - 1] is not None or not lines[end - 1].strip()):
        end -= 1
    if end < len(lines) and end > start and lines[end - 1].rstrip().endswith(":"):
        end = len(lines)  # the article quotes what follows its colon
    removed: dict[str, int] = {}
    for i, kind in enumerate(found):
        if kind is not None and not (start <= i < end):
            removed[kind] = removed.get(kind, 0) + 1
    if not removed:
        return text, {}
    return "".join(lines[start:end]).strip(), removed


NAV_RUN_MIN_LINES = 8   # a byline, a date and a photo credit make three short lines; a menu makes many
NAV_ENTRY_MAX_CHARS = 25
_SENTENCE_END = ".!?…:;»\"”’)。！？」』；：؟۔।॥"
NAV_ENTRY_MAX_WORDS = 3   # "Logga in", "Sport", "World news": a poem line or a sentence runs longer
NAV_ENTRY_MAX_CJK = 8     # a CJK menu entry is a few characters; a CJK sentence without its full stop is not
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def _is_nav_entry(line: str) -> bool:
    text = line.strip()
    return (
        0 < len(text) <= NAV_ENTRY_MAX_CHARS
        and not text.endswith(tuple(_SENTENCE_END))
        and not any(ch.isdigit() for ch in text)  # a date, a score or a time is data, not a menu entry
        and not any(ch in ",，、;；" for ch in text)  # a clause break is a sentence, not a menu entry
        and len(text.split()) <= NAV_ENTRY_MAX_WORDS
        and not (_CJK_RE.search(text) and len(text) > NAV_ENTRY_MAX_CJK)
    )


# Section names a news site's menu carries, in the app's languages and the Nordic ones the field report
# met. A run is a menu only when most of its entries are such names: a haiku, a poem or a film's
# credits are short unpunctuated lines too, and none of them reads "News, Sport, Culture".
_NAV_WORD_TEXT = """
home news world politics business economy sport sports culture arts opinion science technology tech health
travel lifestyle weather video videos podcasts podcast local national international entertainment
latest menu search subscribe login register contact about more live
hem nyheter inrikes utrikes kultur ekonomi debatt väder ledare nöje prenumerera
etusivu uutiset urheilu kulttuuri talous mielipide sää kirjaudu
forside nyheder indland udland kultur erhverv vejret nyheter innenriks utenriks økonomi været
accueil actualités monde politique économie sport culture opinions sciences météo connexion
startseite nachrichten politik wirtschaft kultur meinung wissen wetter anmelden
inicio noticias mundo política economía deportes cultura opinión ciencia tiempo
início notícias mundo política economia esportes desporto cultura opinião ciência tempo
главная новости мир политика экономика спорт культура мнения наука погода
beranda berita dunia politik ekonomi olahraga budaya opini sains cuaca
ホーム ニュース 国際 政治 経済 スポーツ 文化 社会 天気
首页 新闻 国际 政治 经济 体育 文化 社会 科技 天气 评论
होम समाचार देश दुनिया राजनीति खेल मनोरंजन व्यापार
প্রচ্ছদ খবর দেশ বিদেশ রাজনীতি খেলা বিনোদন অর্থনীতি
الرئيسية أخبار العالم سياسة اقتصاد رياضة ثقافة رأي علوم الطقس
"""
_NAV_WORDS = frozenset(w.casefold() for w in _NAV_WORD_TEXT.split()) | {"log in", "sign in", "logga in", "logg inn"}


def strip_leading_nav(text: str, *, keep_min_chars: int) -> tuple[str, int]:
    """``(text without its leading menu run, entries removed)``. A run is at least
    ``NAV_RUN_MIN_LINES`` consecutive menu-entry lines (blank lines between them do not break it)
    starting at the first line of the body, most of them section names (``_NAV_WORDS``). It goes only when at least ``keep_min_chars`` of body
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
    named = sum(line.strip().casefold() in _NAV_WORDS for line in lines[:cut] if line.strip())
    if named * 2 < entries:
        return text, 0  # short lines that are not section names: verse, credits, a list
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
    # A statement ends in ";" in every specimen; a headline about code ("JavaScript's => arrow functions
    # (and why () {} matter)") carries the punctuation but not a statement.
    return (
        bool(_CODE_TOKEN_RE.search(title)) and ";" in title and sum(ch in _CODE_PUNCT for ch in title) >= 3
    )
