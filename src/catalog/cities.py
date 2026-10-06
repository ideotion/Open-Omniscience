"""
City coordinate gazetteer (name -> lat/lon/country), for the Insights map.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A small sample ships so the map renders out of the box; the full gazetteer is
generated from Wikidata (CC0) by scripts/build_city_gazetteer.py into
configs/cities.yml (preferred when present). Lookups are disambiguated by the
source's country (Paris/FR vs Paris/US), falling back to the most-populous match.
The SPARQL parser is pure and unit-tested.

TWO FILES, ONE GAZETTEER (0.5 row C, S4). ``configs/places_gazetteer.yml`` is the place
artifact ``scripts/build_place_gazetteer.py`` builds out of ingested OpenStreetMap ``place=*``
objects joined to Wikidata: it is READ BESIDE the world-city file, never in place of it, so a
country's OSM cut can never shrink the world's coverage. The two are merged BY QID, and only by
QID: where both carry the same QID the place artifact's entry wins; an entry without a QID is
never merged with another by name -- two ``Paris`` entries stay two entries, because a name is
not an identity. Every entry keeps the source it came from (:attr:`City.source`) and the
vintage of the file that held it (:attr:`City.vintage`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

_LOG = logging.getLogger(__name__)

_CONF = Path(__file__).resolve().parents[2] / "configs"
GAZETTEER_PATH = _CONF / "cities.yml"  # generated (full)
SAMPLE_PATH = _CONF / "cities.sample.yml"  # shipped (small fallback)
PLACES_GAZETTEER_PATH = _CONF / "places_gazetteer.yml"  # built from OSM place=* + Wikidata (row C S4)

#: What an entry's ``source`` says when its file does not say (a file's own ``source`` key, and an
#: entry's own, win in that order).
SOURCE_WORLD = "wikidata-wdqs"
SOURCE_SAMPLE = "shipped-sample"
SOURCE_PLACES = "osm+wikidata"

# Wikidata P625 coordinate literal, e.g. "Point(2.3522 48.8566)" (lon lat).
_POINT_RE = re.compile(r"Point\(\s*([-\d.]+)\s+([-\d.]+)\s*\)")


@dataclass
class City:
    name: str
    lat: float
    lon: float
    country: str | None = None
    population: int | None = None
    #: S05-03 (Q805 / Q818): the fields the Place gazetteer artifact carries and the
    #: shipped sample does not. ``osm`` is the OSM object as OSM writes it
    #: (``node/240109189``) and is what a Place is keyed on; ``kind`` is the OSM
    #: ``place=*`` value verbatim; ``names`` is OSM's ``name:xx`` tags. All optional: an
    #: entry without ``osm`` resolves nothing, and says so, rather than becoming a Place
    #: under an invented id.
    qid: str | None = None
    osm: str | None = None
    kind: str | None = None
    names: dict[str, str] | None = None
    #: Where THIS entry came from (``osm+wikidata``, ``osm``, ``wikidata-wdqs``, ``shipped-sample``)
    #: and the vintage of the file that held it; both None when nothing says, never a borrowed value.
    source: str | None = None
    vintage: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "country": self.country,
            "population": self.population,
        }


def _default_source(path: Path) -> str | None:
    """What an entry of ``path`` is said to come from when neither it nor its file says."""
    if path == PLACES_GAZETTEER_PATH:
        return SOURCE_PLACES
    if path == GAZETTEER_PATH:
        return SOURCE_WORLD
    if path == SAMPLE_PATH:
        return SOURCE_SAMPLE
    return None


def _load_file(p: Path) -> list[City]:
    """One gazetteer file's entries, each stamped with its source and its file's vintage."""
    if not p.exists():
        return []
    try:
        data = yaml.safe_load(p.read_text("utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        if p == PLACES_GAZETTEER_PATH:  # a damaged artifact must not take the world file's coverage with it
            _LOG.warning("%s is unreadable; reading the world gazetteer alone", p.name, exc_info=True)
            return []
        raise
    if not isinstance(data, dict):
        return []
    raw_vintage = data.get("as_of")
    vintage = str(raw_vintage) if raw_vintage else None
    file_source = str(data["source"]).strip() or None if data.get("source") else None
    default = file_source or _default_source(p)
    out: list[City] = []
    for c in data.get("cities", []):
        if not isinstance(c, dict) or c.get("name") is None:
            continue
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        names = c.get("names")
        out.append(
            City(
                name=str(c["name"]),
                lat=lat,
                lon=lon,
                country=(str(c.get("country", "")).lower() or None),
                population=c.get("population"),
                qid=_clean_qid(c.get("qid")),
                osm=_clean_osm(c.get("osm")),
                kind=(str(c["kind"]).strip() or None) if c.get("kind") else None,
                names=(
                    {str(k).strip().lower(): str(v) for k, v in names.items() if k and v}
                    if isinstance(names, dict) else None
                ),
                source=(str(c["source"]).strip() or None) if c.get("source") else default,
                vintage=vintage,
            )
        )
    return out


def merge_by_qid(world: list[City], places: list[City]) -> list[City]:
    """The world entries the place artifact does not supersede, then the artifact's own.

    Only a QID merges two entries, and where both files carry one the place artifact's entry
    wins. An entry WITHOUT a QID is never dropped for a name it shares with another: two
    entries called ``Paris`` stay two entries. (``build_index`` then disambiguates them by
    country exactly as it always did.)
    """
    taken = {c.qid for c in places if c.qid}
    kept = [c for c in world if not (c.qid and c.qid in taken)]
    return kept + list(places)


def load_cities(path: Path | None = None) -> list[City]:
    """Load the gazetteer.

    With ``path``: exactly that file. Without: the world file (generated if present, else the
    shipped sample) merged BY QID with the place artifact, when one has been built.
    """
    if path is not None:
        return _load_file(path)
    world = _load_file(GAZETTEER_PATH if GAZETTEER_PATH.exists() else SAMPLE_PATH)
    return merge_by_qid(world, _load_file(PLACES_GAZETTEER_PATH))


_QID_RE = re.compile(r"^Q[1-9][0-9]*$")
_OSM_RE = re.compile(r"^(node|way|relation)/[1-9][0-9]*$")


def _clean_qid(value) -> str | None:
    """A QID exactly as Wikidata writes one, or None -- never a repaired guess."""
    v = str(value or "").strip()
    return v if _QID_RE.match(v) else None


def _clean_osm(value) -> str | None:
    """An OSM object reference (``node/123``), or None -- never a repaired guess."""
    v = str(value or "").strip().lower()
    return v if _OSM_RE.match(v) else None


def gazetteer_path() -> Path:
    """The gazetteer the app reads: the generated artifact when present, else the sample."""
    return GAZETTEER_PATH if GAZETTEER_PATH.exists() else SAMPLE_PATH


def _file_vintage(p: Path) -> str | None:
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text("utf-8")) or {}
        raw = data.get("as_of") if isinstance(data, dict) else None
        return str(raw) if raw else None
    except (OSError, yaml.YAMLError):
        return None


@lru_cache(maxsize=1)
def gazetteer_meta() -> dict:
    """WHICH gazetteer answered, and its VINTAGE (Q805: shown wherever it resolves a place).

    The vintage is the artifact's own top-level ``as_of``, written at build time on the
    maintainer's machine. The shipped sample carries none, and says so as ``None`` rather
    than borrowing a date it does not have. ``places`` is the same three facts for the place
    artifact (``configs/places_gazetteer.yml``) read beside it; an entry's own vintage is on
    the entry (:attr:`City.vintage`), because the two files are not the same age.
    """
    p = gazetteer_path()
    return {
        "path": p.name,
        "artifact": p == GAZETTEER_PATH,
        "vintage": _file_vintage(p),
        "places": {
            "path": PLACES_GAZETTEER_PATH.name,
            "artifact": PLACES_GAZETTEER_PATH.exists(),
            "vintage": _file_vintage(PLACES_GAZETTEER_PATH),
        },
    }


def build_index(cities: list[City]) -> dict:
    """Index for lookup: by (name, country) and by name (best = most populous)."""
    by_pair: dict[tuple[str, str | None], City] = {}
    by_name: dict[str, City] = {}
    for c in cities:
        nl = c.name.lower()
        # The most populous entry keeps a (name, country) key, last-wins only among equals (the old
        # behaviour): an OSM hamlet that shares a world city's name and country must not take the
        # lookup over just by being listed after it, whatever its QID.
        cur_pair = by_pair.get((nl, c.country))
        if cur_pair is None or (c.population or 0) >= (cur_pair.population or 0):
            by_pair[(nl, c.country)] = c
        cur = by_name.get(nl)
        if cur is None or (c.population or 0) > (cur.population or 0):
            by_name[nl] = c
    return {"pair": by_pair, "name": by_name}


@lru_cache(maxsize=1)
def cached_index() -> dict:
    """The default gazetteer's lookup index, parsed ONCE per process.

    ``build_index(load_cities())`` re-reads and re-parses the whole YAML on every
    call, and :func:`src.timemap.locextract.extract_locations` was calling it
    PER ARTICLE. Measured 2026-07-30 on a gazetteer the size
    ``scripts/build_city_gazetteer.py`` actually produces from Wikidata (50,000
    cities, 5.2 MB): ``load_cities`` alone takes 17.0 SECONDS, so a 500,000-article
    import spent something like 2,300 core-hours re-parsing the same file. Even
    with the tiny shipped 21-city sample it was ~6 ms per article, 6% of
    ``extract_locations``.

    No new staleness class: ``locextract._patterns()`` and ``geocode._index()``
    already cache exactly this data for the process lifetime, so the gazetteer was
    ALREADY assumed immutable while the app runs -- it is generated offline by a
    script, never written at runtime. If anything this removes an inconsistency,
    since the cached patterns and the freshly-parsed index could previously come
    from two different versions of the file.

    Callers that supply their OWN city list keep using :func:`build_index`
    directly; this is only the default-gazetteer path."""
    return build_index(load_cities())


def lookup(index: dict, name: str, country: str | None = None) -> City | None:
    """Find a city by name, disambiguated by country when available."""
    nl = (name or "").strip().lower()
    if not nl:
        return None
    if country:
        hit = index["pair"].get((nl, country.strip().lower()))
        if hit:
            return hit
    return index["name"].get(nl)


def parse_cities_sparql(payload: dict) -> list[City]:
    """Parse a WDQS response with ?cityLabel ?coord ?cc ?population into cities."""
    bindings = (payload or {}).get("results", {}).get("bindings", [])
    out: list[City] = []
    for b in bindings:
        name = (b.get("cityLabel") or {}).get("value")
        coord = (b.get("coord") or {}).get("value")
        if not name or not coord:
            continue
        m = _POINT_RE.search(coord)
        if not m:
            continue
        lon, lat = float(m.group(1)), float(m.group(2))
        cc = (b.get("cc") or {}).get("value")
        pop_raw = (b.get("population") or {}).get("value")
        try:
            pop = int(float(pop_raw)) if pop_raw else None
        except (TypeError, ValueError):
            pop = None
        out.append(
            City(name=name, lat=lat, lon=lon, country=(cc.lower() if cc else None), population=pop)
        )
    return out
