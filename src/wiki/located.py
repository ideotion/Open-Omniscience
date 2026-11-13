"""R17 step 4 for the Wikipedia lane (v0.6 row D, S06-03 S2 + S3; Q819, Q820; R678): infobox addresses, located only locally.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IS READ. The wikitext this machine already STORED -- a followed (HOT) page's newest revision and a WARM page's latest text -- never the
reader's stripped text (``src/api/wiki.py`` peels the infoboxes away) and never a new request. In it, the first infobox whose TYPE is on the
edition's closed list of organisation, institution, public-building and public-place infoboxes (R691: never a generic building,
monument, castle or heritage-register type, which describe private houses as often as public places), and in that infobox only the fields whose KEY names an address.

WHAT IS NEVER READ (R678), DECIDED FOR THE WHOLE PAGE AND FAILING CLOSED. A page is skipped, and counted with its reason, when any
template or category on it marks a person (an infobox about a person, de ``Personendaten``, "Living people", births and deaths), when any
of its infoboxes is not on the list, or, as an extra check on top (R691), when its title, categories or infobox name a home in any of
the twelve languages (a house, a farm, an estate, 邸, हवेली). A family counts as people. A firm, an agency, a restaurant or a hotel
is read only beside the page's own ``{{coord}}``, since one may be run from someone's home; and an address is never shortened to its
street alone, since "5 Mill Lane" answers from whichever village has one.

WHAT OSM ITSELF SAYS DECIDES (R691, structural and in no language). A located answer is placed only when every object the index answered
with carries the house number the address names, and the placed one is something OSM names as a place people walk into: a shop, or an
allowlisted value (a place of worship, a school, a library, a hospital, a museum, a hotel, a stadium, a station, a government office ...);
never a bare office, religion, Wikidata link, garden or childcare tag, and never a dwelling (building=house, residential, detached,
apartments, farm ...), residential use, or private or residents-only access. Anything
else is counted as ambiguous, never placed. A type or a marker nobody wrote down
costs a located address, never a person's privacy: the map can never become a way to find where someone lives.
Addresses in article BODIES (wiki and press) are not read either: without an infobox key, a body-text grammar would place strings that only
look like addresses. That is a recorded gap, stated in the counters' ``gaps`` rather than shown as zero.

HOW AN ADDRESS IS LOCATED. Only through the local OpenStreetMap address index of the countries the user ingested
(:func:`src.osm.places.geocode`, S05-04): never an external geocoder, nothing leaves the machine (Q820). An address is located when the index
answers with one to five OSM objects carrying every word of it, all within :data:`SAME_PLACE_METRES` of each other (one address on a building
and its entrance), and within :data:`COORD_AGREEMENT_METRES` of the page's own ``{{coord}}`` when it has one. More answers, answers spread
further apart, or an answer far from the page's coordinate are AMBIGUOUS: counted, never placed. Trailing comma parts (country, region)
may be dropped one at a time; the leading street part never is. A value with no digit has no house number and is counted, never looked up.
"Outside your OpenStreetMap countries" is claimed only when the page's own ``{{coord}}`` lies outside the bounding box of every ingested
country; anything else not found is "not located", because the index cannot tell a missing address from a differently worded one.

THE READ IS INCREMENTAL AND BOUNDED. A call reads and looks up for at most :data:`SCAN_BUDGET_SECONDS` and keeps what it learned in memory,
keyed by each text's version: a page that changes is read again, a page that goes is forgotten, and a replaced lane file starts over. The
counters say how many stored texts were read and how many addresses are still pending. A call that finds the scan busy answers with the
last snapshot instead of waiting (a poll never waits on a read). Nothing is written to disk.
"""

from __future__ import annotations

import html
import json
import logging
import math
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from src.monitoring.secret_scrub import log_failure
from src.wiki.pagefacts import _balanced_template, _split_top_level

_LOG = logging.getLogger("wiki.located")

#: Two OSM answers for one address count as one place when they are this close (a building and its entrance node, two shops at one number).
SAME_PLACE_METRES: float = 150.0
#: More answers than this is an ambiguous address, however close they are.
MAX_ANSWERS: int = 5
#: How long one call may spend reading stored texts before it answers with what it has.
SCAN_BUDGET_SECONDS: float = 1.5
#: Texts decompressed per database round trip.
SCAN_BATCH: int = 200
#: The longest cleaned address the locator is given. An infobox value longer than this is not an address line.
MAX_ADDRESS_CHARS: int = 200

SCOPE = "Addresses outside your OpenStreetMap countries are not located."

#: The statuses one address can end in, in the order the counters list them.
STATUSES: tuple[str, ...] = (
    "located",
    "ambiguous",
    "not_located",
    "outside_your_osm_countries",
    "no_house_number",
    "no_osm_country",
    "osm_unreadable",
    "lookup_failed",
    "pending",
)
#: Why a page was not read, counted per edition. Every one fails closed: a page is read only when nothing on it says otherwise.
SKIPS: tuple[str, ...] = ("about_a_person", "a_home", "type_not_on_the_list")
#: A located answer further than this from the page's own ``{{coord}}`` is not trusted: it is counted as ambiguous, never placed.
COORD_AGREEMENT_METRES: float = 5_000.0

GAPS: tuple[str, ...] = (
    "Addresses in article bodies (Wikipedia and press) are not read: only an infobox field named as an address is.",
    "Infoboxes of a type not on the edition's list are not read; the list is closed and fails closed.",
    "An address written in a script the OpenStreetMap index splits differently (Chinese, Japanese) is rarely located.",
)


_NAMESPACES = (
    "template:", "modèle:", "vorlage:", "plantilla:", "predefinição:", "шаблон:", "模板:", "テンプレート:", "قالب:", "templat:",
    "साँचा:", "টেমপ্লেট:",
)


def _norm(name: str) -> str:
    """A template or field name as compared here: case-folded, underscores as spaces, one space between words, no namespace prefix."""
    out = " ".join((name or "").replace("_", " ").casefold().split())
    for ns in _NAMESPACES:
        if out.startswith(ns):
            return out[len(ns):].strip()
    return out


def _names(*items: str) -> frozenset[str]:
    return frozenset(_norm(i) for i in items)


