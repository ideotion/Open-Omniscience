"""What the article search index stores for Arabic, Chinese and Japanese text.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULINGS. Q507 = a: Arabic is folded at index AND query time (alef, teh marbuta and yeh,
beside the tokenizer's ``remove_diacritics 2``). Q506 🔒 = b: Chinese and Japanese are
segmented by a real segmenter (``jieba`` for zh, ``sudachipy`` for ja). Brief ``S04-07`` S8.

WHAT THE TOKENIZER DOES WITHOUT THIS, measured on SQLite 3.45 with the index's own
``unicode61 remove_diacritics 2``:

* An unbroken run of Chinese or Japanese characters is ONE token. "东京大学的学生" indexes as
  that whole string, so a search for "东京" finds nothing.
* Arabic harakat are SEPARATORS, not diacritics to remove: a vocalised "مَدْرَسَةٌ" indexes as
  five one-letter tokens. Tatweel is kept inside the token, so "ـــكتاب" is not "كتاب". And
  "أحمد" and "احمد" are different words.

So the index cannot be fixed by a tokenizer option (FTS5 offers none for either), and a
custom tokenizer cannot be registered from Python's ``sqlite3``. The transform therefore
runs BEFORE the tokenizer, as a SQL function the sync triggers call, and the same transform
shapes each query literal. The tokenizer and the table are unchanged.

THE ONE RULE THAT MAKES THIS SAFE: AN EXTERNAL-CONTENT FTS5 ``'delete'`` MUST BE GIVEN
EXACTLY THE VALUES THAT WERE INDEXED. Handing it anything else silently corrupts the index.
Every document indexed before this existed was indexed raw, and what the transform does
depends on which segmenters are installed at the time. So each document's entry is
RECORDED: ``article_fts_norm(article_id, mask, title, content)`` has a row for every
document whose indexed text differs from its stored text (no row: indexed raw).

* The Arabic fold is this module's own code and never changes meaning under a bit (a new
  fold would get a new bit), so for it the MASK is enough: the delete side re-folds the
  stored text and gets exactly what was indexed.
* A segmenter is a third-party package. A new dictionary release segments the same text
  differently, and an uninstall cannot segment it at all; either way, re-running it at
  delete time would hand FTS5 the wrong values. So a document a segmenter touched keeps
  the EXACT values it was indexed with in its row, and the delete side reads them back.
  That costs a second copy of those documents' indexed text, and only theirs; it buys a
  delete that is exact whatever happens to the package later.

The table's name starts with ``article_fts`` on purpose: every place that skips the FTS
shadow tables by that prefix (backups, table counts, the merge) skips it too, and every
place that rebuilds the index rebuilds it too.

WHY BY SCRIPT, NOT BY LANGUAGE. The trigger sees only the text: an article's detected
language is written after the row. Arabic folding touches only Arabic-script code points,
so applying it to every text changes nothing else. A text containing kana is Japanese; a
text with Han characters and no kana is segmented as Chinese.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable
from functools import lru_cache

logger = logging.getLogger(__name__)

#: The SQL function names the triggers call. Kept here so the DDL and the registration
#: cannot drift apart.
FN_NORM = "oo_fts_norm"  # (text, mask) -> the text as it is indexed under that mask
FN_CAPS = "oo_fts_caps"  # () -> the mask this connection would index new text under
FN_USED = "oo_fts_used"  # (title, content, caps) -> the part of caps that changes either text

#: The per-document record. See the module docstring.
STATE_TABLE = "article_fts_norm"

# The mask's bits. A NEW transform gets a NEW bit and never changes what an old one does:
# a document indexed under bit 1 in 2026 must still delete cleanly under bit 1 later.
ARABIC = 1  # Q507: strip harakat + tatweel, fold alef / teh marbuta / alef maksura
ZH_JIEBA = 2  # Q506: Han text without kana, segmented by jieba (search mode)
JA_SUDACHI = 4  # Q506: text containing kana, segmented by sudachipy (mode C + its A units)

#: The bits whose output comes from a third-party package, so a document they touched keeps
#: its exact indexed values (see the module docstring).
SEGMENTERS = ZH_JIEBA | JA_SUDACHI

#: When each segmenter was last verified against this module: the versions the tests ran on
#: and the behaviour the query side relies on (configs/external_artifacts.yml).
JIEBA_AS_OF = "2026-09-25"  # jieba 0.42.1: cut_for_search on the index, cut on queries
SUDACHI_AS_OF = "2026-09-25"  # sudachipy 0.7.0 + sudachidict_core 20260723.1: mode C + A units

# --------------------------------------------------------------------------- #
# Arabic (Q507)
# --------------------------------------------------------------------------- #

# Harakat / tashkeel, Quranic annotation marks, the superscript alef, and tatweel: the
# marks unicode61 treats as separators (so it shreds a vocalised word) plus the one
# lengthening character it keeps inside a token. The same mark ranges the keyword
# extractor keeps as word continuations (``extract._ARABIC_MARKS``); tatweel is added.
_AR_STRIP = re.compile("[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭـ]")
_AR_FOLD = str.maketrans(
    {
        "أ": "ا",  # أ alef with hamza above -> ا
        "إ": "ا",  # إ alef with hamza below -> ا
        "آ": "ا",  # آ alef with madda -> ا
        "ٱ": "ا",  # ٱ alef wasla -> ا
        "ة": "ه",  # ة teh marbuta -> ه
        "ى": "ي",  # ى alef maksura -> ي
    }
)
_AR_ANY = re.compile(
    "[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭـ"
    "آأإةىٱ]"
)


def fold_arabic(text: str) -> str:
    """Q507's fold. Touches Arabic-script code points only; any other text is returned
    unchanged (the brief's negative space: a folded query never matches a non-Arabic token
    it did not match before)."""
    if not _AR_ANY.search(text):
        return text
    return _AR_STRIP.sub("", text).translate(_AR_FOLD)


# --------------------------------------------------------------------------- #
# Chinese and Japanese (Q506)
# --------------------------------------------------------------------------- #

_KANA = re.compile("[぀-ゟ゠-ヿㇰ-ㇿｦ-ﾟ]")
_HAN = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0002fa1f]")
# A maximal run the tokenizer would otherwise index whole: ideographs, kana, the
# iteration mark and the prolonged-sound mark.
_CJK_RUN = re.compile(
    "[々〆぀-ゟ゠-ヿㇰ-ㇿ㐀-䶿一-鿿"
    "豈-﫿ｦ-ﾟ\U00020000-\U0002fa1f]+"
)


def _enabled() -> bool:
    # The same switch the keyword extractor's segmentation reads.
    return os.getenv("OO_SEGMENTATION", "1") != "0"


@lru_cache(maxsize=1)
def _jieba():
    try:
        import jieba

        jieba.setLogLevel(60)
        return jieba
    except Exception:  # noqa: BLE001 - not installed: the bit is simply unavailable
        return None


_JIEBA_READY = threading.Lock()
_jieba_initialised = False


def _jieba_ready():
    """jieba builds its prefix dictionary once (~0.7 s, ~70 MB), on first real use."""
    global _jieba_initialised
    jb = _jieba()
    if jb is None:
        return None
    if not _jieba_initialised:
        with _JIEBA_READY:
            if not _jieba_initialised:
                jb.initialize()
                _jieba_initialised = True
    return jb


@lru_cache(maxsize=1)
def _sudachi_dictionary():
    """sudachipy's core dictionary, loaded once per process, or None when either is missing."""
    try:
        from sudachipy import Dictionary, SplitMode

        return Dictionary(dict="core"), SplitMode
    except Exception:  # noqa: BLE001 - not installed, or its dictionary is missing
        return None


