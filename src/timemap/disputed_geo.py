"""Pure transform: Natural Earth's disputed/breakaway areas -> the CONTESTED asset.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE RULING THIS SERVES (Q826, Q803, 2026-09-15): a disputed area is rendered
CONTESTED showing BOTH claims, never a silent pick. A world map that quietly assigns
Crimea, Aksai Chin or Western Sahara to one claimant is making a political statement
in the app's voice, and this project does not do that in any other surface either.

WHY THIS SOURCE CAN ANSWER THE QUESTION AT ALL. Natural Earth's
``admin_0_breakaway_disputed_areas`` layer does not merely mark an area as disputed:
each feature carries an ``ADM0_A3_<POV>`` field per point of view, so the SAME polygon
records who each of ~33 national/institutional viewpoints considers it to belong to.
The claims are therefore READ OUT of the data, never curated here by hand -- which is
what lets the app show a difference between conventions without adopting one.

TWO HONESTY RULES ENCODED BELOW.

* An alpha-3 that resolves to no country is NOT a claimant. Natural Earth uses
  internal codes (``B16``, ``C02``, ...) for "this viewpoint treats the area as
  belonging to no recognised state". Those become a NULL view -- *undetermined* --
  and never a fabricated country. Dropping them silently would have turned an
  explicit refusal-to-assign into a missing data point.
* Names travel as DATA, not as translation. Natural Earth ships ``NAME_<lang>`` for
  every one of this app's twelve locales, so a contested area is named in the
  reader's language from the source's own field. Nothing here is translated by us,
  and a locale the source does not carry is simply absent rather than filled in.
"""

from __future__ import annotations

from src.timemap.outline import _bbox_span, _coarsen_ring, _iter_rings

# The app's twelve locales. Natural Earth carries a NAME_<lang> for each of them.
APP_LOCALES: tuple[str, ...] = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")

# The points of view Natural Earth records per feature. ISO = the ISO/de-jure reading,
# TLC = Natural Earth's own "top level country" de-facto assignment; the rest are
# national viewpoints, keyed by the country whose view they are.
POV_KEYS: tuple[str, ...] = (
    "ISO", "TLC", "AR", "BD", "BR", "CN", "DE", "EG", "ES", "FR", "GB", "GR", "ID",
    "IL", "IN", "IT", "JP", "KO", "MA", "NL", "NP", "PK", "PL", "PS", "PT", "RU",
    "SA", "SE", "TR", "TW", "UA", "US", "VN",
)

_A3_FIELDS = ("ADM0_A3", "ISO_A3", "ISO_A3_EH", "SOV_A3", "BRK_A3")

# Natural Earth's per-viewpoint feature class. "Admin-0 country" means THAT viewpoint
# recognises the area as a state in its own right -- which is how a self-declared
# entity's own claim is recorded, since it has no ISO alpha-2 to appear in an
# ADM0_A3_<POV> field.
_FCLASS_COUNTRY = "Admin-0 country"


def _a2_of(props: dict) -> str | None:
    """A usable lowercase alpha-2, honouring Natural Earth's ``_EH`` fallback."""
    for key in ("ISO_A2", "ISO_A2_EH"):
        v = str(props.get(key) or "").strip()
        if len(v) == 2 and v.isalpha():
            return v.lower()
    return None


def claim_index(*geojsons: dict) -> dict[str, dict]:
    """Learn ``alpha-3 -> {"a2", "name"}`` from the SAME Natural Earth release.

    Built from the release being shipped rather than from a bundled lookup table, so
    the codes in the disputed layer and the codes it is resolved against cannot drift
    apart across a refresh. Later sources do not overwrite earlier ones.
    """
    index: dict[str, dict] = {}
    for gj in geojsons:
        for feat in (gj or {}).get("features", []) or []:
            props = feat.get("properties") or {}
            a2 = _a2_of(props)
            name = str(props.get("NAME") or props.get("BRK_NAME") or props.get("ADMIN") or "")
            for field in _A3_FIELDS:
                code = str(props.get(field) or "").strip()
                if len(code) != 3:
                    continue
                entry = index.setdefault(code, {"a2": None, "name": ""})
                if entry["a2"] is None and a2:
                    entry["a2"] = a2
                if not entry["name"] and name:
                    entry["name"] = name
    return index


