"""
ISO 3166-1 alpha-2 country codes + the single storage<->display conversion layer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Storage convention (maintainer-ruled, 0.09): country values are stored as
lowercase ISO 3166-1 alpha-2 codes (the codebase-wide convention: the ISO set,
ccTLD inference, keyword mentions, the gazetteer and the coverage layer are all
lowercase) and displayed as full English names through
this one module -- `normalize_country` for the way in, `country_display_name`
for the way out. Codes come from the iso-codes reference dataset; display names
prefer common over formal forms ("Russia", not "Russian Federation"). This is
reference data, not an editorial statement about any place; comparisons stay
case-insensitive everywhere. The continent grouping (UN-style six continents)
exists purely to measure the catalog's regional balance.

The in-text location extractor (`src.timemap.locextract`) keeps its own curated
multilingual table: free-text matching has different ambiguity trade-offs than
normalising a catalog field, and short aliases that are safe here ("uk", "usa")
would be traps there.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

# ISO 3166-1 alpha-2 (officially assigned codes), lowercased. Kept as a
# whitespace-separated string (split at import) so it stays compact and neutral.
_CODES = """
    ad ae af ag ai al am ao aq ar as at au aw ax az
    ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz
    ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz
    de dj dk dm do dz
    ec ee eg eh er es et
    fi fj fk fm fo fr
    ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy
    hk hm hn hr ht hu
    id ie il im in io iq ir is it
    je jm jo jp
    ke kg kh ki km kn kp kr kw ky kz
    la lb lc li lk lr ls lt lu lv ly
    ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz
    na nc ne nf ng ni nl no np nr nu nz
    om
    pa pe pf pg ph pk pl pm pn pr ps pt pw py
    qa
    re ro rs ru rw
    sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz
    tc td tf tg th tj tk tl tm tn to tr tt tv tw tz
    ua ug um us uy uz
    va vc ve vg vi vn vu
    wf ws
    ye yt
    za zm zw
    """

ISO_3166_1_ALPHA2: frozenset[str] = frozenset(_CODES.split())

# Codes the shipped catalogs legitimately use that are NOT officially-assigned
# ISO countries: EU is exceptionally reserved (EU institutions: EUR-Lex, EPO);
# XK is the de-facto user-assigned code for Kosovo; INT is this project's
# convention for international bodies (WIPO, UN); AN (Netherlands Antilles) is
# transitionally reserved -- it appears in a live-verified holiday feed.
# Recognised and displayed by name, but counted apart from countries in
# coverage so the denominator stays honest.
SPECIAL_CODES: dict[str, str] = {
    "eu": "European Union",
    "int": "International",
    "xk": "Kosovo",
    "an": "Netherlands Antilles",
}

COUNTRY_NAMES: dict[str, str] = {
    "ad": "Andorra",
    "ae": "United Arab Emirates",
    "af": "Afghanistan",
    "ag": "Antigua and Barbuda",
    "ai": "Anguilla",
    "al": "Albania",
    "am": "Armenia",
    "ao": "Angola",
    "aq": "Antarctica",
    "ar": "Argentina",
    "as": "American Samoa",
    "at": "Austria",
    "au": "Australia",
    "aw": "Aruba",
    "ax": "Åland Islands",
    "az": "Azerbaijan",
    "ba": "Bosnia and Herzegovina",
    "bb": "Barbados",
    "bd": "Bangladesh",
    "be": "Belgium",
    "bf": "Burkina Faso",
    "bg": "Bulgaria",
    "bh": "Bahrain",
    "bi": "Burundi",
    "bj": "Benin",
    "bl": "Saint Barthélemy",
    "bm": "Bermuda",
    "bn": "Brunei",
    "bo": "Bolivia",
    "bq": "Bonaire, Sint Eustatius and Saba",
    "br": "Brazil",
    "bs": "Bahamas",
    "bt": "Bhutan",
    "bv": "Bouvet Island",
    "bw": "Botswana",
    "by": "Belarus",
    "bz": "Belize",
    "ca": "Canada",
    "cc": "Cocos (Keeling) Islands",
    "cd": "DR Congo",
    "cf": "Central African Republic",
    "cg": "Congo (Republic)",
    "ch": "Switzerland",
    "ci": "Côte d'Ivoire",
    "ck": "Cook Islands",
    "cl": "Chile",
    "cm": "Cameroon",
    "cn": "China",
    "co": "Colombia",
    "cr": "Costa Rica",
    "cu": "Cuba",
    "cv": "Cabo Verde",
    "cw": "Curaçao",
    "cx": "Christmas Island",
    "cy": "Cyprus",
    "cz": "Czechia",
    "de": "Germany",
    "dj": "Djibouti",
    "dk": "Denmark",
    "dm": "Dominica",
    "do": "Dominican Republic",
    "dz": "Algeria",
    "ec": "Ecuador",
    "ee": "Estonia",
    "eg": "Egypt",
    "eh": "Western Sahara",
    "er": "Eritrea",
    "es": "Spain",
    "et": "Ethiopia",
    "fi": "Finland",
    "fj": "Fiji",
    "fk": "Falkland Islands (Malvinas)",
    "fm": "Micronesia",
    "fo": "Faroe Islands",
    "fr": "France",
    "ga": "Gabon",
    "gb": "United Kingdom",
    "gd": "Grenada",
    "ge": "Georgia",
    "gf": "French Guiana",
    "gg": "Guernsey",
    "gh": "Ghana",
    "gi": "Gibraltar",
    "gl": "Greenland",
    "gm": "Gambia",
    "gn": "Guinea",
    "gp": "Guadeloupe",
    "gq": "Equatorial Guinea",
    "gr": "Greece",
    "gs": "South Georgia and the South Sandwich Islands",
    "gt": "Guatemala",
    "gu": "Guam",
    "gw": "Guinea-Bissau",
    "gy": "Guyana",
    "hk": "Hong Kong",
    "hm": "Heard Island and McDonald Islands",
    "hn": "Honduras",
    "hr": "Croatia",
    "ht": "Haiti",
    "hu": "Hungary",
    "id": "Indonesia",
    "ie": "Ireland",
    "il": "Israel",
    "im": "Isle of Man",
    "in": "India",
    "io": "British Indian Ocean Territory",
    "iq": "Iraq",
    "ir": "Iran",
    "is": "Iceland",
    "it": "Italy",
    "je": "Jersey",
    "jm": "Jamaica",
    "jo": "Jordan",
    "jp": "Japan",
    "ke": "Kenya",
    "kg": "Kyrgyzstan",
    "kh": "Cambodia",
    "ki": "Kiribati",
    "km": "Comoros",
    "kn": "Saint Kitts and Nevis",
    "kp": "North Korea",
    "kr": "South Korea",
    "kw": "Kuwait",
    "ky": "Cayman Islands",
    "kz": "Kazakhstan",
    "la": "Laos",
    "lb": "Lebanon",
    "lc": "Saint Lucia",
    "li": "Liechtenstein",
    "lk": "Sri Lanka",
    "lr": "Liberia",
    "ls": "Lesotho",
    "lt": "Lithuania",
    "lu": "Luxembourg",
    "lv": "Latvia",
    "ly": "Libya",
    "ma": "Morocco",
    "mc": "Monaco",
    "md": "Moldova",
    "me": "Montenegro",
    "mf": "Saint Martin (French part)",
    "mg": "Madagascar",
    "mh": "Marshall Islands",
    "mk": "North Macedonia",
    "ml": "Mali",
    "mm": "Myanmar",
    "mn": "Mongolia",
    "mo": "Macao",
    "mp": "Northern Mariana Islands",
    "mq": "Martinique",
    "mr": "Mauritania",
    "ms": "Montserrat",
    "mt": "Malta",
    "mu": "Mauritius",
    "mv": "Maldives",
    "mw": "Malawi",
    "mx": "Mexico",
    "my": "Malaysia",
    "mz": "Mozambique",
    "na": "Namibia",
    "nc": "New Caledonia",
    "ne": "Niger",
    "nf": "Norfolk Island",
    "ng": "Nigeria",
    "ni": "Nicaragua",
    "nl": "Netherlands",
    "no": "Norway",
    "np": "Nepal",
    "nr": "Nauru",
    "nu": "Niue",
    "nz": "New Zealand",
    "om": "Oman",
    "pa": "Panama",
    "pe": "Peru",
    "pf": "French Polynesia",
    "pg": "Papua New Guinea",
    "ph": "Philippines",
    "pk": "Pakistan",
    "pl": "Poland",
    "pm": "Saint Pierre and Miquelon",
    "pn": "Pitcairn",
    "pr": "Puerto Rico",
    "ps": "Palestine",
    "pt": "Portugal",
    "pw": "Palau",
    "py": "Paraguay",
    "qa": "Qatar",
    "re": "Réunion",
    "ro": "Romania",
    "rs": "Serbia",
    "ru": "Russia",
    "rw": "Rwanda",
    "sa": "Saudi Arabia",
    "sb": "Solomon Islands",
    "sc": "Seychelles",
    "sd": "Sudan",
    "se": "Sweden",
    "sg": "Singapore",
    "sh": "Saint Helena",
    "si": "Slovenia",
    "sj": "Svalbard and Jan Mayen",
    "sk": "Slovakia",
    "sl": "Sierra Leone",
    "sm": "San Marino",
    "sn": "Senegal",
    "so": "Somalia",
    "sr": "Suriname",
    "ss": "South Sudan",
    "st": "Sao Tome and Principe",
    "sv": "El Salvador",
    "sx": "Sint Maarten (Dutch part)",
    "sy": "Syria",
    "sz": "Eswatini",
    "tc": "Turks and Caicos Islands",
    "td": "Chad",
    "tf": "French Southern Territories",
    "tg": "Togo",
    "th": "Thailand",
    "tj": "Tajikistan",
    "tk": "Tokelau",
    "tl": "Timor-Leste",
    "tm": "Turkmenistan",
    "tn": "Tunisia",
    "to": "Tonga",
    "tr": "Türkiye",
    "tt": "Trinidad and Tobago",
    "tv": "Tuvalu",
    "tw": "Taiwan",
    "tz": "Tanzania",
    "ua": "Ukraine",
    "ug": "Uganda",
    "um": "U.S. Minor Outlying Islands",
    "us": "United States",
    "uy": "Uruguay",
    "uz": "Uzbekistan",
    "va": "Vatican City",
    "vc": "Saint Vincent and the Grenadines",
    "ve": "Venezuela",
    "vg": "British Virgin Islands",
    "vi": "U.S. Virgin Islands",
    "vn": "Vietnam",
    "vu": "Vanuatu",
    "wf": "Wallis and Futuna",
    "ws": "Samoa",
    "ye": "Yemen",
    "yt": "Mayotte",
    "za": "South Africa",
    "zm": "Zambia",
    "zw": "Zimbabwe",
}

_EXTRA_NAME_FORMS: dict[str, str] = {
    "turkey": "tr",
    "america": "us",
    "arab republic of egypt": "eg",
    "argentine republic": "ar",
    "bolivarian republic of venezuela": "ve",
    "bolivia plurinational state of": "bo",
    "britain": "gb",
    "brunei darussalam": "bn",
    "burma": "mm",
    "cape verde": "cv",
    "commonwealth of dominica": "dm",
    "commonwealth of the bahamas": "bs",
    "commonwealth of the northern mariana islands": "mp",
    "congo": "cd",
    "congo brazzaville": "cg",
    "congo the democratic republic of the": "cd",
    "czech republic": "cz",
    "democratic people s republic of korea": "kp",
    "democratic republic of congo": "cd",
    "democratic republic of sao tome and principe": "st",
    "democratic republic of the congo": "cd",
    "democratic republic of timor leste": "tl",
    "democratic socialist republic of sri lanka": "lk",
    "drc": "cd",
    "east timor": "tl",
    "eastern republic of uruguay": "uy",
    "emirates": "ae",
    "england": "gb",
    "federal democratic republic of ethiopia": "et",
    "federal democratic republic of nepal": "np",
    "federal republic of germany": "de",
    "federal republic of nigeria": "ng",
    "federal republic of somalia": "so",
    "federated states of micronesia": "fm",
    "federative republic of brazil": "br",
    "french republic": "fr",
    "gabonese republic": "ga",
    "grand duchy of luxembourg": "lu",
    "great britain": "gb",
    "hashemite kingdom of jordan": "jo",
    "hellenic republic": "gr",
    "holland": "nl",
    "holy see": "va",
    "holy see vatican city state": "va",
    "hong kong special administrative region of china": "hk",
    "independent state of papua new guinea": "pg",
    "independent state of samoa": "ws",
    "iran islamic republic of": "ir",
    "islamic republic of afghanistan": "af",
    "islamic republic of iran": "ir",
    "islamic republic of mauritania": "mr",
    "islamic republic of pakistan": "pk",
    "italian republic": "it",
    "ivory coast": "ci",
    "kingdom of bahrain": "bh",
    "kingdom of belgium": "be",
    "kingdom of bhutan": "bt",
    "kingdom of cambodia": "kh",
    "kingdom of denmark": "dk",
    "kingdom of eswatini": "sz",
    "kingdom of lesotho": "ls",
    "kingdom of morocco": "ma",
    "kingdom of norway": "no",
    "kingdom of saudi arabia": "sa",
    "kingdom of spain": "es",
    "kingdom of sweden": "se",
    "kingdom of thailand": "th",
    "kingdom of the netherlands": "nl",
    "kingdom of tonga": "to",
    "korea democratic people s republic of": "kp",
    "korea republic of": "kr",
    "kyrgyz republic": "kg",
    "lao people s democratic republic": "la",
    "lebanese republic": "lb",
    "macao special administrative region of china": "mo",
    "macau": "mo",
    "macedonia": "mk",
    "micronesia federated states of": "fm",
    "moldova republic of": "md",
    "palestine state of": "ps",
    "people s democratic republic of algeria": "dz",
    "people s republic of bangladesh": "bd",
    "people s republic of china": "cn",
    "plurinational state of bolivia": "bo",
    "portuguese republic": "pt",
    "principality of andorra": "ad",
    "principality of liechtenstein": "li",
    "principality of monaco": "mc",
    "republic of albania": "al",
    "republic of angola": "ao",
    "republic of armenia": "am",
    "republic of austria": "at",
    "republic of azerbaijan": "az",
    "republic of belarus": "by",
    "republic of benin": "bj",
    "republic of bosnia and herzegovina": "ba",
    "republic of botswana": "bw",
    "republic of bulgaria": "bg",
    "republic of burundi": "bi",
    "republic of cabo verde": "cv",
    "republic of cameroon": "cm",
    "republic of chad": "td",
    "republic of chile": "cl",
    "republic of colombia": "co",
    "republic of congo": "cg",
    "republic of costa rica": "cr",
    "republic of cote d ivoire": "ci",
    "republic of croatia": "hr",
    "republic of cuba": "cu",
    "republic of cyprus": "cy",
    "republic of djibouti": "dj",
    "republic of ecuador": "ec",
    "republic of el salvador": "sv",
    "republic of equatorial guinea": "gq",
    "republic of estonia": "ee",
    "republic of fiji": "fj",
    "republic of finland": "fi",
    "republic of ghana": "gh",
    "republic of guatemala": "gt",
    "republic of guinea": "gn",
    "republic of guinea bissau": "gw",
    "republic of guyana": "gy",
    "republic of haiti": "ht",
    "republic of honduras": "hn",
    "republic of iceland": "is",
    "republic of india": "in",
    "republic of indonesia": "id",
    "republic of iraq": "iq",
    "republic of kazakhstan": "kz",
    "republic of kenya": "ke",
    "republic of kiribati": "ki",
    "republic of latvia": "lv",
    "republic of liberia": "lr",
    "republic of lithuania": "lt",
    "republic of madagascar": "mg",
    "republic of malawi": "mw",
    "republic of maldives": "mv",
    "republic of mali": "ml",
    "republic of malta": "mt",
    "republic of mauritius": "mu",
    "republic of moldova": "md",
    "republic of mozambique": "mz",
    "republic of myanmar": "mm",
    "republic of namibia": "na",
    "republic of nauru": "nr",
    "republic of nicaragua": "ni",
    "republic of north macedonia": "mk",
    "republic of palau": "pw",
    "republic of panama": "pa",
    "republic of paraguay": "py",
    "republic of peru": "pe",
    "republic of poland": "pl",
    "republic of san marino": "sm",
    "republic of senegal": "sn",
    "republic of serbia": "rs",
    "republic of seychelles": "sc",
    "republic of sierra leone": "sl",
    "republic of singapore": "sg",
    "republic of slovenia": "si",
    "republic of south africa": "za",
    "republic of south sudan": "ss",
    "republic of suriname": "sr",
    "republic of tajikistan": "tj",
    "republic of the congo": "cg",
    "republic of the gambia": "gm",
    "republic of the marshall islands": "mh",
    "republic of the niger": "ne",
    "republic of the philippines": "ph",
    "republic of the sudan": "sd",
    "republic of trinidad and tobago": "tt",
    "republic of tunisia": "tn",
    "republic of turkiye": "tr",
    "republic of uganda": "ug",
    "republic of uzbekistan": "uz",
    "republic of vanuatu": "vu",
    "republic of yemen": "ye",
    "republic of zambia": "zm",
    "republic of zimbabwe": "zw",
    "russian federation": "ru",
    "rwandese republic": "rw",
    "saint helena ascension and tristan da cunha": "sh",
    "slovak republic": "sk",
    "socialist republic of viet nam": "vn",
    "state of israel": "il",
    "state of kuwait": "kw",
    "state of qatar": "qa",
    "sultanate of oman": "om",
    "swaziland": "sz",
    "swiss confederation": "ch",
    "syrian arab republic": "sy",
    "taiwan province of china": "tw",
    "tanzania united republic of": "tz",
    "the bahamas": "bs",
    "the gambia": "gm",
    "the netherlands": "nl",
    "the state of eritrea": "er",
    "the state of palestine": "ps",
    "togolese republic": "tg",
    "uae": "ae",
    "uk": "gb",
    "union of the comoros": "km",
    "united kingdom of great britain and northern ireland": "gb",
    "united mexican states": "mx",
    "united republic of tanzania": "tz",
    "united states minor outlying islands": "um",
    "united states of america": "us",
    "usa": "us",
    "vatican": "va",
    "venezuela bolivarian republic of": "ve",
    "viet nam": "vn",
    "virgin islands british": "vg",
    "virgin islands of the united states": "vi",
    "virgin islands u s": "vi",
}

_AFRICA = """
    ao bf bi bj bw cd cf cg ci cm cv dj dz eg eh er et ga gh gm gn gq gw ke
    km lr ls ly ma mg ml mr mu mw mz na ne ng re rw sc sd sh sl sn so ss st
    sz td tg tn tz ug yt za zm zw
