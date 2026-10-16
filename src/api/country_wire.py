"""The country form of a JSON payload: alpha-3 on the wire, alpha-2 inside (Q304, S05-02 S2).

THE ARCHITECTURE, and why it is a boundary and not a hundred call sites. B1 made the STORE's
country form a property of the file (``CountryCode``: Python speaks lowercase alpha-2, the file
speaks whichever form it was stamped with). This is the same move one layer out: Python keeps
speaking lowercase alpha-2 -- its dict keys, joins, comparisons and caches never change shape --
and the JSON the app SENDS speaks uppercase alpha-3. The choice is made in ONE place, so a new
endpoint that carries a ``country`` is covered without anyone remembering to cover it, which is
the failure the per-site version of this change would have had ~100 chances at.

WHAT IT TOUCHES -- fields, never guesses:

* the keys in :data:`CODE_FIELDS` (``country``, ``jurisdiction`` ...) when the value is a CODE: two
  or three letters that :func:`src.catalog.countries.country_payload_iso3` recognises. A country
  NAME is never converted ("Niger" stays "Niger"), an unrecognised code travels exactly as it
  was (a payload that blanked it would say "no country", a different claim), and an aggregate
  is not laundered into a nation (``wld`` stays ``wld``).
* ``countries`` when it is a list of codes, and a ``code`` inside a list under ``countries``.
* the KEYS of :data:`CODE_KEYED_FIELDS` (``jurisdictions``: ``{code: count}``), summing two
  spellings of one country rather than letting the later one replace the earlier.

WHAT IT DOES NOT TOUCH, deliberately: the explicitly-named alpha-2 fields an external contract
reads (``iso2``, ``alpha2``, ``cc``, ``country_iso2``) and every explicitly-alpha-3 one (``iso3``,
``alpha3``) -- a field that names its own form never changes it.

Pure and copy-on-write: a cached payload (the analytics read-models hand the SAME dict to every
request) is never mutated, and a payload with nothing to convert is returned as the very same
object, so the boundary costs a walk, not an allocation.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from src.catalog.countries import country_payload_iso3

#: Keys whose value is ONE country code in a payload.
CODE_FIELDS: frozenset[str] = frozenset(
    {
        "country",
        "jurisdiction",
        "stored_country",
        "domain_implies",
        "place_country",
        "source_country",
        "country_code",
    }
)

#: Keys whose value is a LIST of country codes (or of objects carrying a ``code``).
CODE_LIST_FIELDS: frozenset[str] = frozenset({"countries"})

#: Keys whose value is a DICT keyed by country code.
CODE_KEYED_FIELDS: frozenset[str] = frozenset({"jurisdictions"})


def wire_code(value: Any) -> Any:
    """``value`` as it travels: its alpha-3 when it is a recognised code, otherwise ITSELF.

    Returns the very same object when nothing changes, so a caller can tell by identity.
    """
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not (2 <= len(raw) <= 3 and raw.isascii() and raw.isalpha()):
        return value
    converted = country_payload_iso3(raw)
    # An already-wire value comes back as the SAME object, so "nothing changed" is visible by identity upstream.
    return converted if converted and converted != value else value


def _convert_code_list(items: list) -> list:
    changed = False
    out: list = []
    for item in items:
        if isinstance(item, str):
            new = wire_code(item)
        elif isinstance(item, dict) and isinstance(item.get("code"), str):
            new = to_wire(item)
            code = wire_code(item["code"])
            if code is not item["code"]:
                new = dict(new)
                new["code"] = code
        else:
            new = to_wire(item)
        if new is not item:
            changed = True
        out.append(new)
    return out if changed else items


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _convert_keyed(mapping: dict) -> dict:
    out: dict = {}
    changed = False
    for key, value in mapping.items():
        new_key = wire_code(key)
        if new_key in out:
            if _is_number(out[new_key]) and _is_number(value):
                out[new_key] = out[new_key] + value  # two spellings of one country add up
                changed = True
                continue
            # Values that cannot be added (objects, booleans) are not merged and not dropped: the later one keeps the
            # spelling it came with, so both stay visible.
            new_key = key
        if new_key is not key:
            changed = True
        out[new_key] = value
    return out if changed else mapping


def to_wire(payload: Any) -> Any:
    """The payload with every country field in its wire form (see the module docstring)."""
    if isinstance(payload, dict):
        changed = False
        out: dict = {}
        for key, value in payload.items():
            if key in CODE_FIELDS:
                # A non-string under a code field (the map's `country` geometry object) is
                # still walked: only a STRING can be a code, but anything can contain one.
                new = wire_code(value) if isinstance(value, str) else to_wire(value)
            elif key in CODE_LIST_FIELDS and isinstance(value, list):
                new = _convert_code_list(value)
            elif key in CODE_KEYED_FIELDS and isinstance(value, dict):
                new = _convert_keyed(value)
            else:
                new = to_wire(value)
            if new is not value:
                changed = True
            out[key] = new
        return out if changed else payload
    if isinstance(payload, list):
        converted = [to_wire(v) for v in payload]
        return converted if any(a is not b for a, b in zip(converted, payload, strict=True)) else payload
    return payload


class CountryWireResponse(JSONResponse):
    """The app's default JSON response: renders the payload through :func:`to_wire`."""

    def render(self, content: Any) -> bytes:
        return super().render(to_wire(content))
