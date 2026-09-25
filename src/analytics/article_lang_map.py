"""Article id -> the language ``index_article`` resolves for it, read without content.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. ``KeywordMention.language`` (Q414 = a) stores the article's language on
every mention, but only on mentions written since that column was added: the migration
deliberately did NO backfill, so an older mention reads NULL until a re-index reaches its
article. Two passes need that older mention's language anyway -- the keyword-language
reconcile (a vote per mention) and the lemma fold job (which lemmatiser extraction would
have used) -- and both must answer exactly what ``index_article`` would have written, or
the keyword they touch would disagree with the next article indexed under it.

THE RULE IS ``index_article``'s, MINUS ONE STEP. ``_resolve_known_language`` takes the
asserted ``Article.language``, else the deduced ``detected_language``; the mention stores
``normalize_lang`` of that; extraction lemmatises under ``normalize_lang(known or "en")``.
The step left out is the offline text detection it runs when an article has neither: that
reads the article body, which is the SQLCipher codec trap (a ~35 KB decrypt per row to
reach one small column). An article with no language at all therefore stays unknown here,
which is the honest answer, not a guess.

READ FROM A COVERING INDEX, NEVER FROM THE ROWS. ``idx_article_created_lang`` carries
``(created_at, language, detected_language)`` plus the rowid, so the whole map is one
index-only scan -- ``tests/test_keyword_fold.py`` pins the plan. It is the same trap the
reconcile's original article-language map was written to avoid.

COMPACT ON PURPOSE. A million articles as a ``dict[int, str]`` is on the order of 100 MB,
on a reference machine with 3.5 GB. One byte per article id (a code into a short table of
the distinct languages) is about 1 MB for the same corpus. Zero means "no language".
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.analytics.managed import normalize_lang

#: The one statement, kept as a constant so the plan test reads the exact text that runs.
MAP_SQL = (
    "SELECT id, language, detected_language FROM articles "
    "WHERE (language IS NOT NULL AND language != '') "
    "OR (detected_language IS NOT NULL AND detected_language != '')"
)

#: Extraction's working assumption for an article whose language is unknown
#: (``index_article`` passes ``known_lang or "en"``). Never stored, never a vote.
EXTRACTION_DEFAULT = "en"


class ArticleLanguageMap:
    """The resolved language of every article that has one, one byte per article id."""

    def __init__(self, session: Session) -> None:
        self._codes: list[str] = []  # slot value k (1..255) -> self._codes[k - 1]
        self._code_of: dict[str, int] = {}
        self._slots = bytearray()
        self._overflow: dict[int, str] = {}  # only if a corpus has > 255 distinct codes
        self.articles = 0
        result = session.execute(text(MAP_SQL))
        try:
            for aid, lang, detected in result:
                known = (lang or "").strip() or (detected or "").strip()
                if not known:  # excluded by the WHERE; a whitespace-only value lands here
                    continue
                self._put(int(aid), normalize_lang(known))
        finally:
            result.close()

    def _put(self, aid: int, code: str) -> None:
        self.articles += 1
        slot = self._code_of.get(code)
        if slot is None:
            if len(self._codes) >= 255:
                self._overflow[aid] = code
                return
            self._codes.append(code)
            slot = len(self._codes)
            self._code_of[code] = slot
        if aid >= len(self._slots):
            self._slots.extend(bytes(max(aid + 1 - len(self._slots), len(self._slots))))
        self._slots[aid] = slot

    def known(self, aid: int) -> str | None:
        """The article's normalised language, ``""`` if its stored value normalises to
        nothing, ``None`` if it has no language at all."""
        if 0 <= aid < len(self._slots):
            slot = self._slots[aid]
            if slot:
                return self._codes[slot - 1]
        return self._overflow.get(aid)

    def mention_language(self, aid: int) -> str | None:
        """What ``index_article`` writes on this article's mentions: a code, or NULL."""
        return self.known(aid) or None

    def extraction_language(self, aid: int) -> str:
        """The language extraction lemmatised this article's terms under."""
        known = self.known(aid)
        return EXTRACTION_DEFAULT if known is None else known
