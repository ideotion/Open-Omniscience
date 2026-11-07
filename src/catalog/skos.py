"""SKOS thesaurus reader -- EuroVoc, the UNESCO Thesaurus, AGROVOC, IPTC Media Topics (C-L3, Q1146).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

OFFLINE and pure: :func:`parse_rdfxml` reads a SKOS RDF/XML file the operator downloaded and
returns a compact, JSON-able document (:func:`build_artifact`); nothing here opens a socket.
The thesaurus files are somebody else's XML, so they go through ``defusedxml`` (a core
dependency): an entity-expansion bomb must fail as a parse error, never as an out-of-memory.
``iterparse`` is called with ``forbid_entities=True`` and ``forbid_external=True`` spelled out (not left to
the library's defaults): a DOCTYPE that points at an external URL is REFUSED, never dereferenced, so the
namespace URIs below are identifiers this module never fetches. Pinned by
``tests/test_skos_topics.py::test_external_doctype_is_refused_without_a_network_call``.

NEGATIVE SPACE (S06-02 S4 acceptance): an empty scheme and a concept with no label are
reported as GAPS, never given a label. A concept that carries no ``prefLabel``/``altLabel``
in any language is dropped from ``concepts`` and listed in ``gaps``; a file with no concept
at all yields ``gaps`` containing ``empty_scheme``. Nothing is invented to fill either.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, BinaryIO

from defusedxml import ElementTree as SafeET

SKOS = "{http://www.w3.org/2004/02/skos/core#}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

SCHEMES = ("eurovoc", "unesco-thesaurus", "agrovoc", "iptc-media-topics")


class SkosError(ValueError):
    """The file is not parseable SKOS RDF/XML (named, never a silent empty result)."""


def _text(el: Any) -> str:
    return " ".join("".join(el.itertext()).split())


def parse_rdfxml(source: str | Path | BinaryIO) -> dict[str, Any]:
    """Parse SKOS RDF/XML into ``{"concepts": {uri: {...}}, "gaps": [...], "n_seen": int}``.

    Each concept: ``{"pref": {lang: label}, "alt": {lang: [labels]}, "broader": [uri]}``.
    Streaming (``iterparse``): each top-level concept is cleared once read. Elements that are not
    concepts (a ConceptScheme, SKOS-XL label resources) are not cleared and stay in memory; a SKOS-XL-only
    file (labels as ``skosxl:Label``) is not read and every concept in it is reported as a gap.
    """
    concepts: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, str]] = []
    n_seen = 0
    langs: dict[int, str] = {}  # element id -> effective xml:lang (inherited from its ancestors)
    stack: list[str] = []
    depth = 0
    try:
        for event, el in SafeET.iterparse(
            source, events=("start", "end"), forbid_dtd=False, forbid_entities=True, forbid_external=True,
        ):
            if event == "start":
                own = el.get(XML_LANG)
                stack.append(own if own is not None else (stack[-1] if stack else ""))
                langs[id(el)] = stack[-1]
                depth += 1
                continue
            depth -= 1
            stack.pop()
            if el.tag != f"{SKOS}Concept" and not (
                el.tag == f"{RDF}Description"
                and any(c.tag == f"{RDF}type" and c.get(f"{RDF}resource", "").endswith("skos/core#Concept")
                        for c in el)
            ):
                continue
            n_seen += 1
            uri = el.get(f"{RDF}about") or ""
            if not uri:
                gaps.append({"kind": "concept_without_id", "detail": "a concept carries no rdf:about"})
            else:
                pref: dict[str, str] = {}
                alt: dict[str, list[str]] = {}
                broader: list[str] = []
                for c in el:
                    lang = langs.get(id(c), "").split("-")[0].lower()
                    if c.tag == f"{SKOS}prefLabel":
                        label = _text(c)
                        if label and lang and lang not in pref:
                            pref[lang] = label
                        elif label and not lang:
                            gaps.append({"kind": "label_without_language", "detail": uri})
                    elif c.tag == f"{SKOS}altLabel":
                        label = _text(c)
                        if label and lang:
                            alt.setdefault(lang, []).append(label)
                        elif label:
                            gaps.append({"kind": "label_without_language", "detail": uri})
                    elif c.tag == f"{SKOS}broader":
                        ref = c.get(f"{RDF}resource")
                        if not ref:  # the nested form: <skos:broader><skos:Concept rdf:about=.../></skos:broader>
                            ref = next((g.get(f"{RDF}about") for g in c if g.get(f"{RDF}about")), None)
                        if ref:
                            broader.append(ref)
                if not pref and not alt:
                    gaps.append({"kind": "concept_without_label", "detail": uri})
                else:
                    concepts[uri] = {"pref": pref, "alt": alt, "broader": broader}
            if depth <= 1:  # a top-level concept is finished; a nested one is still its parent's to read
                el.clear()
    except SkosError:
        raise
    except Exception as exc:  # defusedxml/ElementTree errors: named, not swallowed
        raise SkosError(f"not parseable SKOS RDF/XML ({type(exc).__name__})") from None
    if not concepts:
        gaps.append({"kind": "empty_scheme", "detail": f"{n_seen} concept(s) seen, none with a label"})
    return {"concepts": concepts, "gaps": gaps, "n_seen": n_seen}


def build_artifact(
    scheme: str, parsed: dict[str, Any], *, vintage: str, license: str, upstream: str,
    languages: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """The JSON document bundled under ``src/catalog/data/skos/<scheme>.json``.

    ``languages`` (when given) keeps only those languages' labels; a concept left with no
    label by the filter becomes a gap, not an empty row.
    """
    if scheme not in SCHEMES:
        raise SkosError(f"unknown scheme {scheme!r}; known: {', '.join(SCHEMES)}")
    gaps = list(parsed.get("gaps", []))
    concepts: dict[str, Any] = {}
    for uri, c in parsed["concepts"].items():
        if languages is not None:
            c = {
                "pref": {k: v for k, v in c["pref"].items() if k in languages},
                "alt": {k: v for k, v in c["alt"].items() if k in languages},
                "broader": c["broader"],
            }
            if not c["pref"] and not c["alt"]:
                gaps.append({"kind": "concept_without_label_in_languages", "detail": uri})
                continue
        concepts[uri] = c
    if not concepts and not any(g["kind"] == "empty_scheme" for g in gaps):
        gaps.append({"kind": "empty_scheme", "detail": "no concept left after the language filter"})
    return {
        "scheme": scheme, "vintage": vintage, "license": license, "upstream": upstream,
        "languages": sorted(languages) if languages else sorted(
            {k for c in concepts.values() for k in (*c["pref"], *c["alt"])}),
        "n_concepts": len(concepts), "concepts": concepts, "gaps": gaps,
    }


def load_artifact(path: str | Path) -> dict[str, Any]:
    """Read a bundled artifact; a missing file is reported by the caller, a malformed one is named."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "concepts" not in data or "scheme" not in data:
        raise SkosError(f"{path}: not a SKOS artifact (needs 'scheme' and 'concepts')")
    return data