# The infobox types read, per edition (R678, R691): ORGANISATIONS, INSTITUTIONS, PUBLIC BUILDINGS and PUBLIC PLACES only, a CLOSED list
# that fails closed. Generic building, monument, castle, landmark and heritage-register types (en "infobox building", "infobox nrhp",
# fr "infobox monument", de "infobox bauwerk", ja "infobox 建築物" ...) are deliberately ABSENT: they describe private houses, farms and
# estates as often as public places, and a word list cannot tell them apart in twelve languages (R691). So is anything about a person or a
# family. The template names are the editions' own as written from knowledge, fixture-tested; a name missing here costs a located address,
# never a person's privacy.
_EN_TYPES = (
    "infobox museum", "infobox company", "infobox organization", "infobox organisation", "infobox government agency", "infobox hospital",
    "infobox school", "infobox university", "infobox library", "infobox hotel", "infobox restaurant", "infobox shopping mall",
    "infobox venue", "infobox stadium", "infobox theatre", "infobox church", "infobox religious building", "infobox mosque",
    "infobox temple", "infobox hindu temple", "infobox synagogue", "infobox station", "infobox airport", "infobox park",
    "infobox zoo",
)
PLACE_TYPES: dict[str, frozenset[str]] = {
    "en": _names(*_EN_TYPES),
    "fr": _names(
        "infobox musée", "infobox entreprise", "infobox organisation", "infobox université", "infobox école",
        "infobox établissement scolaire", "infobox hôpital", "infobox hôtel", "infobox gare", "infobox stade", "infobox salle de spectacle",
        "infobox édifice religieux", "infobox bibliothèque", "infobox administration", "infobox parc",
    ),
    "de": _names(
        "infobox unternehmen", "infobox hochschule", "infobox museum", "infobox bahnhof", "infobox stadion", "infobox krankenhaus",
        "infobox schule", "infobox bibliothek", "infobox behörde", "infobox kirchengebäude", "infobox hotel", "infobox theater",
        "infobox organisation",
    ),
    "es": _names(
        "ficha de museo", "ficha de empresa", "ficha de organización", "ficha de universidad", "ficha de hospital", "ficha de estación",
        "ficha de estadio", "ficha de edificio religioso", "ficha de recinto", "ficha de institución educativa", "ficha de biblioteca",
        "ficha de hotel",
    ),
    "pt": _names(
        "info/empresa", "info/museu", "info/organização", "info/universidade", "info/hospital", "info/estação", "info/estádio",
        "info/igreja", "info/escola", "info/biblioteca", "info/hotel",
    ),
    "ru": _names(
        "компания", "музей", "организация", "университет", "больница", "станция метро", "железнодорожная станция", "стадион", "храм",
        "школа", "библиотека", "гостиница", "театр",
    ),
    "zh": _names(*_EN_TYPES, "infobox 公司", "infobox 博物馆", "infobox 大学"),
    "ja": _names(*_EN_TYPES, "基礎情報 会社", "infobox 博物館", "日本の大学", "駅情報", "infobox 病院", "infobox 学校"),
    "ar": _names(
        "صندوق معلومات شركة", "صندوق معلومات متحف", "صندوق معلومات جامعة", "صندوق معلومات منظمة", "صندوق معلومات مستشفى",
        "صندوق معلومات محطة", "صندوق معلومات ملعب", "صندوق معلومات مسجد", "صندوق معلومات مدرسة", "صندوق معلومات مكتبة",
        "صندوق معلومات فندق", "صندوق معلومات كنيسة",
    ),
    "id": _names(*_EN_TYPES, "infobox perusahaan", "infobox universitas", "infobox masjid", "infobox stasiun"),
    "hi": _names(*_EN_TYPES, "ज्ञानसन्दूक कंपनी", "ज्ञानसन्दूक संग्रहालय", "ज्ञानसन्दूक विश्वविद्यालय"),
    "bn": _names(*_EN_TYPES, "তথ্যছক কোম্পানি", "তথ্যছক জাদুঘর", "তথ্যছক বিশ্ববিদ্যালয়", "তথ্যছক সংস্থা"),
}

