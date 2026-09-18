"""Q705's per-page metadata: the vocabulary, and the rule that absence stays absent.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q705 = a confirms the sheet's proposed list verbatim:

    ``pageid`` - QID (``pageprops.wikibase_item``) - sitelink count - categories -
    length - revision count - protection level - last editor class (bot / anonymous
    / registered) - infobox fields (key/value) - coordinates (``prop=coordinates``,
    GeoData) - image count - external-link count - citation-needed count - page
    assessment class where the edition has it (``prop=pageassessments``) - creation
    date - the edition.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE. A field the wiki did not answer is
ABSENT — no row in ``versioned_entity_facts`` — and a field the wiki answered with a
zero is a zero. :func:`facts_from_page` never writes a key it did not read, and never
substitutes a default for a missing one. The recorded failure this guards against is
ordinary and expensive: an aggregation keyed by a ``.get(id, [])`` cannot tell "no
evidence" from "examined and found clean", and a gate built on it promotes on zero
verification. Here the difference survives all the way into storage.

``pageid`` AND ``edition`` ARE DELIBERATELY NOT FACTS. They are the entity's
IDENTITY (``external_id``) and its ``language`` column — storing them again as facts
would create a second spelling of the key, which is how two rows come to mean one
page. Q705 lists them because it is describing what the lane knows about a page, not
prescribing a table.

NOTHING HERE TOUCHES THE NETWORK. It is handed an Action API response and returns a
mapping. The request that produced the response is :mod:`src.wiki.hot`'s.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: The fact names this lane writes. A CLOSED vocabulary: a name not in here is
#: refused on write, because a typo'd fact name is a fact nothing will ever read
#: again and nothing would ever report missing.
FACT_NAMES: tuple[str, ...] = (
    "qid",
    "sitelink_count",
    "categories",
    "length_bytes",
    "revision_count",
    "protection",
    "last_editor_class",
    "infobox",
    "coordinates",
    "image_count",
    "external_link_count",
    "citation_needed_count",
    "assessment_class",
    "created_at",
)

#: ``{{...}}`` opener, used only to find where an infobox template starts.
_INFOBOX_OPEN = re.compile(r"\{\{\s*([Ii]nfobox[^\n|}]*)", re.M)

#: The maintenance templates whose COUNT Q705 asks for. Matched case-insensitively
#: on the template name only, so prose mentioning the phrase is not counted.
_CITATION_NEEDED = re.compile(
    r"\{\{\s*(citation needed|cn|fact|refnec|référence nécessaire|quelle)\b", re.I
)


class UnknownFactError(ValueError):
    """A fact name outside :data:`FACT_NAMES`."""


def encode(value: Any) -> str:
    """JSON for storage. Separators are compact for byte-stable comparison."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode(blob: str) -> Any:
    """Inverse of :func:`encode`. Raises on a value this lane did not write."""
    return json.loads(blob)


def editor_class(row: dict) -> str | None:
    """bot / anonymous / registered, or ``None`` when the response says nothing.

    ``None`` rather than ``"registered"`` for an absent flag: "we were not told" and
    "a logged-in human" are different facts, and defaulting to the commonest one
    would make a gap look like a measurement.
    """
    if "anon" not in row and "bot" not in row and "user" not in row:
        return None
    if row.get("bot"):
        return "bot"
    if row.get("anon"):
        return "anonymous"
    return "registered"


def count_citation_needed(wikitext: str) -> int:
    """How many citation-needed templates the wikitext carries.

    A real count over the source of truth (Q704 = a keeps the wikitext precisely so
    template-level facts stay extractable). Zero is a MEASUREMENT here — the text was
    read and none were found — which is why the caller may store it.
    """
    return len(_CITATION_NEEDED.findall(wikitext or ""))


def infobox_fields(wikitext: str, *, max_fields: int = 200) -> dict[str, str] | None:
    """The first infobox's ``key = value`` pairs, or ``None`` when there is no infobox.

    ``None``, never ``{}``: an article with no infobox and an infobox we failed to
    parse must not read the same. ``max_fields`` bounds a pathological page rather
    than the ordinary one — and when it bites, the CAP is what stops, never a
    reported number (the anti-capping rule), so the caller sees the truncation as a
    shorter dict and the ``infobox_truncated`` fact records that it happened.
    """
    match = _INFOBOX_OPEN.search(wikitext or "")
    if match is None:
        return None
    body = _balanced_template(wikitext, match.start())
    if body is None:
        return None
    fields: dict[str, str] = {}
    for part in _split_top_level(body):
        key, sep, value = part.partition("=")
        if not sep:
            continue
        name = key.strip()
        if not name or name in fields:
            continue
        fields[name] = value.strip()
        if len(fields) >= max_fields:
            break
    return fields


