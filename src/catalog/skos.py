"""SKOS thesaurus reader -- EuroVoc, the UNESCO Thesaurus, AGROVOC, IPTC Media Topics (C-L3, Q1146).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

OFFLINE and pure: :func:`parse_rdfxml` reads a SKOS RDF/XML file the operator downloaded and
returns a compact, JSON-able document (:func:`build_artifact`); nothing here opens a socket.
The thesaurus files are somebody else's XML, so they go through ``defusedxml`` (a core
dependency): an entity-expansion bomb must fail as a parse error, never as an out-of-memory.

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
    Streaming (``iterparse``) so a 100 MB thesaurus is not held as a tree.
    """
    concepts: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, str]] = []
    n_seen = 0
    try:
        for _event, el in SafeET.iterparse(source, events=("end",)):
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
                el.clear()
                continue
            pref: dict[str, str] = {}
            alt: dict[str, list[str]] = {}
            broader: list[str] = []
            for c in el:
                lang = (c.get(XML_LANG) or "").split("-")[0].lower()
                if c.tag == f"{SKOS}prefLabel":
                    label = _text(c)
                    if label and lang and lang not in pref:
                        pref[lang] = label
                elif c.tag == f"{SKOS}altLabel":
                    label = _text(c)
                    if label and lang:
                        alt.setdefault(lang, []).append(label)
                elif c.tag == f"{SKOS}broader":
                    ref = c.get(f"{RDF}resource")
                    if ref:
                        broader.append(ref)
            if not pref and not alt:
                gaps.append({"kind": "concept_without_label", "detail": uri})
            else:
                concepts[uri] = {"pref": pref, "alt": alt, "broader": broader}
            el.clear()
    except SkosError:
        raise
    except Exception as exc:  # defusedxml/ElementTree errors: named, not swallowed
        raise SkosError(f"not parseable SKOS RDF/XML: {type(exc).__name__}: {exc}") from exc
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
