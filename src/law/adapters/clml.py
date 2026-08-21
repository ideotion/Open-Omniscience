"""
legislation.gov.uk CLML (Crown Legislation Markup Language) — read, never reconstructed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Adapter #1 of the law-vertical brief's S6, ruled adapter-first (2026-08-07, ruling 34a).
The parsing contract, the date discipline and this module's honest verification status
are in :mod:`src.law.adapters` — read that first.

WHAT THIS FILE ASSUMES, AND WHY IT SURVIVES BEING WRONG. CLML nests a legislative
document roughly as ``Legislation > Primary/Secondary > Body > Part > Chapter > Pblock >
P1group > P1 > P1para > Text``, with ``Pnumber`` carrying a provision's number and
``Title`` its heading, and with the publisher's own metadata in a sibling ``Metadata``
subtree. This adapter was written to that shape but does not depend on it holding:

* it walks by **local name**, so namespaces may be revised freely;
* containers, provisions and metadata are recognised by NAME SETS, so an unfamiliar
  intermediate element is simply walked through rather than terminating the walk;
* text inside an element it does not model is still collected, so an unknown tag costs
  structural detail, never text;
* it measures recovered text against the body's own total and refuses below
  :data:`~src.law.adapters.TEXT_RECOVERY_FLOOR`.

That last check is the load-bearing one. Every assumption above could be wrong and the
adapter would still refuse rather than hand back a fraction of a statute as if it were
the whole thing.

SCALING, measured rather than assumed (2026-08-20): parse time is LINEAR in document
size -- 500/1000/2000/4000 sections took 0.026/0.049/0.104/0.198 s, i.e. ~2.0x per
doubling, with a 4000-section document (1.2 MB) parsed in 0.2 s. Worth stating because
the metadata read was quadratic in a first draft (a real Act carries hundreds of `Title`
elements, and asking "is this one in the metadata?" by re-walking the tree per lookup is
the shape that turned a 412 KB article into a multi-second stall elsewhere here). There
is deliberately NO timing assertion guarding this: a threshold over wall time is noise on
a shared runner, and the structural fix -- collecting the metadata element set once -- is
what the reader should check if this is ever revisited.
"""

from __future__ import annotations

import re

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as _safe_fromstring

from src.law.adapters import TEXT_RECOVERY_FLOOR, AdapterRefusal, ParsedLaw, Provision

FORMAT = "clml"

# Roots this adapter will read. Anything else is REFUSED -- a parser that accepts an
# unrecognised root will happily "read" an error page, a search result or an HTML
# document and return a plausible, empty Act.
_ROOTS = {"legislation"}

# The document's own metadata subtree: read for dates/title, never emitted as law text.
_METADATA = {"metadata", "primarymetadata", "secondarymetadata", "eumetadata"}

# Structural containers. Their Title (if any) joins the path of everything beneath them.
_CONTAINERS = {
    "part",
    "chapter",
    "pblock",
    "pgroup",
    "group",
    "schedule",
    "schedules",
    "schedulebody",
    "crossheading",
}

# Provision elements: the numbered units a lawyer cites. CLML numbers them P1..P7 by
# depth; only the OUTERMOST is emitted, so a section is one provision carrying its
# subsections rather than a flat spray of fragments. A section is also the unit a
# per-section diff should address: splitting subsections out would report an amendment
# to s.2(2) as a change to a different provision than s.2.
#
# A nested subsection's own number therefore stays INSIDE its section's text (it reads
# as a bare "2" between sentences). That is what the document says; dropping it would
# lose the numbering a citation depends on, and re-formatting it as "(2)" would be this
# adapter inventing presentation the publisher did not write.
_PROVISION_RE = re.compile(r"^p[1-7]$")
_PROVISION_GROUP_RE = re.compile(r"^p[1-7]group$")

# Elements whose text is the provision's number or heading rather than its prose. They
# are read for those fields and then EXCLUDED from the body text, or every section would
# begin by repeating its own number and title.
_NUMBER = {"pnumber", "number"}
_HEADING = {"title", "titleblock"}

# Structural wrappers that carry no meaning of their own -- walked through silently so
# they never inflate the unknown-element report.
_TRANSPARENT = {
    "primary",
    "secondary",
    "eubody",
    "body",
    "contents",
    "p1para",
    "p2para",
    "p3para",
    "p4para",
    "p5para",
    "p6para",
    "p7para",
    "text",
    "para",
    "content",
    "citation",
    "reference",
    "emphasis",
    "strong",
    "inline",
    "abbreviation",
    "addition",
    "repeal",
    "substitution",
    "span",
}