# Infobox types about a PERSON. Only for the count of "skipped: about a person": the closed list above already keeps them out, and an
# unlisted person type is skipped as "type not on the list" all the same.
_PERSON_WORDS = (
    "person", "biography", "officeholder", "politician", "musical artist", "musician", "actor", "writer", "scientist", "sportsperson",
    "athlete", "footballer", "cricketer", "player", "royalty", "military person", "criminal", "artist", "philosopher", "journalist",
    "personnalité", "biographie", "politicien", "acteur", "écrivain", "sportif", "footballeur", "artiste",
    "persönlichkeit", "biografía", "ficha de persona", "ficha de político", "ficha de deportista", "ficha de artista",
    "info/biografia", "info/político", "info/ator", "персона", "государственный деятель", "учёный", "писатель", "футболист",
    "музыкант", "人物", "政治家", "شخص", "سيرة", "tokoh", "biografi", "व्यक्ति", "ব্যক্তি",
    # A family or a dynasty is people too (R691).
    "family", "dynasty", "famille", "dynastie", "familie", "geschlecht", "familia", "dinastía", "família", "dinastia", "семья", "род",
    "家族", "一族", "王朝", "عائلة", "أسرة", "keluarga", "dinasti", "परिवार", "राजवंश", "পরিবার", "রাজবংশ",
)
#: Person templates some editions name without an infobox prefix, or that mark a biography with no infobox at all (de Personendaten).
_PERSON_UNPREFIXED = _names(
    "персона", "государственный деятель", "учёный", "писатель", "футболист", "музыкант", "人物", "政治家", "基礎情報 人物",
    "personendaten", "persondata", "actoractress", "actor actress", "基礎情報 音楽家", "基礎情報 政治家", "スポーツ選手",
)
#: Category name fragments that mark a page about a person, per the editions' own conventions (living people, births, deaths).
_PERSON_CATEGORY = re.compile(
    r"living people|\b\d{3,4} births|\b\d{3,4} deaths|naissance en|décès en|^geboren |^gestorben |^mann$|^frau$|nacidos en|fallecidos en|"
    r"nascidos em|mortos em|pessoas vivas|родившиеся|умершие|персоналии|在世人物|出生|逝世|存命人物|年生|年没|أشخاص على قيد الحياة|مواليد|وفيات|"
    r"tokoh yang masih hidup|kelahiran|kematian|जीवित लोग|जन्म|निधन|জীবিত ব্যক্তি|জন্ম|মৃত্যু|"
    r"famil(?:y|ies)|familles?|familien?|familias?|famílias?|семь[яи]|家族|一族|عائلات?|أسرة|keluarga|परिवार|পরিবার|"
    r"^people |people from|year of birth|year of death|personnalité|^personnes |^personen |^personas |^pessoas |^люди |уроженцы|"
    r"人物$|出身の人物|أشخاص من|^tokoh |लोग$|ব্যক্তিত্ব|"
    r"(?:hoteliers|innkeepers|chefs|restaurateurs|businesspeople|businessmen|businesswomen|sculptors|painters|artists|writers|"
    r"architects|farmers|bakers)$",
    re.I,
)
_CATEGORY_LINK = re.compile(
    r"\[\[\s*(?:category|catégorie|kategorie|categoría|categoria|категория|分类|分類|カテゴリ|تصنيف|kategori|श्रेणी|বিষয়শ্রেণী)\s*:\s*([^\]|]+)",
    re.I,
)
#: Unprefixed building templates an edition uses (ru): recognised as infoboxes so they count as off the list, never as "no infobox".
_KNOWN_UNLISTED = _names("здание", "усадьба", "жилой дом", "памятник архитектуры", "особняк")
#: Templates that mark a biography with no infobox, and the sort-key magic words whose "Surname, Given" value says the same.
_PERSON_MARKERS = _names("lifetime", "bd", "bio", "bda", "birth date and age", "death date and age")
_SORT_KEYS = ("defaultsort:", "sortierung:", "ordenar:", "clé de tri:", "сортировка:", "デフォルトソート:", "ترتيب افتراضي:")
#: A template name that is itself a template: unreadable, so the page fails closed.
_UNREADABLE_TEMPLATE = re.compile(r"\{\{\s*[^\n|{}]*\{\{(?!\s*!\s*\}\})")
#: Disambiguators that say a title names a person ("John Smith (chef)").
_PERSON_DISAMBIGUATOR = re.compile(
    r"\((?:[^()]*\b)?(?:chef|restaurateur|business(?:man|woman|person)|entrepreneur|architect|artist|singer|actor|actress|writer|author|"
    r"politician|painter|musician|footballer|cricketer|journalist|hotelier|innkeeper|baker|farmer|born \d+|\d{3,4}[-–]\d{0,4}|"
    r"cuisinier|fermier|boulanger|homme d'affaires|koch|bäcker|landwirt|bauer|hotelier|cocinero|agricultor|cozinheiro|"
    r"unternehmer|empresario|empresária|empresário|предприниматель|повар|料理人|实业家|企業家|رجل أعمال|उद्यमी|ব্যবসায়ী)\)\s*$",
    re.I,
)
#: Organisation-kind types: a firm or a hotel may be run from someone's home, so these are read only when the page carries its own
#: ``{{coord}}`` (a public, mapped place) and the located answer agrees with it.
_ORG_WORDS = (
    "company", "organization", "organisation", "agency", "restaurant", "hotel", "entreprise", "administration", "hôtel", "unternehmen",
    "behörde", "empresa", "organización", "organização", "компания", "организация", "гостиница", "公司", "会社", "شركة", "منظمة", "فندق",
    "perusahaan", "कंपनी", "কোম্পানি", "সংস্থা",
)


def _needs_coord(kind: str) -> bool:
    return any(word in kind for word in _ORG_WORDS)


#: Infoboxes that may share a page with a place infobox without saying anything about who lives there.
_HARMLESS = _names("infobox mapframe", "infobox map")
#: An EXTRA check on top of the closed list (R691: never the safeguard itself). A page whose title, categories, infobox name, type or use
#: field names a home is skipped. Words in scripts that separate words with spaces are matched as whole words by letter lookarounds,
#: never ``\b`` (which splits Devanagari and Bengali at their vowel signs); words in scripts that do not (Chinese, Japanese) and short
#: Arabic, Devanagari and Bengali stems are matched anywhere, failing towards a skip.
_HOME_FIELDS = _names(
    "name", "building type", "nrhp type", "type", "current use", "current_use", "use", "usage", "nutzung", "uso", "tipo", "тип", "用途",
    "種類", "类型", "النوع", "प्रकार", "ধরন",
    # What the place is NOW and who holds it: a chapel converted into a house says so here (security read 2, R691).
    "status", "functional status", "functional_status", "condition", "owner", "ownership", "public access", "statut", "propriétaire",
    "eigentümer", "zustand", "estado", "propietario", "proprietário", "статус", "владелец", "状態", "所有者", "现状", "الحالة", "المالك",
    "स्थिति", "स्वामी", "অবস্থা", "মালিক", "pemilik",
)
_HOME_SPACED = (
    "house", "houses", "residence", "residences", "residential", "home", "homes", "homestead", "dwelling", "villa", "cottage", "farm",
    "farms", "farmhouse", "ranch", "estate", "manor", "mansion", "bungalow", "townhouse", "rowhouse", "apartment", "apartments", "flat",
    "plantation", "chalet", "maison", "habitation", "ferme", "manoir", "domaine", "demeure", "hôtel particulier", "wohnhaus",
    "wohngebäude", "bauernhof", "landhaus", "herrenhaus", "gutshaus", "gutshof", "residencia", "vivienda", "casa", "hacienda", "finca",
    "cortijo", "quinta", "residência", "moradia", "fazenda", "chácara", "sítio", "жилой", "дом", "особняк", "усадьба", "дача", "ферма",
    "rumah", "kediaman", "vila", "perkebunan", "peternakan",
    # Houses that go with an office: a clergy, envoy, warden or guest house is someone's home (security read, R691).
    "rectory", "vicarage", "parsonage", "manse", "presbytery", "deanery", "official residence", "guesthouse", "guest house", "lodge",
    "résidence", "presbytère", "cure", "gîte", "residenz", "pfarrhaus", "forsthaus", "gästehaus", "pension", "rectoría", "casona",
    "presbitério", "residências", "резиденция", "причта", "домик", "pastoran", "wisma",
    "flats", "family", "families", "living quarters", "basement", "household",
)
#: Prefixes in spaced scripts: "homeschool", "householder", "privately", "Privatbesitz".
_HOME_PREFIXES = ("home", "house")
#: Words that, in a TYPE or USE field only, say the place is not public.
_PRIVATE_SPACED = ("privé", "privée", "privado", "privada", "частный", "частная", "частное", "pribadi", "not open to the public")
_PRIVATE_PREFIXES = ("privat",)
_PRIVATE_ANYWHERE = ("私人", "私有", "私邸", "個人", "خاص", "निजी", "ব্যক্তিগত")
_HOME_ANYWHERE = (
    "住宅", "邸", "宅", "公馆", "公館", "故居", "旧居", "舊居", "別荘", "别墅", "別墅", "農場", "农场", "牧場", "牧场", "山荘", "荘園", "庄园",
    "莊園", "民家", "家屋", "مسكن", "منزل", "سكني", "بيت", "فيلا", "مزرعة", "आवास", "निवास", "हवेली", "कोठी", "बंगला", "फार्म", "घर",
    "বাসভবন", "বাসা", "বাড়ি", "খামার", "বাংলো",
    "屋敷", "住居", "寓所", "官舎", "宿舎", "مقر إقامة", "إقامة", "मकान", "ঘর",
)
_LETTER = r"[^\W\d_]"