def _names_of(props: dict) -> dict[str, str]:
    """The area's own name in each app locale, taken from Natural Earth's fields."""
    out: dict[str, str] = {}
    for loc in APP_LOCALES:
        v = str(props.get(f"NAME_{loc.upper()}") or "").strip()
        if v:
            out[loc] = v
    return out


def coarsen_disputed(
    geojson: dict,
    *,
    index: dict[str, dict] | None = None,
    precision: int = 2,
    min_span: float = 0.0,
) -> dict:
    """Reduce the disputed/breakaway layer to the compact CONTESTED asset.

    ``precision`` defaults to 2 (~1.1 km) rather than the choropleth's 1: several
    contested areas (Demchok, the Samdu and Tirpani Valleys) are small enough that
    11 km rounding collapses them below a drawable ring, and an area that vanishes
    is the one outcome this asset exists to prevent.

    Returns ``{"areas": [...], "views": [...], "precision", "source"}``; pure.
    """
    idx = index or {}
    areas: list[dict] = []
    for feat in (geojson or {}).get("features", []) or []:
        props = feat.get("properties") or {}
        rings = [r for r in (_coarsen_ring(x, precision) for x in _iter_rings(feat.get("geometry") or {}))
                 if len(r) >= 4]
        if min_span > 0:
            big = [r for r in rings if _bbox_span(r) >= min_span]
            rings = big or ([max(rings, key=_bbox_span)] if rings else [])
        if not rings:
            continue

        base = str(props.get("ADM0_A3") or "").strip()
        fclass = {p.lower(): str(props.get(f"FCLASS_{p}") or "").strip() for p in POV_KEYS}
        recognised_by = sorted(k for k, v in fclass.items() if v == _FCLASS_COUNTRY)

        # A SELF-DECLARED entity has a claim of its own, and it is the one an
        # alpha-3 sweep cannot see: Abkhazia, Somaliland and Northern Cyprus carry
        # Natural Earth's internal codes (B35, B30, B20), never an ISO one, so
        # resolving claims from the ADM0_A3_<POV> fields alone lists ONLY the parent
        # state -- which is precisely the silent pick Q826 forbids, in the parent's
        # favour. Recognised by at least one viewpoint, or classed a breakaway: both
        # are the data saying this area claims to be a state.
        self_declared = bool(recognised_by) or str(props.get("TYPE") or "").strip().lower() == "breakaway"

        views: dict[str, str | None] = {}
        for pov in POV_KEYS:
            key = pov.lower()
            if self_declared and fclass[key] == _FCLASS_COUNTRY:
                views[key] = "self"          # this viewpoint sees the area as its own state
                continue
            code = str(props.get(f"ADM0_A3_{pov}") or "").strip() or base
            # A code the index cannot resolve to a country is an explicit
            # "belongs to no recognised state" from that viewpoint, not a gap.
            views[key] = (idx.get(code) or {}).get("a2")

        name = str(props.get("BRK_NAME") or props.get("NAME") or props.get("ADMIN") or "")

        claims: list[dict] = []
        if self_declared:
            claims.append({
                "a2": None,                                    # no ISO code exists
                "a3": str(props.get("BRK_A3") or base or ""),
                "name": name,
                "self": True,
                "recognised_by": recognised_by,
            })
        seen: set[str] = set()
        for code in [base, *(str(props.get(f"ADM0_A3_{p}") or "").strip() for p in POV_KEYS)]:
            entry = idx.get(code)
            if not entry or not entry.get("a2") or entry["a2"] in seen:
                continue
            seen.add(entry["a2"])
            claims.append({"a2": entry["a2"], "a3": code, "name": entry.get("name") or code,
                           "self": False, "recognised_by": []})
        # The area's own claim first, then the recognised states in a stable order.
        if self_declared:
            claims = [claims[0], *sorted(claims[1:], key=lambda c: c["a2"] or "")]
        else:
            claims = sorted(claims, key=lambda c: c["a2"] or "")
        areas.append({
            "id": str(props.get("NE_ID") or name),
            "name": name,
            "names": _names_of(props),
            "type": str(props.get("TYPE") or "Disputed"),
            "admin": (idx.get(base) or {}).get("a2"),
            "self_declared": self_declared,
            "recognised_by": recognised_by,
            "claims": claims,
            "views": views,
            "rings": rings,
        })

    areas.sort(key=lambda a: a["name"])
    return {
        "areas": areas,
        "views": [p.lower() for p in POV_KEYS],
        "precision": precision,
        "source": (geojson or {}).get("source", "natural-earth-50m-breakaway-disputed"),
    }