# Date fields, by the local name that states them. There is deliberately NO fallback
# between these: see the date discipline in the package docstring.
_ENACTED = {"enactmentdate", "madedate", "dateenacted"}
_VALID = {"valid", "validdate", "pointintime", "dct:valid"}

_WS_RE = re.compile(r"\s+")


def _local(tag: str) -> str:
    """Local name of a possibly namespaced tag, lowercased.

    ``{http://…/legislation}Part`` -> ``part``. Matching on this is what makes a
    namespace revision a non-event.
    """
    if not isinstance(tag, str):  # a comment/PI node's tag is a callable, not a string
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _all_text(el) -> str:
    """Every text node under ``el``, in document order."""
    return _norm("".join(el.itertext()))


def _text_excluding(el, exclude: set) -> str:
    """Text under ``el`` minus the subtrees in ``exclude`` (compared by identity).

    Used to keep a provision's number and heading out of its own body text.
    """
    parts: list[str] = []

    def walk(node) -> None:
        if any(node is x for x in exclude):
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    return _norm("".join(parts))


def _first_child_named(el, names: set):
    for child in el:
        if _local(child.tag) in names:
            return child
    return None


def _date_of(el) -> str | None:
    """A date as the document states it — attribute first, then element text.

    Returns ``None`` when the document does not state one. Never today's date, never
    another field's date.
    """
    for attr in ("Date", "date", "Value", "value"):
        v = el.get(attr)
        if v:
            return v.strip()
    txt = _norm(el.text or "")
    return txt or None


def _metadata_elements(root) -> list:
    """Every element inside a metadata subtree, collected ONCE.

    Collected once rather than re-derived per lookup: a real Act carries hundreds of
    ``Title`` elements, and asking "is this one in the metadata?" by re-walking the tree
    each time is quadratic in document size -- the shape that turned a 412 KB article
    into a multi-second stall elsewhere in this codebase.
    """
    out: list = []
    for el in root.iter():
        if _local(el.tag) in _METADATA:
            out.extend(el.iter())
    return out


def _read_metadata(root) -> dict:
    """Title, dates and publisher identifiers, each only where the metadata states it.

    Read from the metadata subtree ONLY. A ``Number`` or ``Year`` inside the body is a
    provision's own number or a year mentioned in the law -- reading those as the
    document's identifiers is how a statute acquires a publication year it never had.
    """
    out: dict[str, str | None] = {
        "title": None,
        "enacted_on": None,
        "valid_on": None,
        "document_number": None,
        "year": None,
    }
    for el in _metadata_elements(root):
        name = _local(el.tag)
        if name in _ENACTED and out["enacted_on"] is None:
            out["enacted_on"] = _date_of(el)
        elif name in _VALID and out["valid_on"] is None:
            out["valid_on"] = _date_of(el)
        elif name in _HEADING and out["title"] is None:
            out["title"] = _norm(_all_text(el)) or None
        elif name == "number" and out["document_number"] is None:
            out["document_number"] = _date_of(el)
        elif name == "year" and out["year"] is None:
            out["year"] = _date_of(el)
    return out


def _find_body(root):
    """The subtree holding the law itself, or the root when none is declared.

    Falling back to the root is safe because the metadata subtrees are skipped by the
    walk regardless — and it means a document that omits an explicit body still parses
    rather than reading as empty.
    """
    for el in root.iter():
        if _local(el.tag) == "body":
            return el
    return root