def _words(spaced: tuple[str, ...], anywhere: tuple[str, ...], prefixes: tuple[str, ...] = ()) -> re.Pattern[str]:
    return re.compile(
        "|".join(
            [rf"(?<!{_LETTER}){re.escape(w)}(?!{_LETTER})" for w in spaced]
            + [rf"(?<!{_LETTER}){re.escape(w)}" for w in prefixes]
            + [re.escape(w) for w in anywhere]
        ),
        re.I,
    )


_HOME_WORDS = _words(_HOME_SPACED, _HOME_ANYWHERE, _HOME_PREFIXES)
_PRIVATE_WORDS = _words(_PRIVATE_SPACED, _PRIVATE_ANYWHERE, _PRIVATE_PREFIXES)
#: Arabic tatweel and short-vowel marks, removed before matching so a stretched or vowelled word still matches.
_ARABIC_MARKS = re.compile("[\u0640\u064b-\u0652\u0670]")


def _plain(text: str) -> str:
    return " ".join(_ARABIC_MARKS.sub("", html.unescape(str(text))).replace("_", " ").split())


def names_a_home(text: str | None) -> bool:
    """True when ``text`` names a dwelling in any of the twelve editions' languages. An extra check, never the safeguard (R691)."""
    return bool(text) and _HOME_WORDS.search(_plain(str(text))) is not None


# The infobox keys that name an address, per edition. ``address`` is read in every edition: many localised templates keep the English
# parameter name.
ADDRESS_KEYS: dict[str, frozenset[str]] = {
    "en": _names("address", "street address", "street_address"),
    "fr": _names("address", "adresse"),
    "de": _names("address", "adresse", "anschrift"),
    "es": _names("address", "dirección", "direccion"),
    "pt": _names("address", "endereço", "endereco", "morada"),
    "ru": _names("address", "адрес"),
    "zh": _names("address", "地址"),
    "ja": _names("address", "所在地", "住所"),
    "ar": _names("address", "العنوان", "عنوان"),
    "id": _names("address", "alamat"),
    "hi": _names("address", "पता"),
    "bn": _names("address", "ঠিকানা"),
}

_TEMPLATE_OPEN = re.compile(r"\{\{\s*([^\n|{}]+?)\s*(?=\||\}\}|\n)")
_COORD_OPEN = re.compile(r"\{\{\s*[Cc]oord\s*\|")
_WRAPPERS = _names("nowrap", "nobr", "small", "smaller", "lang", "transl", "plainlist", "unbulleted list", "ubl", "hlist", "flatlist", "nbsp")
_INNER_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
_REF = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_EXTLINK = re.compile(r"\[(?:https?:)?//\S+\s*([^\]]*)\]")


_INFOBOX_PREFIXES = ("infobox", "ficha de", "info/", "карточка", "基礎情報", "صندوق معلومات", "ज्ञानसन्दूक", "তথ্যছক")
_ALL_PLACE_TYPES: frozenset[str] = frozenset().union(*PLACE_TYPES.values())


def _is_person_type(name: str) -> bool:
    return name in _PERSON_UNPREFIXED or any(word in name for word in _PERSON_WORDS)


def _looks_like_infobox(name: str) -> bool:
    """An infobox of any kind: a known prefix, a listed type, a person template, or ``infobox`` anywhere (``#invoke:Infobox``)."""
    return (
        name.startswith(_INFOBOX_PREFIXES)
        or "infobox" in name
        or name in _ALL_PLACE_TYPES
        or name in _PERSON_UNPREFIXED
        or name in _KNOWN_UNLISTED
    )


def _fields(text: str, start: int) -> dict[str, str] | None:
    body = _balanced_template(text, start)
    if body is None:
        return None
    fields: dict[str, str] = {}
    for part in _split_top_level(body):
        key, sep, value = part.partition("=")
        k = _norm(key)
        if sep and k and k not in fields:
            fields[k] = value.strip()
    return fields


def classify_page(edition: str, wikitext: str) -> tuple[str | None, str | None, dict[str, str] | None]:
    """``(skip reason, place type, fields)``. FAILS CLOSED AT PAGE LEVEL (R678): a page is read only when EVERY infobox on it is on the
    edition's place list (or harmless), no template or category on it marks a person, and the place infobox does not name a home.

    ``(None, None, None)`` is a page with no infobox at all.
    """
    text = wikitext or ""
    cats = [_plain(c) for c in _CATEGORY_LINK.findall(text)]
    if any(_PERSON_CATEGORY.search(c) for c in cats):
        return "about_a_person", None, None
    home_category = any(names_a_home(c) for c in cats)
    if _UNREADABLE_TEMPLATE.search(text):
        # A template whose name is itself built by a template ({{Infobox {{#if:...}}}}) cannot be told apart: fail closed.
        return "type_not_on_the_list", None, None
    allowed = PLACE_TYPES.get(edition, frozenset())
    first: tuple[str, int] | None = None
    unlisted = False
    seen = False
    for match in _TEMPLATE_OPEN.finditer(text):
        name = _norm(match.group(1))
        if name in _PERSON_MARKERS or (name.startswith(_SORT_KEYS) and "," in name):
            return "about_a_person", None, None  # {{Lifetime}}, {{BD}}, a "Surname, Given" sort key: a biography without an infobox
        if _is_person_type(name) and (_looks_like_infobox(name) or name in _PERSON_UNPREFIXED):
            return "about_a_person", None, None
        if not _looks_like_infobox(name) or name in _HARMLESS:
            continue
        seen = True
        if name not in allowed:
            unlisted = True
        elif first is None:
            first = (name, match.start())
    if not seen:
        return None, None, None
    if unlisted or first is None:
        return "type_not_on_the_list", None, None
    fields = _fields(text, first[1])
    if fields is None:
        return "type_not_on_the_list", None, None
    # The extra check (R691), on the raw value as well as the cleaned one: a link target ([[Detached house|Single-family]]) or a value too
    # long to clean still counts.
    named = [(key, fields[key]) for key in _HOME_FIELDS if key in fields]
    if home_category or names_a_home(first[0]) or any(names_a_home(raw) or names_a_home(clean_value(raw)) for _, raw in named):
        return "a_home", None, None
    if any(key != "name" and _PRIVATE_WORDS.search(_plain(raw)) for key, raw in named):
        return "a_home", None, None  # type = Private garden
    return None, first[0], fields


