"""R17 step 4 for the Wikipedia lane (v0.6 row D, S06-03 S2 + S3; Q819, Q820; R678): infobox addresses, located only locally.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IS READ. The wikitext this machine already STORED -- a followed (HOT) page's newest revision and a WARM page's latest text -- never the
reader's stripped text (``src/api/wiki.py`` peels the infoboxes away) and never a new request. In it, the first infobox whose TYPE is on the
edition's closed list of organisation, building and place infoboxes, and in that infobox only the fields whose KEY names an address.

WHAT IS NEVER READ (R678's condition). An infobox about a PERSON, or of any type this module does not list, is skipped and counted with its
reason. The list fails closed: a type nobody wrote down is not located, so the map can never become a way to find where an individual lives.
Addresses in article BODIES (wiki and press) are not read either: without an infobox key, a body-text grammar would place strings that only
look like addresses. That is a recorded gap, stated in the counters' ``gaps`` rather than shown as zero.

HOW AN ADDRESS IS LOCATED. Only through the local OpenStreetMap address index of the countries the user ingested
(:func:`src.osm.places.geocode`, S05-04): never an external geocoder, nothing leaves the machine (Q820). An address is located when the index
answers with one to five OSM objects carrying every word of it, all within :data:`SAME_PLACE_METRES` of each other (one address on a building
and its entrance). More answers, or answers spread further apart, are AMBIGUOUS: counted, never placed. Trailing comma parts (country, region)
may be dropped one at a time; the leading street part never is. A value with no digit has no house number and is counted, never looked up.
"Outside your OpenStreetMap countries" is claimed only when the page's own ``{{coord}}`` lies outside the bounding box of every ingested
country; anything else not found is "not located", because the index cannot tell a missing address from a differently worded one.

THE READ IS INCREMENTAL AND BOUNDED. The texts are many and compressed, so a call reads for at most :data:`SCAN_BUDGET_SECONDS` and keeps what
it learned in memory; the counters say how many of the stored texts have been read so far. A call that finds the scan busy answers with the
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
)
#: Why an infobox was not read, counted per edition.
SKIPS: tuple[str, ...] = ("about_a_person", "type_not_on_the_list")

GAPS: tuple[str, ...] = (
    "Addresses in article bodies (Wikipedia and press) are not read: only an infobox field named as an address is.",
    "Infoboxes of a type not on the edition's list are not read; the list is closed and fails closed.",
    "An address written in a script the OpenStreetMap index splits differently (Chinese, Japanese) is rarely located.",
)


def _norm(name: str) -> str:
    """A template or field name as compared here: case-folded, underscores as spaces, one space between words."""
    return " ".join((name or "").replace("_", " ").casefold().split())


def _names(*items: str) -> frozenset[str]:
    return frozenset(_norm(i) for i in items)


# The infobox types read, per edition: organisations, buildings and places. CLOSED and failing closed (R678). The template names are the
# editions' own as written from knowledge, fixture-tested; a name missing here costs a located address, never a person's privacy.
_EN_TYPES = (
    "infobox building", "infobox historic building", "infobox skyscraper", "infobox museum", "infobox company", "infobox organization",
    "infobox organisation", "infobox government agency", "infobox hospital", "infobox school", "infobox university", "infobox library",
    "infobox hotel", "infobox restaurant", "infobox shopping mall", "infobox venue", "infobox stadium", "infobox theatre", "infobox church",
    "infobox religious building", "infobox mosque", "infobox temple", "infobox hindu temple", "infobox synagogue", "infobox embassy",
    "infobox station", "infobox nrhp", "infobox airport", "infobox park", "infobox landmark", "infobox castle", "infobox zoo",
)
PLACE_TYPES: dict[str, frozenset[str]] = {
    "en": _names(*_EN_TYPES),
    "fr": _names(
        "infobox bâtiment", "infobox monument", "infobox musée", "infobox entreprise", "infobox organisation", "infobox université",
        "infobox école", "infobox établissement scolaire", "infobox hôpital", "infobox hôtel", "infobox gare", "infobox stade",
        "infobox salle de spectacle", "infobox édifice religieux", "infobox château", "infobox bibliothèque", "infobox administration",
        "infobox ambassade", "infobox gratte-ciel", "infobox parc",
    ),
    "de": _names(
        "infobox unternehmen", "infobox hochschule", "infobox museum", "infobox bauwerk", "infobox hochhaus", "infobox bahnhof",
        "infobox stadion", "infobox krankenhaus", "infobox schule", "infobox bibliothek", "infobox behörde", "infobox kirchengebäude",
        "infobox hotel", "infobox theater", "infobox organisation", "infobox burg",
    ),
    "es": _names(
        "ficha de edificio", "ficha de museo", "ficha de empresa", "ficha de organización", "ficha de universidad", "ficha de hospital",
        "ficha de estación", "ficha de estadio", "ficha de edificio religioso", "ficha de recinto", "ficha de institución educativa",
        "ficha de biblioteca", "ficha de hotel", "ficha de castillo", "ficha de monumento", "ficha de rascacielos",
    ),
    "pt": _names(
        "info/edifício", "info/empresa", "info/museu", "info/organização", "info/universidade", "info/hospital", "info/estação",
        "info/estádio", "info/igreja", "info/escola", "info/biblioteca", "info/hotel", "info/castelo", "info/monumento", "info/arranha-céu",
    ),
    "ru": _names(
        "карточка здания", "здание", "компания", "музей", "организация", "университет", "больница", "станция метро",
        "железнодорожная станция", "стадион", "храм", "школа", "библиотека", "гостиница", "театр",
    ),
    "zh": _names(*_EN_TYPES, "infobox 建筑物", "infobox 公司", "infobox 博物馆", "infobox 大学"),
    "ja": _names(*_EN_TYPES, "infobox 建築物", "基礎情報 会社", "infobox 博物館", "日本の大学", "駅情報", "infobox 病院", "infobox 学校"),
    "ar": _names(
        "صندوق معلومات مبنى", "صندوق معلومات شركة", "صندوق معلومات متحف", "صندوق معلومات جامعة", "صندوق معلومات منظمة",
        "صندوق معلومات مستشفى", "صندوق معلومات محطة", "صندوق معلومات ملعب", "صندوق معلومات مسجد", "صندوق معلومات مدرسة",
        "صندوق معلومات مكتبة", "صندوق معلومات فندق", "صندوق معلومات كنيسة",
    ),
    "id": _names(*_EN_TYPES, "infobox perusahaan", "infobox universitas", "infobox masjid", "infobox gedung", "infobox stasiun"),
    "hi": _names(*_EN_TYPES, "ज्ञानसन्दूक भवन", "ज्ञानसन्दूक कंपनी", "ज्ञानसन्दूक संग्रहालय", "ज्ञानसन्दूक विश्वविद्यालय"),
    "bn": _names(*_EN_TYPES, "তথ্যছক ভবন", "তথ্যছক কোম্পানি", "তথ্যছক জাদুঘর", "তথ্যছক বিশ্ববিদ্যালয়", "তথ্যছক সংস্থা"),
}

# Infobox types about a PERSON. Only for the count of "skipped: about a person": the closed list above already keeps them out, and an
# unlisted person type is skipped as "type not on the list" all the same.
_PERSON_WORDS = (
    "person", "biography", "officeholder", "politician", "musical artist", "actor", "writer", "scientist", "sportsperson", "athlete",
    "footballer", "royalty", "military person", "criminal", "artist", "philosopher", "religious biography", "journalist",
    "personnalité", "biographie", "politicien", "acteur", "écrivain", "sportif", "footballeur", "artiste",
    "person", "persönlichkeit", "biografía", "ficha de persona", "ficha de político", "ficha de deportista", "ficha de artista",
    "info/biografia", "info/político", "info/ator", "персона", "государственный деятель", "учёный", "писатель", "футболист",
    "人物", "政治家", "شخص", "سيرة", "tokoh", "biografi", "व्यक्ति", "ব্যক্তি",
)
#: Person infoboxes some editions name without an infobox prefix (ru, ja, zh), so they are recognised as infoboxes at all.
_PERSON_UNPREFIXED = _names("персона", "государственный деятель", "учёный", "писатель", "футболист", "人物", "政治家", "基礎情報 人物")

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
_REF = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_EXTLINK = re.compile(r"\[(?:https?:)?//\S+\s*([^\]]*)\]")


def infobox_type_and_fields(wikitext: str) -> tuple[str, dict[str, str], bool] | None:
    """The first infobox of ANY kind, as ``(normalised type, fields, a person infobox is on the page)``; ``None`` with no infobox.

    Every template name on the page is looked at, so a person's infobox anywhere on it is seen: R678's rule is about the PAGE, and a
    building infobox below a biography's must not be read.
    """
    text = wikitext or ""
    first: tuple[str, int] | None = None
    person = False
    for match in _TEMPLATE_OPEN.finditer(text):
        name = _norm(match.group(1))
        if not _looks_like_infobox(name):
            continue
        if _is_person_type(name):
            person = True
        if first is None:
            first = (name, match.start())
    if first is None:
        return None
    name, start = first
    body = _balanced_template(text, start)
    if body is None:
        return None
    fields: dict[str, str] = {}
    for part in _split_top_level(body):
        key, sep, value = part.partition("=")
        k = _norm(key)
        if sep and k and k not in fields:
            fields[k] = value.strip()
    return name, fields, person


_INFOBOX_PREFIXES = ("infobox", "ficha de", "info/", "карточка", "基礎情報", "صندوق معلومات", "ज्ञानसन्दूक", "তথ্যছক")
_ALL_PLACE_TYPES: frozenset[str] = frozenset().union(*PLACE_TYPES.values())


def _is_person_type(name: str) -> bool:
    return name in _PERSON_UNPREFIXED or any(word in name for word in _PERSON_WORDS)


def _looks_like_infobox(name: str) -> bool:
    return name.startswith(_INFOBOX_PREFIXES) or name in _ALL_PLACE_TYPES or name in _PERSON_UNPREFIXED


def classify_type(edition: str, name: str, *, person_on_page: bool = False) -> str | None:
    """``None`` when the infobox may be read, else the skip reason. A person infobox anywhere on the page wins over every other type."""
    if person_on_page or _is_person_type(name):
        return "about_a_person"
    if name in PLACE_TYPES.get(edition, frozenset()):
        return None
    return "type_not_on_the_list"


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


def variants(text: str) -> list[str]:
    """The address as written, then with trailing comma parts dropped one at a time. The leading part is never dropped."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    out = []
    for n in range(len(parts), 0, -1):
        candidate = ", ".join(parts[:n])
        if has_house_number(candidate):
            out.append(candidate)
    return out


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


