"""Extract explicit dates *mentioned in article text* (for the temporal map).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A story's *publication* date is not the date it is *about*: a 2024 piece may report
on a 1945 event or a 2026 election. This module finds the explicit calendar dates a
text mentions so the temporal map can place coverage at the moment it discusses.

**High precision by design** (the project's ethos — better to miss a date than invent
one). We match only unambiguous forms:

  * ISO ``YYYY-MM-DD``
  * ``11 September 2001`` / ``11 Sept 2001`` (day)
  * ``September 11, 2001`` (day)
  * ``September 2001`` / ``Sept 2001`` (month)

We deliberately do **not** extract bare years (``in 1945`` — too easily a quantity,
a page number, a model year) or relative expressions (``last Tuesday`` — needs a
reference and guesses), and every result is a *candidate* carrying the matched snippet
as provenance, never a confirmed fact. Pure: no I/O, fully unit-tested.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
# Multilingual month names (field log 2026-06-11: the corpus is half French —
# "le 11 juin 2026" was invisible to an English-only table). Unambiguous tokens:
# every name maps to exactly one month, so all tables stay active at once.
_MONTHS.update({
    # French
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "décembre": 12, "decembre": 12,
    # German
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4,
    "juni": 6, "juli": 7, "oktober": 10, "dezember": 12,
    # Spanish
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
    # Italian
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "settembre": 9, "ottobre": 10, "dicembre": 12,
    # Portuguese
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "maio": 5, "junho": 6,
    "julho": 7, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
})
# Additional UI/corpus languages (date-diagnostics 2026-06-17: these had NO month
# vocabulary, so date coverage cratered despite real article volume — sr 6.8 %,
# hu 3.7 %, tr 8.9 %, ro 15.6 %, da 25.8 %, sk/pl/fi/bg ~0 %). SAFE to add: a month
# name only ever yields a date when a day number or a year sits ADJACENT (every
# regex below requires it), so vocabulary raises recall without inventing dates
# from running prose. Inflected forms idiomatic in dates are included (Slavic
# GENITIVE "5 maja", Finnish PARTITIVE "5. toukokuuta"). Every token maps to ONE
# month. Tokens that are common words in a HIGHER-volume language are deliberately
# omitted to preserve precision (e.g. Polish/Slovak genitive "marca" = March, but
# also Spanish/Italian "marca" = brand → omitted; "5 marca" still resolves via the
# nominative marzec/marec or numeric forms).
_MONTHS.update({
    # Romanian
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "iunie": 6,
    "iulie": 7, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
    # Hungarian ("2024. május 5.")
    "január": 1, "február": 2, "március": 3, "április": 4, "május": 5,
    "június": 6, "július": 7, "augusztus": 8, "szeptember": 9, "október": 10,
    # Turkish ("5 Mayıs 2024")
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
    # Nordic (Danish / Swedish / Norwegian Bokmål)
    "marts": 3, "maj": 5, "desember": 12, "januari": 1, "februari": 2,
    "augusti": 8,
    # Finnish — nominative + partitive ("5. toukokuuta 2024")
    "tammikuu": 1, "helmikuu": 2, "maaliskuu": 3, "huhtikuu": 4, "toukokuu": 5,
    "kesäkuu": 6, "heinäkuu": 7, "elokuu": 8, "syyskuu": 9, "lokakuu": 10,
    "marraskuu": 11, "joulukuu": 12,
    "tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4,
    "toukokuuta": 5, "kesäkuuta": 6, "heinäkuuta": 7, "elokuuta": 8,
    "syyskuuta": 9, "lokakuuta": 10, "marraskuuta": 11, "joulukuuta": 12,
    # Polish — nominative + genitive ("5 maja 2024"); "marca" omitted (see above)
    "styczeń": 1, "luty": 2, "marzec": 3, "kwiecień": 4, "czerwiec": 6,
    "lipiec": 7, "sierpień": 8, "wrzesień": 9, "październik": 10, "listopad": 11,
    "grudzień": 12,
    "stycznia": 1, "lutego": 2, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11,
    "grudnia": 12,
    # Slovak — nominative + genitive ("5. mája 2024"); "marca" omitted (see above)
    "marec": 3, "apríl": 4, "máj": 5, "jún": 6, "júl": 7,
    "januára": 1, "februára": 2, "apríla": 4, "mája": 5, "júna": 6, "júla": 7,
    "augusta": 8, "septembra": 9, "októbra": 10, "novembra": 11, "decembra": 12,
    # Serbian (Latin)
    "avgust": 8, "septembar": 9, "oktobar": 10, "novembar": 11, "decembar": 12,
    # Serbian (Cyrillic)
    "јануар": 1, "фебруар": 2, "март": 3, "април": 4, "мај": 5, "јун": 6,
    "јул": 7, "август": 8, "септембар": 9, "октобар": 10, "новембар": 11,
    "децембар": 12,
    # Bulgarian (Cyrillic)
    "януари": 1, "февруари": 2, "май": 5, "юни": 6, "юли": 7,
    "септември": 9, "октомври": 10, "ноември": 11, "декември": 12,
})
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))  # longest first so 'sept' beats 'sep'

# Numeric dates (dd/mm/yyyy · dd.mm.yyyy · dd-mm-yyyy · yyyy/mm/dd). When both
# fields are ≤12 the order is ambiguous: the ARTICLE LANGUAGE decides (en→MDY,
# everything else→DMY); with no hint, an ambiguous numeric date is SKIPPED —
# never guessed (provenance honesty).
_NUM_DMY_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_NUM_YMD_RE = re.compile(r"\b(\d{4})[./](\d{1,2})[./](\d{1,2})\b")

# Anchored expressions (resolved against the article's PUBLICATION date; each
# carries graded provenance — FUTURE_DEVELOPMENTS design, now implemented):
_DM_NOYEAR_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+(?:de\s+)?({_MONTH_ALT})\.?\b(?!\.?\s+(?:de\s+)?\d{{4}})", re.I)
_MD_NOYEAR_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{{4}})", re.I)
_REL_WORDS = {
    "yesterday": -1, "today": 0, "tomorrow": 1,
    "hier": -1, "aujourd'hui": 0, "aujourd’hui": 0, "demain": 1,
    "gestern": -1, "heute": 0, "morgen": 1,
    "ayer": -1, "hoy": 0, "mañana": 1,
    "ontem": -1, "hoje": 0, "amanhã": 1,
    "ieri": -1, "oggi": 0, "domani": 1,
}
_REL_RE = re.compile(r"\b(" + "|".join(sorted(_REL_WORDS, key=len, reverse=True)) + r")\b", re.I)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4,
    "samedi": 5, "dimanche": 6,
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,
    "samstag": 5, "sonntag": 6,
}
_WD_RE = re.compile(
    r"\b(next\s+|last\s+)?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b", re.I
)

_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_RE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+(?:de\s+)?({_MONTH_ALT})\.?\s+(?:de\s+)?(\d{{4}})\b", re.I)
_MDY_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
# Year-first with a NAMED month ("2024. május 5." Hungarian / "2024 m. gegužės"
# patterns): unambiguous (full year + month name + day all present), so it is a
# day match like ISO. Covers locales that write Y M D in prose with words.
_YMD_NAME_RE = re.compile(rf"\b(\d{{4}})\.?\s+({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)
_MY_RE = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{4}})\b", re.I)

# Plausible window for a *mentioned* date: deep history up to a little ahead of "now".
_MIN_YEAR, _MAX_AHEAD = 1000, 5


def _valid(year: int, month: int, day: int, today: date) -> date | None:
    if not (_MIN_YEAR <= year <= today.year + _MAX_AHEAD):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_of(token: str) -> int | None:
    """Month number for a matched month name, tolerant of case-fold quirks. A
    regex hit case-insensitively matches the table, but ``str.lower()`` does not
    always round-trip to the stored key (Turkish DOTLESS ı: ``"MAYIS".lower()``
    is ``"mayis"`` ≠ the table's ``"mayıs"``). Returns None on a miss so the hit
    is skipped, never a ``KeyError`` that would abort extraction for the article."""
    return _MONTHS.get(token.lower())


def _snippet(text: str, start: int, end: int, pad: int = 24) -> str:
    s = text[max(0, start - pad) : min(len(text), end + pad)].strip()
    return re.sub(r"\s+", " ", s)


def extract_dates(
    text: str,
    *,
    today: date | None = None,
    limit: int = 8,
    anchor: date | None = None,
    language: str | None = None,
) -> list[dict]:
    """Calendar dates mentioned in ``text``, as candidates with provenance.

    Returns up to ``limit`` de-duplicated ``{date, precision, text}`` dicts, ordered by
    first appearance. ``precision`` is ``"day"`` or ``"month"``. Overlapping matches are
    resolved most-specific-first (a day match suppresses the month match inside it).

    ``anchor`` (the article's publication date) unlocks ANCHORED resolution —
    day+month without a year, yesterday/today/tomorrow words, bare weekdays —
    each marked with how it was resolved. ``language`` decides the order of
    ambiguous numeric dates (en→MDY, others→DMY; no hint + ambiguous → skipped,
    never guessed). Optimized 2026-06-11 (maintainer: far too few dates).
    """
    if not text:
        return []
    today = today or date.today()
    consumed: list[tuple[int, int]] = []  # spans claimed by more specific matches
    found: dict[tuple[str, str], dict] = {}

    def claim(start: int, end: int) -> bool:
        for cs, ce in consumed:
            if start < ce and cs < end:  # overlaps an already-claimed span
                return False
        consumed.append((start, end))
        return True

    def add(d: date, precision: str, m: re.Match) -> None:
        key = (d.isoformat(), precision)
        if key not in found:
            found[key] = {
                "date": d.isoformat(),
                "precision": precision,
                "text": _snippet(text, m.start(), m.end()),
                "pos": m.start(),
            }

    for m in _ISO_RE.finditer(text):
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _DMY_RE.finditer(text):
        mon = _month_of(m.group(2))
        d = _valid(int(m.group(3)), mon, int(m.group(1)), today) if mon else None
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _MDY_RE.finditer(text):
        mon = _month_of(m.group(1))
        d = _valid(int(m.group(3)), mon, int(m.group(2)), today) if mon else None
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _YMD_NAME_RE.finditer(text):  # "2024. május 5." (year-first, named month)
        mon = _month_of(m.group(2))
        d = _valid(int(m.group(1)), mon, int(m.group(3)), today) if mon else None
        if d and claim(*m.span()):
            add(d, "day", m)
    # Numeric dates — language picks the order when ambiguous; never guessed.
    mdy_first = (language or "").lower().startswith("en")
    for m in _NUM_YMD_RE.finditer(text):
        d = _valid(int(m.group(1)), int(m.group(2)), int(m.group(3)), today)
        if d and claim(*m.span()):
            add(d, "day", m)
    for m in _NUM_DMY_RE.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            d = _valid(y, b, a, today)
        elif b > 12 and a <= 12:
            d = _valid(y, a, b, today)
        elif a <= 12 and b <= 12 and language:
            d = _valid(y, a, b, today) if mdy_first else _valid(y, b, a, today)
        else:
            continue  # ambiguous with no language hint: skipped, not guessed
        if d and claim(*m.span()):
            add(d, "day", m)

    for m in _MY_RE.finditer(text):  # month precision — only where no day match claimed it
        mon = _month_of(m.group(1))
        d = _valid(int(m.group(2)), mon, 1, today) if mon else None
        if d and claim(*m.span()):
            add(d, "month", m)

    # ---- anchored resolution (needs the article's publication date) -------- #
    if anchor is not None:
        def nearest_year(month: int, day: int) -> date | None:
            best = None
            for y in (anchor.year - 1, anchor.year, anchor.year + 1):
                try:
                    cand = date(y, month, day)
                except ValueError:
                    continue
                if best is None or abs((cand - anchor).days) < abs((best - anchor).days):
                    best = cand
            return best if best and abs((best - anchor).days) <= 183 else None

        for rx, gi_d, gi_m in ((_DM_NOYEAR_RE, 1, 2), (_MD_NOYEAR_RE, 2, 1)):
            for m in rx.finditer(text):
                mon = _MONTHS.get(m.group(gi_m).lower())
                if not mon:
                    continue
                d = nearest_year(mon, int(m.group(gi_d)))
                if d and claim(*m.span()):
                    add(d, "day", m)
        for m in _REL_RE.finditer(text):
            if claim(*m.span()):
                add(anchor + timedelta(days=_REL_WORDS[m.group(1).lower()]), "day", m)
        for m in _WD_RE.finditer(text):
            wd = _WEEKDAYS[m.group(2).lower()]
            mod = (m.group(1) or "").strip().lower()
            delta = (wd - anchor.weekday()) % 7
            if mod == "next":
                d = anchor + timedelta(days=delta or 7)
            elif mod == "last":
                d = anchor - timedelta(days=((anchor.weekday() - wd) % 7) or 7)
            else:  # bare weekday in news prose: the most recent such day
                d = anchor - timedelta(days=(anchor.weekday() - wd) % 7)
            if claim(*m.span()):
                add(d, "day", m)

    out = sorted(found.values(), key=lambda c: c["pos"])
    for c in out:
        c.pop("pos", None)
    return out[:limit]