_SUDACHI_LOCAL = threading.local()


def _sudachi():
    """A sudachipy tokenizer for THIS thread, or None.

    One per thread: a shared tokenizer used from four threads at once raised "Tokenizer is
    already in use" (measured, sudachipy 0.7.0), and the triggers run on whichever thread
    holds the connection. The dictionary is shared; a tokenizer over it costs nothing."""
    d = _sudachi_dictionary()
    if d is None:
        return None
    tok = getattr(_SUDACHI_LOCAL, "tok", None)
    if tok is None:
        dic = d[0]
        # 0.7 renamed create() to tokenizer(); 0.6 has only create().
        tok = dic.tokenizer() if hasattr(dic, "tokenizer") else dic.create()
        _SUDACHI_LOCAL.tok = tok
    return tok, d[1]


def available_mask() -> int:
    """The transforms this process can apply right now. Arabic folding needs nothing."""
    mask = ARABIC
    if _enabled():
        if _jieba() is not None:
            mask |= ZH_JIEBA
        if _sudachi() is not None:
            mask |= JA_SUDACHI
    return mask


def _zh_tokens(run: str, *, for_query: bool) -> list[str]:
    jb = _jieba_ready()
    if jb is None:
        raise SegmenterMissing("jieba")
    # Index in search mode (a compound AND its dictionary sub-words: 东京大学 -> 东京, 大学,
    # 东京大学) so a search for a part finds the whole; query in the default mode, whose
    # token is always among what search mode indexed. The common practice for jieba search.
    words = jb.cut(run) if for_query else jb.cut_for_search(run)
    return [w for w in words if w.strip()]