def parse_clml(data: bytes | str, *, retrieved_on: str | None = None) -> ParsedLaw:
    """Parse a CLML document. Raises :class:`AdapterRefusal` rather than guessing.

    ``retrieved_on`` is the caller's capture date. The document cannot know when we
    fetched it, so this adapter never invents it — and never lets it stand in for a
    date the document itself was supposed to state.
    """
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdapterRefusal("not utf-8 xml", detail=str(exc)) from exc

    try:
        root = _safe_fromstring(data)
    except DefusedXmlException as exc:  # entity expansion / external entity
        raise AdapterRefusal("unsafe xml refused", detail=type(exc).__name__) from exc
    except Exception as exc:  # noqa: BLE001 - any malformed input is one refusal reason
        raise AdapterRefusal("not well-formed xml", detail=str(exc)[:200]) from exc

    root_name = _local(root.tag)
    if root_name not in _ROOTS:
        # An HTML error page, a search result, a redirect notice -- all parse as "some
        # XML". Refusing here is what stops one being stored as an Act with no text.
        raise AdapterRefusal("not a CLML document", detail=f"root element <{root_name}>")

    meta = _read_metadata(root)
    body = _find_body(root)

    provisions: list[Provision] = []
    unknown: dict[str, int] = {}
    captured: list[str] = []

    def walk(el, path: tuple[str, ...]) -> None:
        name = _local(el.tag)
        if name in _METADATA:
            return  # publisher metadata is not law text
        if _PROVISION_RE.match(name):
            provisions.append(_provision(el, path, name))
            captured.append(_all_text(el))
            return  # subsections belong to their section, not beside it
        if name in _CONTAINERS or _PROVISION_GROUP_RE.match(name):
            heading_el = _first_child_named(el, _HEADING)
            number_el = _first_child_named(el, _NUMBER)
            label = " ".join(
                x
                for x in (
                    _norm(_all_text(number_el)) if number_el is not None else "",
                    _norm(_all_text(heading_el)) if heading_el is not None else "",
                )
                if x
            )
            # A P1group wraps exactly one P1: its heading belongs to that provision,
            # not to a container level above it, or every section gains a phantom parent.
            if _PROVISION_GROUP_RE.match(name):
                inner = [c for c in el if _PROVISION_RE.match(_local(c.tag))]
                if len(inner) == 1:
                    provisions.append(
                        _provision(
                            inner[0],
                            path,
                            _local(inner[0].tag),
                            heading=_norm(_all_text(heading_el)) if heading_el is not None else None,
                        )
                    )
                    captured.append(_all_text(el))
                    return
            if label:
                # Recovered into the path rather than into a provision, but recovered:
                # not counting it would make a complete parse read as lossy.
                captured.append(label)
            child_path = (*path, label) if label else path
            for child in el:
                walk(child, child_path)
            return
        if name not in _TRANSPARENT and name not in _HEADING and name not in _NUMBER:
            unknown[name] = unknown.get(name, 0) + 1
        for child in el:
            walk(child, path)

    for child in body:
        walk(child, ())

    body_text = _all_text(body) if body is not root else _body_text_excluding_metadata(root)
    body_chars = len(body_text)
    captured_chars = len(_norm(" ".join(captured)))
    recovered = (captured_chars / body_chars) if body_chars else 0.0
    # A parser can capture MORE characters than the body holds (a heading read once as a
    # container label and again inside its provision). That is not >100% recovery of the
    # document; cap it, because a number above 1.0 would read as evidence of quality.
    recovered = min(1.0, recovered)

    if not provisions:
        raise AdapterRefusal(
            "no provisions found",
            detail=f"{body_chars} chars of body text, {len(unknown)} unmodelled element kinds",
        )
    if recovered < TEXT_RECOVERY_FLOOR:
        raise AdapterRefusal(
            "too little of the document was recovered",
            detail=(
                f"{recovered:.0%} of {body_chars} body chars in {len(provisions)} provisions "
                f"(floor {TEXT_RECOVERY_FLOOR:.0%})"
            ),
        )

    return ParsedLaw(
        title=meta["title"],
        provisions=provisions,
        enacted_on=meta["enacted_on"],
        valid_on=meta["valid_on"],
        retrieved_on=retrieved_on,
        document_number=meta["document_number"],
        year=meta["year"],
        unknown_elements=unknown,
        text_recovered_pct=recovered,
        body_chars=body_chars,
        format=FORMAT,
    )


def _body_text_excluding_metadata(root) -> str:
    """Root text minus every metadata subtree — the denominator when no <Body> exists."""
    meta_els = [el for el in root.iter() if _local(el.tag) in _METADATA]
    return _text_excluding(root, set(meta_els)) if meta_els else _all_text(root)


def _provision(el, path: tuple[str, ...], element: str, *, heading: str | None = None) -> Provision:
    number_el = _first_child_named(el, _NUMBER)
    heading_el = _first_child_named(el, _HEADING)
    exclude = {x for x in (number_el, heading_el) if x is not None}
    return Provision(
        number=_norm(_all_text(number_el)) if number_el is not None else None,
        heading=(heading or (_norm(_all_text(heading_el)) if heading_el is not None else None)),
        text=_text_excluding(el, exclude),
        path=path,
        element=element,
    )