def clean_value(raw: str) -> str | None:
    """An infobox value as plain text: references, comments and tags gone, links as their text, wrapper templates opened, others dropped."""
    text = _COMMENT.sub(" ", raw or "")
    text = _REF.sub(" ", text)
    text = _BR.sub(", ", text)
    for _ in range(8):  # innermost templates first; a value nests a few deep at most
        replaced = _INNER_TEMPLATE.sub(_open_template, text)
        if replaced == text:
            break
        text = replaced
    text = text.replace("{{", " ").replace("}}", " ")
    text = _LINK.sub(r"\1", text)
    text = _EXTLINK.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    text = html.unescape(text).replace("'''", "").replace("''", "")
    text = re.sub(r"\s*\n\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;·")
    text = re.sub(r"\s*(,\s*)+", ", ", text)
    if not text or len(text) > MAX_ADDRESS_CHARS:
        return None
    return text


def _open_template(match: re.Match) -> str:
    parts = [p.strip() for p in match.group(1).split("|")]
    name = _norm(parts[0])
    if name in _WRAPPERS or name.startswith("lang-"):
        args = [p for p in parts[1:] if "=" not in p]
        if name == "lang" and len(args) > 1:
            args = args[1:]  # {{lang|fr|texte}}: the first argument is the language code
        return ", ".join(a for a in args if a)
    return " "


def has_house_number(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


_HOUSE_NUMBER_PART = re.compile(r"^(?:д\.?|дом|n[º°o.]?|no\.?|nr\.?|número|numéro)?\s*\d{1,4}\s*[a-zа-я]?(?:\s*[/-]\s*\d{1,4}[a-zа-я]?)?\.?$", re.I)


def _core(parts: list[str]) -> int:
    """How many leading parts name the house: 1 for "5 Mill Lane", 2 for "ул. Ленина, 5" or "Rua Fixture, 10"; 0 when no part carries
    the number where a house number goes ("Mill Lane, ME1 2AB" names a street and a postcode, not a house)."""
    if len(parts) > 1 and _HOUSE_NUMBER_PART.match(parts[0]):
        return 2  # "5, rue Fixture"
    if parts and has_house_number(parts[0]):
        return 1
    if len(parts) > 1 and _HOUSE_NUMBER_PART.match(parts[1]):
        return 2
    return 0


#: A house number: one to four digits and at most one letter right after them, which must END the token ("5a", "12 b"), so "५ मार्ग"
#: never reads as "५म" (a vowel sign is not a letter to a lookahead).
_NUMBER_TOKEN = re.compile(r"(?<![^\W_])(\d{1,4}(?:\s?[^\W\d_](?=[\s,;/]|$))?)(?![^\W_])")


def house_number(text: str) -> str | None:
    """The house number the address names, normalised ("12", "5a"), or ``None``. Read from the part that carries it (:func:`_core`)."""
    parts = [p.strip() for p in (text or "").split(",") if p.strip()]
    core = _core(parts)
    if core == 0:
        return None
    if core == 2:
        source = parts[0] if _HOUSE_NUMBER_PART.match(parts[0]) else parts[1]
    else:
        source = parts[0]
    match = _NUMBER_TOKEN.search(source)
    return _number(match.group(1)) if match else None


def _number(value: Any) -> str:
    """Compared as ASCII digits: "५", "৫", "٥" and "５" are 5, as in OSM's own tags."""
    text = re.sub(r"\s+", "", str(value)).lower()
    return "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in text)


#: OSM tags that say an object is somebody's home, whatever the page says (R691, structural and language-free).
_DWELLING_BUILDINGS = frozenset({
    "house", "residential", "detached", "semidetached_house", "semi_detached", "semi", "terrace", "row_house", "apartments", "bungalow",
    "cabin", "dormitory", "farm", "farmhouse", "farm_auxiliary", "houseboat", "static_caravan", "hut", "villa", "manor", "stilt_house",
    "trullo", "ger", "allotment_house", "presbytery", "parsonage", "rectory",
})
_REFUSED_ACCESS = frozenset({"private", "no", "residents", "permit", "delivery"})
#: What makes an object PUBLIC, as an allowlist of OSM values that name a place people walk into (security read 3, R691). A key alone is
#: not enough: ``office`` is often a firm in someone's house, ``religion`` a clergy house, ``wikidata`` a lived-in listed house,
#: ``leisure=garden`` a private garden and ``amenity=childcare`` a home daycare.
_PUBLIC_VALUES: dict[str, frozenset[str]] = {
    "amenity": frozenset({
        "place_of_worship", "school", "college", "university", "library", "hospital", "clinic", "townhall", "courthouse", "police",
        "fire_station", "post_office", "theatre", "cinema", "arts_centre", "community_centre", "conference_centre", "events_venue",
        "exhibition_centre", "concert_hall", "restaurant", "cafe", "bar", "pub", "fast_food", "bank", "marketplace", "public_building",
        "music_school", "language_school", "prison", "planetarium", "casino", "nightclub",
    }),
    "tourism": frozenset({"museum", "gallery", "hotel", "hostel", "motel", "zoo", "aquarium", "theme_park"}),
    "leisure": frozenset({"stadium", "sports_centre", "sports_hall", "ice_rink", "water_park", "fitness_centre", "park"}),
    "healthcare": frozenset({"hospital", "clinic"}),
    "public_transport": frozenset({"station"}),
    "aeroway": frozenset({"aerodrome", "terminal"}),
    "office": frozenset({"government"}),
}


def _tag(facts: dict[str, Any], key: str) -> str:
    return str(facts.get(key) or "").strip().lower()


def _public_place(answer: dict[str, Any], number: str | None) -> bool:
    """FAILS CLOSED: an answer without facts, with another house number, tagged as a dwelling or private, or with nothing that OSM names
    as a public place (a shop, or a value on :data:`_PUBLIC_VALUES`) is never placed (R691: what OSM itself says the object is)."""
    facts = answer.get("facts")
    if not isinstance(facts, dict) or number is None:
        return False
    osm_numbers = {_number(n) for n in re.split(r"[;,]", str(facts.get("addr:housenumber") or "")) if n.strip()}
    if number not in osm_numbers:
        return False
    if any(b.strip() in _DWELLING_BUILDINGS for b in _tag(facts, "building").split(";")) or "residential" in _tag(facts, "building:use"):
        return False
    if any(a.strip() in _REFUSED_ACCESS for a in _tag(facts, "access").split(";")):
        return False
    return bool(_tag(facts, "shop")) or any(_tag(facts, key) in values for key, values in _PUBLIC_VALUES.items())


def variants(text: str) -> list[str]:
    """The address as written, then with trailing comma parts dropped one at a time, never into the part that carries the number."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    core = _core(parts)
    if not core or not any(ch.isalpha() for ch in "".join(parts[:core])):
        return []
    return [", ".join(parts[:n]) for n in range(len(parts), core - 1, -1)]


def page_coordinate(wikitext: str) -> tuple[float, float] | None:
    """The page's first ``{{coord}}``, decimal or degrees/minutes/seconds with a hemisphere letter. ``None`` when absent or unreadable."""
    match = _COORD_OPEN.search(wikitext or "")
    if match is None:
        return None
    body = _balanced_template(wikitext, match.start())
    if body is None:
        return None
    args = [p.strip() for p in body.split("|")[1:] if "=" not in p]
    try:
        hemi = [i for i, a in enumerate(args) if a.upper() in ("N", "S", "E", "W")]
        if len(hemi) >= 2:
            lat = _dms(args[: hemi[0]], args[hemi[0]])
            lon = _dms(args[hemi[0] + 1 : hemi[1]], args[hemi[1]])
        else:
            lat, lon = float(args[0]), float(args[1])
    except (ValueError, IndexError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _dms(parts: list[str], hemi: str) -> float:
    if not 1 <= len(parts) <= 3:
        raise ValueError("not degrees, minutes, seconds")
    value = sum(float(p) / (60**i) for i, p in enumerate(parts))
    return -value if hemi.upper() in ("S", "W") else value


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres (haversine, mean Earth radius)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(h)))


