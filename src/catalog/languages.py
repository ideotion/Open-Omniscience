"""ISO 639 language codes — the storage<->display conversion layer for languages.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE COUNTRY MODULE'S SHAPE, ONE STANDARD OVER. ``src/catalog/countries.py`` stores
lowercase alpha-2 and displays uppercase alpha-3; ruling Q306 = b asks for the same
move on languages — the code a PERSON sees reads ISO 639-2/3 (``fra``), while storage
stays ISO 639-1 (``fr``) until the 0.5 storage half. Nothing here widens a column,
rewrites a config or touches what `Article.language` holds.

WHY B AND T MATTER, AND WHICH ONE THIS IS. ISO 639-2 has two sets where a language's
English and native names disagree: the BIBLIOGRAPHIC codes (``fre``, ``ger``, ``chi``)
and the TERMINOLOGICAL ones (``fra``, ``deu``, ``zho``). They differ for 20 languages
and agree for every other. This table is **639-2/T**, which is also ISO 639-3 for every
code in it — so "ISO 639-2/3", the phrase the ruling uses, has one unambiguous reading
here. THE EVIDENCE, not an assumption: the ruling's own worked example is ``fra``,
which is the T code (``fre`` is B). Brief ``S04-05`` §6 records that WHICH table
supplies the codes where they differ is not this slice's to decide, so this is recorded
as the session's ASSUMPTION; flipping it is one dict, and the twenty codes it would
change are the ones listed in ``_B_DIFFERS`` below, so the blast radius is measured
rather than guessed.

WHAT IS NOT CONVERTED, and each has a reason:

* **BCP-47 / ``Intl`` / ``<html lang>`` boundaries.** The browser, `Intl.DisplayNames`,
  the `lang=` attribute and every locale file speak two-letter codes. Those are the
  language analogue of the three external contracts countries keep in alpha-2, and they
  stay 639-1 behind this converter.
* **A Wikipedia EDITION code is not a language.** ``enwiki``/``simple``/``zh-yue`` name
  a wiki, and several editions have no ISO 639-1 code at all. Converting them would
  assert a language where a project is meant.
* **The native-name language switcher** (UI invariant #15) shows NAMES. Untouched.
* **The edition pickers** ``wiki-lang`` / ``dump-lang`` (invariant #1) are language
  pickers over editions, native name first. Untouched.
"""

from __future__ import annotations

from src.analytics.managed import normalize_lang

# ISO 639-1 -> ISO 639-2/T (== ISO 639-3 for every pair here). Whitespace-separated
# at import, the same shape ``countries.py`` uses for its alpha-3 table, so the two
# read alike and a reviewer can diff either by eye.
_ISO1_TO_3_TEXT = """
    aa:aar ab:abk ae:ave af:afr ak:aka am:amh an:arg ar:ara as:asm av:ava ay:aym az:aze
    ba:bak be:bel bg:bul bi:bis bm:bam bn:ben bo:bod br:bre bs:bos
    ca:cat ce:che ch:cha co:cos cr:cre cs:ces cu:chu cv:chv cy:cym
    da:dan de:deu dv:div dz:dzo
    ee:ewe el:ell en:eng eo:epo es:spa et:est eu:eus
    fa:fas ff:ful fi:fin fj:fij fo:fao fr:fra fy:fry
    ga:gle gd:gla gl:glg gn:grn gu:guj gv:glv
    ha:hau he:heb hi:hin ho:hmo hr:hrv ht:hat hu:hun hy:hye hz:her
    ia:ina id:ind ie:ile ig:ibo ii:iii ik:ipk io:ido is:isl it:ita iu:iku
    ja:jpn jv:jav
    ka:kat kg:kon ki:kik kj:kua kk:kaz kl:kal km:khm kn:kan ko:kor kr:kau ks:kas
    ku:kur kv:kom kw:cor ky:kir
    la:lat lb:ltz lg:lug li:lim ln:lin lo:lao lt:lit lu:lub lv:lav
    mg:mlg mh:mah mi:mri mk:mkd ml:mal mn:mon mr:mar ms:msa mt:mlt my:mya
    na:nau nb:nob nd:nde ne:nep ng:ndo nl:nld nn:nno no:nor nr:nbl nv:nav ny:nya
    oc:oci oj:oji om:orm or:ori os:oss
    pa:pan pi:pli pl:pol ps:pus pt:por
    qu:que
    rm:roh rn:run ro:ron ru:rus rw:kin
    sa:san sc:srd sd:snd se:sme sg:sag si:sin sk:slk sl:slv sm:smo sn:sna so:som
    sq:sqi sr:srp ss:ssw st:sot su:sun sv:swe sw:swa
    ta:tam te:tel tg:tgk th:tha ti:tir tk:tuk tl:tgl tn:tsn to:ton tr:tur ts:tso
    tt:tat tw:twi ty:tah
    ug:uig uk:ukr ur:urd uz:uzb
    ve:ven vi:vie vo:vol
    wa:wln wo:wol
    xh:xho
    yi:yid yo:yor
    za:zha zh:zho zu:zul
    """
ISO1_TO_ISO3: dict[str, str] = dict(p.split(":") for p in _ISO1_TO_3_TEXT.split())
ISO3_TO_ISO1: dict[str, str] = {v: k for k, v in ISO1_TO_ISO3.items()}

#: The twenty languages whose BIBLIOGRAPHIC 639-2 code differs from the
#: TERMINOLOGICAL one this table uses. Recorded as DATA rather than prose so the
#: §6 seam has a measured blast radius: if the maintainer rules B, these are the
#: twenty entries that change and the other 164 do not. Three of them are UI
#: locales (fr, de, zh), which is why the choice is visible rather than academic.
B_DIFFERS_FROM_T: dict[str, str] = {
    "bo": "tib", "cs": "cze", "cy": "wel", "de": "ger", "el": "gre",
    "eu": "baq", "fa": "per", "fr": "fre", "hy": "arm", "is": "ice",
    "ka": "geo", "mi": "mao", "mk": "mac", "ms": "may", "my": "bur",
    "nl": "dut", "ro": "rum", "sk": "slo", "sq": "alb", "zh": "chi",
}


def language_display_code(value: str | None) -> str | None:
    """The language code a PERSON sees: lowercase ISO 639-2/T (``fr`` -> ``fra``).

    Accepts a 639-1 code with or without a region/script subtag (``en-US`` -> ``eng``),
    through the house normaliser so this layer and the corpus agree on what a language
    key is. A 639-2/3 code passes through. ``None`` only for an empty value.

    An UNRECOGNISED value comes back stripped but otherwise unchanged, exactly as
    ``countries.country_display_code`` does: a corpus language is stored raw from
    ``<html lang>``, so junk is real and must stay VISIBLE rather than be blanked into
    "this article has no language", which is a different claim.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    base = normalize_lang(raw)
    if not base:
        return raw
    if base in ISO1_TO_ISO3:
        return ISO1_TO_ISO3[base]
    if base in ISO3_TO_ISO1:
        return base
    return raw


def language_storage_code(value: str | None) -> str | None:
    """The inverse: back to the ISO 639-1 the store and every ``Intl`` boundary use.

    Fails closed on a three-letter code with no 639-1 equivalent (``pcm``, ``yue``,
    ``tet`` all appear in the shipped catalogues) -- there is no two-letter answer and
    inventing one would assert a language the standard does not name. Callers that need
    a BCP-47 tag check for ``None`` and fall back to showing the code.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    base = normalize_lang(raw)
    if not base:
        return None
    if base in ISO1_TO_ISO3:
        return base
    return ISO3_TO_ISO1.get(base)