def resolve(text: str, geocoder: Any = None) -> dict[str, Any]:
    """One cleaned address through the local index. Returns ``{"status", ...}``; a ``located`` answer carries the point and its objects."""
    if geocoder is None:
        from src.osm.places import geocode as geocoder
    tries = variants(text)
    if not tries:
        return {"status": "no_house_number"}
    for query in tries:
        answer = geocoder(query, limit=MAX_ANSWERS + 1)
        status = answer.get("status")
        if status == "no-country":
            return {"status": "no_osm_country"}
        results = answer.get("results") or []
        total = int(answer.get("total") or 0)
        if not results:
            continue
        if total > MAX_ANSWERS or len(results) != total:
            return {"status": "ambiguous", "answers": total}
        points = [(float(r["lat"]), float(r["lon"])) for r in results]
        spread = max((metres(p, q) for p in points for q in points), default=0.0)
        if spread > SAME_PLACE_METRES:
            return {"status": "ambiguous", "answers": total}
        first = results[0]
        countries = {c.get("alpha3"): c.get("vintage") for c in answer.get("countries") or []}
        return {
            "status": "located",
            "query": query,
            "lat": points[0][0],
            "lon": points[0][1],
            "osm_object": first.get("object"),
            "osm_address": first.get("address"),
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


def page_addresses(edition: str, wikitext: str) -> dict[str, Any]:
    """Pure: what one stored page offers. ``{"skip": reason}``, ``{"none": True}`` or ``{"type", "candidates": [(field, text)], "coord"}``."""
    found = infobox_type_and_fields(wikitext)
    if found is None:
        return {"none": True}
    kind, fields, person = found
    skip = classify_type(edition, kind, person_on_page=person)
    if skip is not None:
        return {"skip": skip}
    keys = ADDRESS_KEYS.get(edition, ADDRESS_KEYS["en"])
    candidates = []
    for key, value in fields.items():
        if key in keys:
            cleaned = clean_value(value)
            if cleaned:
                candidates.append((key, cleaned))
    if not candidates:
        return {"none": True}
    return {"type": kind, "candidates": candidates, "coord": page_coordinate(wikitext)}


# --------------------------------------------------------------------------- #
# The incremental scan over the stored texts, and its snapshot.
# --------------------------------------------------------------------------- #
@dataclass
class _Page:
    edition: str
    tier: str
    ref: str  # "hot:<entity id>" or "warm:<row id>"
    version: str
    title: str | None
    external_id: str | None
    offer: dict[str, Any]


@dataclass
class _State:
    pages: dict[str, _Page] = field(default_factory=dict)
    hot_after: int = 0
    warm_after: int = 0
    resolved: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    osm_signature: str | None = None
    lane_marker: Any = None


_lock = threading.Lock()
_state = _State()
_last: dict[str, Any] | None = None


def reset() -> None:
    """Forget every page read (tests, and a lane that was replaced)."""
    global _state, _last
    with _lock:
        _state = _State()
        _last = None


def _osm_scope() -> tuple[str, list[tuple[float, float, float, float]]]:
    """The ingested, indexed countries as a signature (their vintages) and their bounding boxes. Reads the OSM lane; ``("", [])`` without one."""
    from src.osm.places import index_state

    try:
        scope = [c for c in index_state() if c.get("indexed")]
    except Exception as exc:  # noqa: BLE001 - an unreadable OSM lane locates nothing, and says so as no country
        log_failure(_LOG, "located addresses: the OSM index state could not be read", exc, level=logging.WARNING)
        return "", []
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


def _scan(lane: Any, state: _State, deadline: float) -> None:
    """Read stored texts in id order until the deadline: HOT's newest revisions first, then WARM's latest texts."""
    from sqlalchemy import func, select

    from src.versioned.models import VersionedEntity, VersionedRevision
    from src.wiki.lane_models import WikiWarmPage

    newest = (
        select(VersionedRevision.entity_id, func.max(VersionedRevision.id).label("rid"))
        .where(VersionedRevision.content.is_not(None))
        .group_by(VersionedRevision.entity_id)
        .subquery()
    )
    while time.monotonic() < deadline:
        rows = lane.execute(
            select(VersionedEntity.id, VersionedEntity.language, VersionedEntity.title, VersionedEntity.external_id, newest.c.rid)
            .join(newest, newest.c.entity_id == VersionedEntity.id)
            .where(VersionedEntity.id > state.hot_after)
            .order_by(VersionedEntity.id)
            .limit(SCAN_BATCH)
        ).all()
        if not rows:
            break
        texts = dict(lane.execute(select(VersionedRevision.id, VersionedRevision.content).where(VersionedRevision.id.in_([r[4] for r in rows]))).all())
        for eid, language, title, external_id, rid in rows:
            edition = str(language or "")
            ref = f"hot:{eid}"
            if edition in PLACE_TYPES:
                state.pages[ref] = _Page(edition, "hot", ref, str(rid), title, external_id, page_addresses(edition, texts.get(rid) or ""))
            state.hot_after = eid
    while time.monotonic() < deadline:
        rows = lane.execute(
            select(WikiWarmPage.id, WikiWarmPage.edition, WikiWarmPage.title, WikiWarmPage.page_id, WikiWarmPage.latest_revid, WikiWarmPage.latest_text)
            .where(WikiWarmPage.id > state.warm_after, WikiWarmPage.latest_text.is_not(None))
            .order_by(WikiWarmPage.id)
            .limit(SCAN_BATCH)
        ).all()
        if not rows:
            break
        for wid, edition, title, page_id, revid, text in rows:
            ref = f"warm:{wid}"
            if edition in PLACE_TYPES:
                state.pages[ref] = _Page(edition, "warm", ref, str(revid), title, f"{edition}:#{page_id}", page_addresses(edition, text or ""))
            state.warm_after = wid


def _totals(lane: Any) -> dict[str, int]:
    from sqlalchemy import func, select

    from src.versioned.models import VersionedRevision
    from src.wiki.lane_models import WikiWarmPage

    hot = lane.execute(select(func.count(func.distinct(VersionedRevision.entity_id))).where(VersionedRevision.content.is_not(None))).scalar() or 0
    warm = lane.execute(select(func.count(WikiWarmPage.id)).where(WikiWarmPage.latest_text.is_not(None))).scalar() or 0
    return {"hot": int(hot), "warm": int(warm)}


def located_report(lane: Any, *, budget: float = SCAN_BUDGET_SECONDS, geocoder: Any = None) -> dict[str, Any]:
    """Advance the scan for at most ``budget`` seconds, resolve what it found, and report: points with provenance, counters per edition.

    Never raises: an unreadable lane is ``measured: false`` with the reason.
    """
    global _last
    if not _lock.acquire(blocking=False):
        # Another call is reading: the last answer, marked as such, rather than a wait (a poll never waits on a read).
        return {**_last, "from_previous_read": True} if _last else {"measured": False, "reason": "busy", "scope": SCOPE}
    try:
        signature, boxes = _osm_scope()
        if _state.osm_signature != signature:
            _state.resolved.clear()
            _state.osm_signature = signature
        try:
            _scan(lane, _state, time.monotonic() + budget)
            totals = _totals(lane)
        except Exception as exc:  # noqa: BLE001 - the report says it could not read, never blanks the surface it rides
            log_failure(_LOG, "located addresses: the stored texts could not be read", exc, level=logging.WARNING)
            return {"measured": False, "reason": "unreadable", "scope": SCOPE}
        _last = _report(_state, totals, boxes, geocoder)
        return _last
    finally:
        _lock.release()


def _report(state: _State, totals: dict[str, int], boxes: list, geocoder: Any) -> dict[str, Any]:
    per: dict[str, dict[str, int]] = {}
    points: list[dict[str, Any]] = []
    for page in state.pages.values():
        row = per.setdefault(page.edition, {})
        offer = page.offer
        if "skip" in offer:
            row["skipped_" + offer["skip"]] = row.get("skipped_" + offer["skip"], 0) + 1
            continue
        if "candidates" not in offer:
            continue
        for key, text in offer["candidates"]:
            row["found"] = row.get("found", 0) + 1
            memo = (page.edition, text)
            if memo not in state.resolved:
                state.resolved[memo] = resolve(text, geocoder) if state.osm_signature not in ("", "[]") else {"status": "no_osm_country"}
            answer = state.resolved[memo]
            status = answer["status"]
            if status == "not_located" and outside_every_country(offer.get("coord"), boxes):
                status = "outside_your_osm_countries"
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
                        **{k: answer[k] for k in ("query", "lat", "lon", "osm_object", "osm_address", "osm_country", "osm_vintage", "answers")},
                    }
                )
    read = {"hot": sum(1 for p in state.pages if p.startswith("hot:")), "warm": sum(1 for p in state.pages if p.startswith("warm:"))}
    return {
        "measured": True,
        "scope": SCOPE,
        "points": points,
        "per_edition": {e: dict(sorted(c.items())) for e, c in sorted(per.items()) if c},
        "texts_read": read,
        "texts_held": totals,
        "complete": read["hot"] >= totals["hot"] and read["warm"] >= totals["warm"],
        "statuses": list(STATUSES),
        "skips": list(SKIPS),
        "gaps": list(GAPS),
        "method": (
            "The first infobox of a stored page, when its type is on the edition's closed list of organisation, building and place "
            "infoboxes; in it, the fields named as an address. Each is looked up in the local OpenStreetMap address index of the "
            f"countries you ingested: located when one to {MAX_ANSWERS} objects carry every word and lie within "
            f"{int(SAME_PLACE_METRES)} m of each other. Nothing is looked up anywhere else."
        ),
    }