def resolve(text: str, geocoder: Any = None, *, guarded: bool = False) -> dict[str, Any]:
    """One cleaned address through the local index. Returns ``{"status", ...}``; a ``located`` answer carries the point and its objects."""
    if geocoder is None:
        from src.osm.places import geocode as geocoder
    tries = variants(text)
    if not tries:
        return {"status": "no_house_number"}
    parts = [p for p in text.split(",") if p.strip()]
    whole, core = len(parts), _core([p.strip() for p in parts])
    # A shortened address always keeps its locality: "5 Mill Lane" alone answers from whichever village has one, and that is somebody's
    # house, not this place (security read, R691). An address with no locality after its house is tried only when the page has its own coordinate
    # (``guarded``) for the answer to agree with.
    tries = [q for q in tries if len(q.split(",")) > core] if whole > core else (tries if guarded else [])
    for query in tries:
        answer = geocoder(query, limit=MAX_ANSWERS + 1, facts=True)
        status = answer.get("status")
        if status == "no-country":
            return {"status": "no_osm_country"}
        results = answer.get("results") or []
        total = int(answer.get("total") or 0)
        if not results:
            continue
        if total > MAX_ANSWERS or len(results) < total:
            # More answers than the index handed back (a stale index, a row in another country): placing one would be a pick.
            return {"status": "ambiguous", "answers": total}
        points = [(float(r["lat"]), float(r["lon"])) for r in results]
        spread = max((metres(p, q) for p in points for q in points), default=0.0)
        if spread > SAME_PLACE_METRES:
            return {"status": "ambiguous", "answers": total}
        number = house_number(query)
        if not all(_public_place(r, number) for r in results):
            # Another house number, a dwelling, a private object or nothing public: never placed, counted as not confirmed.
            return {"status": "ambiguous", "answers": total}
        first = results[0]
        countries = {c.get("alpha3"): c.get("vintage") for c in answer.get("countries") or []}
        return {
            "status": "located",
            "query": query,
            "lat": points[0][0],
            "lon": points[0][1],
            "osm_object": first.get("object"),
            "osm_country": first.get("country"),
            "osm_vintage": countries.get(first.get("country")),
            "answers": total,
        }
    return {"status": "not_located"}


def outside_every_country(point: tuple[float, float] | None, bboxes: list[tuple[float, float, float, float]]) -> bool:
    """True only when ``point`` is known and outside every ingested country's bounding box ``(min_lat, min_lon, max_lat, max_lon)``."""
    if point is None or not bboxes:
        return False
    lat, lon = point
    return not any(b[0] <= lat <= b[2] and b[1] <= lon <= b[3] for b in bboxes)


def page_addresses(edition: str, wikitext: str, title: str | None = None) -> dict[str, Any]:
    """Pure: what one stored page offers. ``{"skip": reason}``, ``{"none": True}`` or ``{"type", "candidates": [(field, text)], "coord"}``."""
    skip, kind, fields = classify_page(edition, wikitext)
    if skip is not None:
        return {"skip": skip}
    if kind is not None and title and _PERSON_DISAMBIGUATOR.search(_plain(title)):
        return {"skip": "about_a_person"}  # "John Smith (chef)": a biography with a restaurant's infobox
    if kind is not None and names_a_home(title):
        return {"skip": "a_home"}  # "John Smith House": the title names a home when no field does
    if kind is None or fields is None:
        return {"none": True}
    keys = ADDRESS_KEYS.get(edition, ADDRESS_KEYS["en"])
    candidates = []
    for key, value in fields.items():
        if key in keys:
            cleaned = clean_value(value)
            if cleaned:
                candidates.append((key, cleaned))
    if not candidates:
        return {"none": True}
    coord = page_coordinate(wikitext)
    if coord is None and _needs_coord(kind):
        return {"skip": "type_not_on_the_list"}  # a firm, an agency or a hotel without its own coordinate may be someone's home
    return {"type": kind, "candidates": candidates, "coord": coord}