def _ja_tokens(run: str, *, for_query: bool) -> list[str]:
    sd = _sudachi()
    if sd is None:
        raise SegmenterMissing("sudachipy")
    tok, mode = sd
    out: list[str] = []
    for m in tok.tokenize(run, mode.C):
        surface = m.surface()
        if not surface.strip():
            continue
        if not for_query:
            # The same shape as jieba's search mode: the short units, then the long word.
            parts = [p.surface() for p in m.split(mode.A)]
            if len(parts) > 1:
                out.extend(p for p in parts if p.strip())
        out.append(surface)
    return out


class SegmenterMissing(RuntimeError):
    """A document was indexed under a segmenter this process does not have.

    Raised rather than guessed at: the delete that needs it must hand FTS5 the exact
    indexed values, and a guess would corrupt the index silently. The trigger then fails
    and the write that fired it is refused, which is loud and repairable."""


def _segment_bit(text: str, mask: int) -> int:
    """Which segmenter bit of ``mask`` applies to this text, by script alone (0: none).

    A text containing kana is Japanese, all of it; Han without kana is Chinese. Read off
    the characters rather than segmenting, so the triggers can ask cheaply."""
    if not (mask & (ZH_JIEBA | JA_SUDACHI)) or not _CJK_RUN.search(text):
        return 0
    if _KANA.search(text) is not None:
        return JA_SUDACHI if mask & JA_SUDACHI else 0
    return ZH_JIEBA if mask & ZH_JIEBA and _HAN.search(text) else 0


def _segment(text: str, mask: int, *, for_query: bool) -> tuple[str, int]:
    """Space-separate every CJK run under ``mask``; return the text and the bit it used."""
    bit = _segment_bit(text, mask)
    if not bit:
        return text, 0
    seg = _ja_tokens if bit == JA_SUDACHI else _zh_tokens
    return _CJK_RUN.sub(lambda m: " " + " ".join(seg(m.group(0), for_query=for_query)) + " ", text), bit


def normalize(text: str | None, mask: int) -> str | None:
    """The text exactly as the index holds it for a document indexed under ``mask``.

    Deterministic for a given mask and installed segmenter version. ``mask == 0`` is the
    identity, which is what every document indexed before this module existed holds."""
    if text is None or not mask:
        return text
    out = fold_arabic(text) if mask & ARABIC else text
    out, _used = _segment(out, mask, for_query=False)
    return out


def used_mask(title: str | None, content: str | None, caps: int) -> int:
    """The bits of ``caps`` that change the title or the content. 0 means the document is
    indexed exactly as stored, so it needs no record at all."""
    used = 0
    for t in (title, content):
        if not t:
            continue
        if caps & ARABIC and _AR_ANY.search(t):
            used |= ARABIC
        used |= _segment_bit(t, caps)
    return used


def index_entry(title: str | None, content: str | None, caps: int) -> tuple[int, str | None, str | None]:
    """``(mask, title, content)`` exactly as the index holds a document written under
    ``caps``. The mask is 0, and the text returned as stored, when nothing applies."""
    mask = used_mask(title, content, caps)
    if not mask:
        return 0, title, content
    return mask, normalize(title, mask), normalize(content, mask)


