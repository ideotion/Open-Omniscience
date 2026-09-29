"""The PURE Wikidata item core for the entity spine: QIDs in, items out. No sockets.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q724 = a: «labels, descriptions and a claims subset (P31, P17, P625, P571…) per QID the corpus
mentions, fetched at etiquette pace, cached locally.»

**WHICH API.** The Action API's ``wbgetentities`` on ``www.wikidata.org`` -- the host the ring
load already reaches and ``docs/SECURITY.md`` already lists, so the spine adds no new host. It
accepts up to 50 ids per request (the API's own ``ids`` limit for a non-bot client), and R8's
bar is per REQUEST, so one request carries a whole batch. That is a PROPOSED default (S05-03 §6
leaves the choice of API to the maintainer), recorded in ``OPEN_QUEUE.md``; the Query Service
would be a second host, which is why it was not the default.

**IT IS NOT ``src/analytics/wikidata_rings.py``,** whose ``wbentities_url`` asks for one item's
labels AND aliases to build a ring, and not ``src/catalog/wikidata_enrich.py``, which asks for
claims to type a news source. Three requests with three different ``props``; the endpoint and
the polite interval are imported from the ring module so there is one of each.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field

from src.analytics.wikidata_rings import API_ENDPOINT, LANGS

#: The claims the ruling names, and no others (S05-03 §6: the subset beyond these four is
#: not this slice's to decide).
CLAIMS: tuple[str, ...] = ("P31", "P17", "P625", "P571")

#: ``wbgetentities`` answers at most 50 ids per request for a client without the bot right.
BATCH_MAX = 50

_QID_RE = re.compile(r"^Q[1-9][0-9]*$")


def is_qid(value: object) -> bool:
    """True for an id exactly as Wikidata writes one (``Q64``), never a repaired guess."""
    return isinstance(value, str) and bool(_QID_RE.match(value))


def entities_url(qids: list[str], langs: tuple[str, ...] = LANGS) -> str:
    """One ``wbgetentities`` request for up to :data:`BATCH_MAX` items.

    ``props=labels|descriptions|claims`` in the twelve UI languages. ``claims`` cannot be
    narrowed server-side to four properties, so the parser drops the rest at the door.
    """
    ids = [q for q in qids if is_qid(q)]
    if not ids:
        raise ValueError("no valid QID to ask for")
    if len(ids) > BATCH_MAX:
        raise ValueError(f"wbgetentities takes at most {BATCH_MAX} ids per request")
    qs = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": "labels|descriptions|claims",
            "languages": "|".join(langs),
            "format": "json",
        }
    )
    return f"{API_ENDPOINT}?{qs}"


@dataclass
class ParsedItem:
    """One item as the cache stores it. ``status`` is Wikidata's own answer."""

    qid: str
    status: str  # "ok" | "missing"
    resolved_qid: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    claims: dict[str, list] = field(default_factory=dict)
    lastrevid: int | None = None

    def json_fields(self) -> dict:
        """The three JSON columns, serialised the one way the cache writes them."""
        return {
            "labels_json": json.dumps(self.labels, ensure_ascii=False, sort_keys=True),
            "descriptions_json": json.dumps(self.descriptions, ensure_ascii=False, sort_keys=True),
            "claims_json": json.dumps(self.claims, ensure_ascii=False, sort_keys=True),
        }


def _lang_values(block: object, langs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(block, dict):
        return out
    for lang in langs:
        v = (block.get(lang) or {}).get("value") if isinstance(block.get(lang), dict) else None
        if isinstance(v, str) and v.strip():
            out[lang] = v
    return out


def _claim_value(prop: str, snak: dict):
    """The one value a kept claim stores, in the shape a reader can use without Wikidata."""
    dv = (snak.get("datavalue") or {}).get("value")
    if dv is None:
        return None
    if prop in ("P31", "P17"):
        qid = dv.get("id") if isinstance(dv, dict) else None
        return qid if is_qid(qid) else None
    if prop == "P625":
        if not isinstance(dv, dict):
            return None
        lat, lon = dv.get("latitude"), dv.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return None
        # A coordinate on another globe (the Moon, Mars) is not a place on this map.
        globe = str(dv.get("globe") or "")
        if globe and not globe.endswith("/Q2"):
            return None
        return {"lat": float(lat), "lon": float(lon)}
    if prop == "P571":
        if not isinstance(dv, dict) or not isinstance(dv.get("time"), str):
            return None
        # Kept as Wikidata writes it, with its precision: "+1900-00-00T00:00:00Z" at year
        # precision is a year, and turning it into a date would invent a month and a day.
        return {"time": dv["time"], "precision": dv.get("precision")}
    return None


def _claims(entity: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    claims = entity.get("claims") or {}
    if not isinstance(claims, dict):
        return out
    for prop in CLAIMS:
        vals = []
        for c in claims.get(prop) or []:
            if not isinstance(c, dict) or c.get("rank") == "deprecated":
                continue
            v = _claim_value(prop, c.get("mainsnak") or {})
            if v is not None and v not in vals:
                vals.append(v)
        if vals:
            out[prop] = vals
    return out


def parse_entities(payload: dict, asked: list[str], langs: tuple[str, ...] = LANGS) -> list[ParsedItem]:
    """Every ASKED id, parsed; an id the answer does not mention is simply not returned.

    Wikidata keys the answer by the id it resolved to, and a merged item comes back under
    its target with ``redirects`` naming the pair; both shapes are handled so the cache row
    is keyed on the id the corpus asked for.
    """
    entities = (payload or {}).get("entities") or {}
    if not isinstance(entities, dict):
        return []
    out: list[ParsedItem] = []
    for qid in asked:
        ent = entities.get(qid)
        resolved = None
        if not isinstance(ent, dict):
            # A redirect: find the entity whose `redirects.from` is this id.
            for key, cand in entities.items():
                red = cand.get("redirects") if isinstance(cand, dict) else None
                if isinstance(red, dict) and red.get("from") == qid:
                    ent, resolved = cand, key
                    break
        if not isinstance(ent, dict):
            continue
        if "missing" in ent:
            out.append(ParsedItem(qid=qid, status="missing"))
            continue
        rev = ent.get("lastrevid")
        out.append(
            ParsedItem(
                qid=qid,
                status="ok",
                resolved_qid=resolved if resolved and resolved != qid else None,
                labels=_lang_values(ent.get("labels"), langs),
                descriptions=_lang_values(ent.get("descriptions"), langs),
                claims=_claims(ent),
                lastrevid=int(rev) if isinstance(rev, int) else None,
            )
        )
    return out


def batches(qids: list[str], size: int = BATCH_MAX) -> list[list[str]]:
    """``qids`` in request-sized batches, order kept, duplicates and invalid ids dropped."""
    seen: set[str] = set()
    clean: list[str] = []
    for q in qids:
        if is_qid(q) and q not in seen:
            seen.add(q)
            clean.append(q)
    return [clean[i:i + size] for i in range(0, len(clean), size)]