# --------------------------------------------------------------------------- #
# The incremental scan over the stored texts, and its snapshot.
# --------------------------------------------------------------------------- #
@dataclass
class _Page:
    edition: str
    tier: str
    version: str
    title: str | None
    external_id: str | None
    offer: dict[str, Any] | None  # None: nothing to count (no infobox, or a place infobox without an address field)


@dataclass
class _State:
    pages: dict[str, _Page] = field(default_factory=dict)
    resolved: dict[tuple[str, str, bool], dict[str, Any]] = field(default_factory=dict)
    osm_signature: str | None = None
    lane_marker: Any = None


_lock = threading.Lock()
_state = _State()
_last: dict[str, Any] | None = None


def reset() -> None:
    """Forget every page read (tests; and done on its own when the lane file is replaced)."""
    global _state, _last
    with _lock:
        _state = _State()
        _last = None


def _lane_marker() -> Any:
    """The wiki lane file's identity: a restore, an erase or an encryption swap replaces the file, and what was read of the old one goes."""
    import os

    from src.versioned.store import lane_path

    try:
        st = os.stat(lane_path("wiki"))
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def _osm_scope() -> tuple[str | None, list[tuple[float, float, float, float]]]:
    """The ingested, indexed countries as a signature and their bounding boxes. ``(None, [])`` when the OSM state could not be read."""
    from src.osm.places import index_state

    try:
        scope = [c for c in index_state() if c.get("indexed")]
    except Exception as exc:  # noqa: BLE001 - an unreadable OSM lane is said as such, never as "no country"
        log_failure(_LOG, "located addresses: the OSM index state could not be read", exc, level=logging.WARNING)
        return None, []
    signature = json.dumps(sorted((c["alpha3"], c.get("vintage")) for c in scope))
    if not scope:
        return signature, []
    from src.osm.lane_models import OsmCountry
    from src.versioned import store

    boxes: list[tuple[float, float, float, float]] = []
    try:
        with store.lane_session("osm") as s:
            for row in s.query(OsmCountry).filter(OsmCountry.alpha3.in_([c["alpha3"] for c in scope])):
                bbox = (json.loads(row.border_json or "{}") or {}).get("bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    boxes.append(tuple(float(v) for v in bbox))  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - without boxes nothing is claimed outside; addresses still resolve
        log_failure(_LOG, "located addresses: the OSM country borders could not be read", exc, level=logging.WARNING)
        boxes = []
    return signature, boxes


def _held(lane: Any) -> dict[str, tuple[str, str, str]]:
    """Every stored text of the twelve editions, as ``ref -> (tier, edition, version)``. Small rows, no text: read every call."""
    from sqlalchemy import func, select

    from src.versioned.models import VersionedEntity, VersionedRevision
    from src.wiki.lane_models import WikiWarmPage

    editions = list(PLACE_TYPES)
    out: dict[str, tuple[str, str, str]] = {}
    # SQLite's bare-column rule: content_hash is the one of the row max() picked, so a recreated lane whose row ids restart cannot pass
    # for the old one.
    # The title is part of the version: a page renamed to "X House" with no new text is read again (security read, R691).
    for eid, language, title, rid, chash in lane.execute(
        select(
            VersionedEntity.id, VersionedEntity.language, VersionedEntity.title, func.max(VersionedRevision.id), VersionedRevision.content_hash
        )
        .join(VersionedRevision, VersionedRevision.entity_id == VersionedEntity.id)
        .where(VersionedRevision.content.is_not(None), VersionedEntity.language.in_(editions))
        .group_by(VersionedEntity.id, VersionedEntity.language, VersionedEntity.title)
    ):
        out[f"hot:{eid}"] = ("hot", str(language), f"{rid}:{chash}:{title}")
    # ONLY columns stored before the texts: a column after ``latest_text`` makes SQLite walk (and SQLCipher decrypt) every row's text
    # overflow pages, which on a large lane spends the whole budget before one text is read. WARM replaces ``latest_text`` only with a
    # newer revid, so the revid alone versions it. A deleted page keeps its last text (Q713) and is read like any other.
    for wid, edition, title, revid in lane.execute(
        select(WikiWarmPage.id, WikiWarmPage.edition, WikiWarmPage.title, WikiWarmPage.latest_revid).where(
            WikiWarmPage.latest_text.is_not(None), WikiWarmPage.edition.in_(editions)
        )
    ):
        out[f"warm:{wid}"] = ("warm", str(edition), f"{revid}:{title}")
    return out


def _read(lane: Any, state: _State, todo: list[str], held: dict[str, tuple[str, str, str]], deadline: float) -> None:
    """Read the texts of ``todo`` in batches until the deadline."""
    from sqlalchemy import select

    from src.versioned.models import VersionedEntity, VersionedRevision
    from src.wiki.lane_models import WikiWarmPage

    for i in range(0, len(todo), SCAN_BATCH):
        if time.monotonic() >= deadline:
            return
        batch = todo[i : i + SCAN_BATCH]
        hot = {int(r.split(":")[1]): r for r in batch if r.startswith("hot:")}
        warm = {int(r.split(":")[1]): r for r in batch if r.startswith("warm:")}
        if hot:
            rids = {int(held[ref][2].split(":")[0]): eid for eid, ref in hot.items()}
            texts = dict(lane.execute(select(VersionedRevision.id, VersionedRevision.content).where(VersionedRevision.id.in_(list(rids)))).all())
            names = {e: (t, x) for e, t, x in lane.execute(
                select(VersionedEntity.id, VersionedEntity.title, VersionedEntity.external_id).where(VersionedEntity.id.in_(list(hot)))
            )}
            for rid, eid in rids.items():
                tier, edition, version = held[hot[eid]]
                title, external_id = names.get(eid, (None, None))
                state.pages[hot[eid]] = _Page(edition, tier, version, title, external_id, _offer(edition, texts.get(rid) or "", title))
        if warm:
            for wid, edition, title, page_id, text in lane.execute(
                select(WikiWarmPage.id, WikiWarmPage.edition, WikiWarmPage.title, WikiWarmPage.page_id, WikiWarmPage.latest_text)
                .where(WikiWarmPage.id.in_(list(warm)))
            ):
                tier, _, version = held[warm[wid]]
                state.pages[warm[wid]] = _Page(edition, tier, version, title, f"{edition}:#{page_id}", _offer(edition, text or "", title))


def _offer(edition: str, text: str, title: str | None) -> dict[str, Any] | None:
    offer = page_addresses(edition, text, title)
    return None if offer.get("none") else offer


def located_report(lane: Any, *, budget: float = SCAN_BUDGET_SECONDS, geocoder: Any = None) -> dict[str, Any]:
    """Bring what was read up to date with the lane, read new or changed texts and resolve their addresses for at most ``budget``
    seconds, and report: points with provenance, counters per edition. Never raises: a failure is ``measured: false`` with the reason.
    """
    global _state, _last
    if not _lock.acquire(blocking=False):
        # Another call is reading: the last answer, marked as such, rather than a wait (a poll never waits on a read).
        # Counts only: a point read before a page changed (into a home, a person) is never served again from a snapshot.
        if _last:
            return {**_last, "points": [], "complete": False, "from_previous_read": True}
        return {"measured": False, "reason": "busy", "scope": SCOPE}
    try:
        deadline = time.monotonic() + budget
        marker = _lane_marker()
        if marker != _state.lane_marker:
            _state = _State(lane_marker=marker)
            _last = None
        signature, boxes = _osm_scope()
        if _state.osm_signature != signature:
            _state.resolved.clear()
            _state.osm_signature = signature
        try:
            held = _held(lane)
            deadline = max(deadline, time.monotonic() + budget / 2)  # the listing never eats the whole budget for the reads
            # A text that changed or went (a new revision, a WARM text replaced in place, a deleted or evicted page) is read again or
            # forgotten: what was read of an old version never stays on the map.
            for ref in [r for r, page in _state.pages.items() if r not in held or held[r][2] != page.version]:
                del _state.pages[ref]
            todo = [r for r in held if r not in _state.pages]
            _read(lane, _state, todo, held, deadline)
        except Exception as exc:  # noqa: BLE001 - the report says it could not read, never blanks the surface it rides
            log_failure(_LOG, "located addresses: the stored texts could not be read", exc, level=logging.WARNING)
            return {"measured": False, "reason": "unreadable", "scope": SCOPE}
        try:
            _last = _report(_state, held, boxes, geocoder, deadline)
        except Exception as exc:  # noqa: BLE001
            log_failure(_LOG, "located addresses: the report could not be built", exc, level=logging.WARNING)
            return {"measured": False, "reason": "unreadable", "scope": SCOPE}
        return _last
    finally:
        _lock.release()


def _answer(state: _State, edition: str, text: str, geocoder: Any, deadline: float, *, guarded: bool = False) -> dict[str, Any]:
    if state.osm_signature is None:
        return {"status": "osm_unreadable"}
    if state.osm_signature == "[]":
        return {"status": "no_osm_country"}
    memo = (edition, text, guarded)
    if memo in state.resolved:
        return state.resolved[memo]
    if time.monotonic() >= deadline:
        return {"status": "pending"}
    try:
        answer = resolve(text, geocoder, guarded=guarded)
    except Exception as exc:  # noqa: BLE001 - one failed lookup is counted, never memoized, never a silent drop
        log_failure(_LOG, "located addresses: one lookup in the OSM index failed", exc, level=logging.WARNING)
        return {"status": "lookup_failed"}
    state.resolved[memo] = answer
    return answer


def _report(state: _State, held: dict[str, tuple[str, str, str]], boxes: list, geocoder: Any, deadline: float) -> dict[str, Any]:
    per: dict[str, dict[str, int]] = {}
    points: list[dict[str, Any]] = []
    for page in state.pages.values():
        offer = page.offer
        if offer is None:
            continue
        row = per.setdefault(page.edition, {})
        if "skip" in offer:
            row["skipped_" + offer["skip"]] = row.get("skipped_" + offer["skip"], 0) + 1
            continue
        coord = offer.get("coord")
        for key, text in offer["candidates"]:
            row["found"] = row.get("found", 0) + 1
            answer = _answer(state, page.edition, text, geocoder, deadline, guarded=coord is not None)
            status = answer["status"]
            if status == "not_located" and outside_every_country(coord, boxes):
                status = "outside_your_osm_countries"
            if status == "located" and coord is not None and metres(coord, (answer["lat"], answer["lon"])) > COORD_AGREEMENT_METRES:
                # The index found the street somewhere the page itself says the place is not: a namesake, never this place.
                status = "ambiguous"
            row[status] = row.get(status, 0) + 1
            if status == "located":
                points.append(
                    {
                        "edition": page.edition,
                        "title": page.title,
                        "external_id": page.external_id,
                        "tier": page.tier,
                        "revision": page.version,
                        "infobox": offer["type"],
                        "field": key,
                        "address": text,
                        **{k: answer[k] for k in ("query", "lat", "lon", "osm_object", "osm_country", "osm_vintage", "answers")},
                    }
                )
    read = {"hot": sum(1 for r in state.pages if r.startswith("hot:")), "warm": sum(1 for r in state.pages if r.startswith("warm:"))}
    total = {"hot": sum(1 for r in held if r.startswith("hot:")), "warm": sum(1 for r in held if r.startswith("warm:"))}
    return {
        "measured": True,
        "scope": SCOPE,
        "points": points,
        "per_edition": {e: dict(sorted(c.items())) for e, c in sorted(per.items()) if c},
        "texts_read": read,
        "texts_held": total,
        "complete": read == total and not any(c.get("pending") for c in per.values()),
        "statuses": list(STATUSES),
        "skips": list(SKIPS),
        "gaps": list(GAPS),
        "method": (
            "A stored page is read only when every infobox on it is on the edition's closed list of organisation, institution, public "
            "building and public place infoboxes, nothing on it marks a person or a family and nothing on it names a home; in it, the fields named as an address. Each is "
            "looked up in the local OpenStreetMap address index of the countries you ingested: located when one to "
            f"{MAX_ANSWERS} objects carry every word and lie within {int(SAME_PLACE_METRES)} m of each other, and within "
            f"{int(COORD_AGREEMENT_METRES / 1000)} km of the page's own coordinate when it has one; and only when OpenStreetMap tags the object "
            "as a public place at that house number, never as a dwelling. Nothing is looked up anywhere else."
        ),
    }