def indexed_values(
    title: str | None,
    content: str | None,
    mask: int,
    kept_title: str | None,
    kept_content: str | None,
) -> tuple[str | None, str | None]:
    """The values a document's CURRENT index entry was written with, from its stored text
    and its ``article_fts_norm`` row (``mask`` 0 and no kept values when it has none).

    What an FTS5 ``'delete'`` must be handed. Never runs a segmenter, so it answers the same
    after a dictionary upgrade or an uninstall; the triggers compute the same thing in SQL."""
    if mask & SEGMENTERS:
        return kept_title, kept_content
    if mask:
        return normalize(title, mask), normalize(content, mask)
    return title, content


def query_variants(literal: str, caps: int | None = None) -> list[str | tuple[str, ...]]:
    """Every form a query literal must take to find its documents, the literal first.

    A string is matched as a phrase, as every literal always was. A TUPLE is a segmented
    literal: its words must occur NEAR each other rather than as a strict phrase, because
    the index holds a compound's dictionary sub-words beside it (search mode, so "东京" finds
    "东京大学"), and those sit between the words a query segments into -- a strict phrase
    of "北京 参加 了 气候变化" would miss the very sentence it was copied from.

    The literal itself stays, because documents indexed before the search re-index hold
    their text raw. A Han-only literal gets BOTH segmentations: it cannot say whether it is
    Chinese or Japanese, and the index holds documents of both."""
    caps = available_mask() if caps is None else caps
    out: list[str | tuple[str, ...]] = [literal]
    folded = fold_arabic(literal) if caps & ARABIC else literal
    if folded not in out:
        out.append(folded)
    if _CJK_RUN.search(folded):
        japanese = _KANA.search(folded) is not None
        tries = [JA_SUDACHI] if japanese else [ZH_JIEBA, JA_SUDACHI]
        for bit in tries:
            if not caps & bit:
                continue
            try:
                seg, used = _segment(folded, bit, for_query=True)
            except SegmenterMissing:
                continue
            words = tuple(seg.split())
            if not used or not words:
                continue
            form: str | tuple[str, ...] = words[0] if len(words) == 1 else words
            if form not in out:
                out.append(form)
    return out


# --------------------------------------------------------------------------- #
# Registration on a connection
# --------------------------------------------------------------------------- #


def _normalize_sql(text: str | None, mask: int) -> str | None:
    """``normalize`` as the triggers call it.

    SQLite reports any exception from a SQL function as "user-defined function raised
    exception", which names nothing. The one failure an operator can act on is therefore
    logged here, with its cause and its fix, before the write is refused."""
    try:
        return normalize(text, mask)
    except SegmenterMissing as exc:
        logger.error(
            "search index: a document was indexed with the %s segmenter, which this install "
            "no longer has, so the write that changes it is refused rather than risk the "
            "index. Install %s again (sudachipy comes with the [segmentation] extra).",
            exc,
            exc,
        )
        raise


def register(dbapi_connection) -> None:
    """Register the three functions the sync triggers call on one SQLite connection.

    Every connection that can write ``articles`` needs them: a trigger calling a function
    the connection does not have fails, and so does the write that fired it. Idempotent."""
    create: Callable | None = getattr(dbapi_connection, "create_function", None)
    if create is None:
        return
    caps = available_mask()
    try:
        create(FN_NORM, 2, _normalize_sql, deterministic=True)
        create(FN_USED, 3, used_mask, deterministic=True)
        create(FN_CAPS, 0, lambda: caps)
    except TypeError:  # an old driver without the deterministic flag
        create(FN_NORM, 2, _normalize_sql)
        create(FN_USED, 3, used_mask)
        create(FN_CAPS, 0, lambda: caps)


def _on_connect(dbapi_connection, _connection_record) -> None:
    register(dbapi_connection)


def install_pool_hook() -> None:
    """Give EVERY SQLAlchemy pool's new connections the functions (idempotent).

    A class-level pool listener rather than one per engine: the app builds engines in
    several places (the main store, the read snapshots, staging copies, tests), and one
    that was missed would fail on its first article write. The raw connection factory
    (``src.database.connect.connect``) registers them itself."""
    from sqlalchemy import event
    from sqlalchemy.pool import Pool

    if not event.contains(Pool, "connect", _on_connect):
        event.listen(Pool, "connect", _on_connect)


install_pool_hook()