def facts_from_page(page: dict, *, wikitext: str | None = None) -> dict[str, Any]:
    """Q705's fields from one Action API page object. Absent stays absent.

    ``page`` is one member of ``query.pages`` with ``prop=info|pageprops|categories|
    coordinates|images|extlinks|pageassessments`` requested. Every read below is
    guarded by MEMBERSHIP, not by a ``.get`` with a default, so a prop the edition
    does not support produces no row at all.
    """
    out: dict[str, Any] = {}

    props = page.get("pageprops")
    if isinstance(props, dict) and "wikibase_item" in props:
        out["qid"] = props["wikibase_item"]

    if isinstance(props, dict) and "wikibase-shortdesc" in props:
        # Not a Q705 field; deliberately NOT stored. Left as a comment so the next
        # reader knows it was seen and declined rather than missed.
        pass

    if "length" in page:
        out["length_bytes"] = page["length"]
    if "revision_count" in page:
        # The Action API does not serve a revision count with ``prop=info``; a caller
        # that has one (from a separate count query) may pass it through. Present
        # only when it was genuinely supplied, which is the whole rule of this module.
        out["revision_count"] = page["revision_count"]

    if "protection" in page and isinstance(page["protection"], list):
        # Stored as the source's own list of ``{type, level, expiry}`` objects. A
        # flattened "semi/full" string would be this app's interpretation of somebody
        # else's policy vocabulary, which differs per edition.
        out["protection"] = page["protection"]

    if "categories" in page and isinstance(page["categories"], list):
        names = [c.get("title") for c in page["categories"] if isinstance(c, dict)]
        out["categories"] = [n for n in names if isinstance(n, str)]

    coords = page.get("coordinates")
    if isinstance(coords, list) and coords:
        first = coords[0]
        if isinstance(first, dict) and "lat" in first and "lon" in first:
            # lat/lon only. The globe and precision the API may add are not Q705's
            # and would be stored unread.
            out["coordinates"] = {"lat": first["lat"], "lon": first["lon"]}

    if "images" in page and isinstance(page["images"], list):
        out["image_count"] = len(page["images"])
    if "extlinks" in page and isinstance(page["extlinks"], list):
        out["external_link_count"] = len(page["extlinks"])

    assessments = page.get("pageassessments")
    if isinstance(assessments, dict) and assessments:
        named: set[str] = set()
        for entry in assessments.values():
            if not isinstance(entry, dict):
                continue
            value = entry.get("class")
            if isinstance(value, str) and value:
                named.add(value)
        classes = sorted(named)
        if classes:
            out["assessment_class"] = classes

    sitelinks = page.get("sitelink_count")
    if isinstance(sitelinks, int):
        out["sitelink_count"] = sitelinks

    revisions = page.get("revisions")
    if isinstance(revisions, list) and revisions:
        newest = revisions[0]
        if isinstance(newest, dict):
            klass = editor_class(newest)
            if klass is not None:
                out["last_editor_class"] = klass

    if "created_at" in page:
        out["created_at"] = page["created_at"]

    if wikitext is not None:
        out["citation_needed_count"] = count_citation_needed(wikitext)
        box = infobox_fields(wikitext)
        if box is not None:
            out["infobox"] = box

    return out


def store_facts(session, entity_id: int, facts: dict[str, Any], *, revision_ref: str | None = None) -> int:
    """Upsert facts for one entity. Returns how many rows were written.

    A fact NOT in ``facts`` is left alone rather than deleted: this function is
    called with whatever one response could answer, and a later, narrower response
    must not erase what a broader one learned. Deleting a fact is a separate,
    deliberate act with its own call site.
    """
    from src.versioned.models import VersionedEntityFact

    written = 0
    for name, value in facts.items():
        if name not in FACT_NAMES:
            raise UnknownFactError(
                f"{name!r} is not a Q705 fact; known names are {', '.join(FACT_NAMES)}"
            )
        blob = encode(value)
        row = (
            session.query(VersionedEntityFact)
            .filter(
                VersionedEntityFact.entity_id == entity_id,
                VersionedEntityFact.name == name,
            )
            .one_or_none()
        )
        if row is None:
            session.add(
                VersionedEntityFact(
                    entity_id=entity_id,
                    name=name,
                    value_json=blob,
                    revision_ref=revision_ref,
                )
            )
            written += 1
        elif row.value_json != blob:
            row.value_json = blob
            row.revision_ref = revision_ref
            written += 1
    session.flush()
    return written


def read_facts(session, entity_id: int) -> dict[str, Any]:
    """Every stored fact for one entity, decoded. An absent fact has no key."""
    from src.versioned.models import VersionedEntityFact

    rows = (
        session.query(VersionedEntityFact)
        .filter(VersionedEntityFact.entity_id == entity_id)
        .all()
    )
    return {r.name: decode(r.value_json) for r in rows}


# --------------------------------------------------------------------------- #
# Wikitext helpers. Small, pure, and individually testable.
# --------------------------------------------------------------------------- #
def _balanced_template(text: str, start: int) -> str | None:
    """The inside of the ``{{...}}`` beginning at ``start``, or ``None`` if unclosed.

    Brace-counting rather than a regex because infoboxes nest templates freely, and a
    non-greedy regex stops at the first inner ``}}`` — producing a plausible-looking
    truncated field list rather than a visible failure.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            if depth == 0:
                return text[start + 2 : i]
            i += 2
            continue
        i += 1
    return None


def _split_top_level(body: str) -> list[str]:
    """Split an infobox body on ``|`` at nesting depth 0 only.

    A ``|`` inside a nested template or a wikilink belongs to that construct; naive
    splitting on every pipe shreds a value into fragments that still parse as
    ``key = value`` pairs, so the damage is silent.
    """
    parts: list[str] = []
    depth_brace = 0
    depth_bracket = 0
    current: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        pair = body[i : i + 2]
        if pair == "{{":
            depth_brace += 1
            current.append(pair)
            i += 2
            continue
        if pair == "}}":
            depth_brace = max(0, depth_brace - 1)
            current.append(pair)
            i += 2
            continue
        if pair == "[[":
            depth_bracket += 1
            current.append(pair)
            i += 2
            continue
        if pair == "]]":
            depth_bracket = max(0, depth_bracket - 1)
            current.append(pair)
            i += 2
            continue
        ch = body[i]
        if ch == "|" and depth_brace == 0 and depth_bracket == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    parts.append("".join(current))
    # The first part is the template NAME, never a field.
    return parts[1:]