"""
_ASIA = """
    ae af am az bd bh bn bt cc cn cx cy ge hk id il in io iq ir jo jp kg kh
    kp kr kw kz la lb lk mm mn mo mv my np om ph pk ps qa sa sg sy th tj tl
    tm tr tw uz vn ye
"""
_EUROPE = """
    ad al at ax ba be bg by ch cz de dk ee es fi fo fr gb gg gi gr hr hu ie
    im is it je li lt lu lv mc md me mk mt nl no pl pt ro rs ru se si sj sk
    sm ua va
"""
_NORTH_AMERICA = """
    ag ai aw bb bl bm bq bs bz ca cr cu cw dm do gd gl gp gt hn ht jm kn ky
    lc mf mq ms mx ni pa pm pr sv sx tc tt us vc vg vi
"""
_SOUTH_AMERICA = """
    ar bo br cl co ec fk gf gy pe py sr uy ve
"""
_OCEANIA = """
    as au ck fj fm gu ki mh mp nc nf nr nu nz pf pg pn pw sb tk to tv um vu
    wf ws
"""
_ANTARCTICA = """
    aq bv gs hm tf
"""

# Continent name per compact code block above (UN-style six continents +
# Antarctica). Specials: Kosovo sits in Europe, the dissolved Netherlands
# Antilles in North America (Caribbean); EU/INT are supranational.
_CONTINENT_BLOCKS: dict[str, str] = {
    "Africa": _AFRICA,
    "Asia": _ASIA,
    "Europe": _EUROPE,
    "North America": _NORTH_AMERICA,
    "South America": _SOUTH_AMERICA,
    "Oceania": _OCEANIA,
    "Antarctica": _ANTARCTICA,
}

CONTINENT_OF: dict[str, str] = {
    code: continent for continent, block in _CONTINENT_BLOCKS.items() for code in block.split()
}
CONTINENT_OF.update({"xk": "Europe", "an": "North America"})

CONTINENTS: tuple[str, ...] = (
    "Africa",
    "Asia",
    "Europe",
    "North America",
    "South America",
    "Oceania",
    "Antarctica",
)


def _slug(value: str) -> str:
    """Lowercase, strip accents, unify separators -- the alias lookup key."""
    s = unicodedata.normalize("NFKD", value)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    for sep in "-_/,.'\u2019()":
        s = s.replace(sep, " ")
    return " ".join(s.split())


@lru_cache(maxsize=1)
def _name_index() -> dict[str, str]:
    """slug(any known name form) -> lowercase code. Built once, stdlib only."""
    index: dict[str, str] = {}
    for code, name in COUNTRY_NAMES.items():
        index[_slug(name)] = code
    for code, name in SPECIAL_CODES.items():
        index[_slug(name)] = code
    index.update(_EXTRA_NAME_FORMS)
    return index


def normalize_country(value: str | None) -> str | None:
    """Canonicalise any country representation to a lowercase ISO-2 code.

    Accepts codes in any case ("us", "US"), full names ("United States"),
    catalog slugs ("united-states"), and common shorthand ("USA", "UK").
    Returns ``None`` for empty or unrecognised input -- never guesses.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low in ISO_3166_1_ALPHA2 or low in SPECIAL_CODES:
        return low
    return _name_index().get(_slug(raw))


def country_display_name(value: str | None) -> str | None:
    """Full English name for a stored code (or any normalisable form).

    Unrecognised values come back AS-IS so legacy/junk data stays visible
    (degrade loudly) instead of being masked by a fabricated name.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    code = normalize_country(raw)
    if code is None:
        return raw
    return COUNTRY_NAMES.get(code) or SPECIAL_CODES.get(code) or raw


def continent_of(value: str | None) -> str | None:
    """Continent bucket for a code/name; ``None`` if unknown or supranational."""
    code = normalize_country(value)
    return CONTINENT_OF.get(code) if code else None
