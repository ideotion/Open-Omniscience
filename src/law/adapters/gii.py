"""
gesetze-im-internet.de XML (the ``gii-norm`` format) — read, never reconstructed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Adapter #2, in the order Q925 = a ruled on 2026-09-29: legislation.gov.uk (CLML) ->
**gesetze-im-internet** -> e-Gov -> EUR-Lex -> LEGI. The parsing contract, the date
discipline and the refusal rules are :mod:`src.law.adapters`' — read that first; this
module only says what is particular to Germany's federal portal.

THE SHAPE, AND WHERE IT WAS READ FROM. The portal publishes every federal act as one
``/<abbreviation>/xml.zip`` holding one XML file (plus image attachments for annexes),
and lists them all in ``/gii-toc.xml``. The XML is a flat sequence under ``<dokumente>``:

* the FIRST ``<norm>`` carries the act's metadata — ``jurabk`` (its abbreviation),
  ``langue`` (its full title), ``ausfertigung-datum`` (the day it was signed into law),
  ``fundstelle`` (where the gazette printed it), ``standangabe`` (what last amended it);
* a ``<norm>`` with ``gliederungseinheit`` is a STRUCTURAL heading (Teil 1, Kapitel 2,
  Abschnitt I.), its depth written in ``gliederungskennzahl`` as three digits per level
  (``010`` is a top level, ``010020`` the second unit beneath it);
* a ``<norm>`` with ``enbez`` is a PROVISION (``§ 1``, ``Art 16a``, ``Präambel``), its
  heading in ``titel`` and its text in ``textdaten/text/Content``.

The host itself is egress-blocked from the build sandbox (the proxy answers 403 to
CONNECT). The two fixtures under ``tests/fixtures/law/gii/`` are therefore NOT fetched
from it: they are byte-for-byte excerpts of the portal's own files as archived by an
independent daily mirror, which is the strongest evidence this tree can hold about the
real shape short of a live read — and a live read is what the release run's law probe
does on the operator's machine. ``tests/fixtures/law/PROVENANCE.md`` says exactly which
files, from where, and when.

WHAT IS DELIBERATELY LEFT OUT OF THE TEXT, AND SAID SO:

* ``fussnoten`` — the portal's editorial notes ("Art. 13 Abs. 3: Eingef. durch …",
  "(+++ Textnachweis ab … +++)"). They are the documentation service's apparatus, not
  the enacted words, and they are re-edited independently of the law: keeping them would
  record an editor's note as an amendment. They are counted in
  :attr:`~src.law.adapters.ParsedLaw.skipped_parts`, never silently dropped.
* the ``Inhaltsübersicht`` norm — the act's own table of contents, a second copy of
  every heading. Keeping it would make one renamed section read as two changes. Counted
  the same way.

Neither is in the recovery DENOMINATOR either, so leaving them out is not a loss the
floor would forgive; everything else under a norm's ``textdaten`` is, which is what
keeps :data:`~src.law.adapters.TEXT_RECOVERY_FLOOR` a real check — a norm of a shape this
adapter does not classify costs recovered text, and enough of them refuse the document.

THE DATES. ``enacted_on`` is ``ausfertigung-datum`` — the date the Federal President
signed the act, which is the date German law treats as its making. ``valid_on`` stays
``None``: the file states WHAT last amended the text (``standkommentar``, prose such as
"Zuletzt geändert durch Art. 1 G v. 22.3.2025"), not a point in time the consolidation
represents, and the ``builddate`` attribute is when the portal BUILT the file. Reading
either as a validity date would be the collapse the date discipline exists to prevent.
``document_number`` is the portal's own ``doknr`` (``BJNR000010949``); ``year`` is not
stated as a field, so it is ``None`` rather than sliced out of a date.

SAFETY: untrusted, network-fetched bytes. The archive is opened in memory and never
written to disk (so a member name cannot traverse anywhere); exactly one XML member is
accepted; its size is bounded TWICE, once by the header and once by an actual bounded
read, because a zip header can lie about how much a member inflates to. The XML goes
through ``defusedxml`` like every other adapter's.
"""

from __future__ import annotations

import io
import re
import zipfile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as _safe_fromstring

from src.law.adapters import TEXT_RECOVERY_FLOOR, AdapterRefusal, ParsedLaw, Provision
from src.monitoring.secret_scrub import record_text

FORMAT = "gii"

#: The four bytes every zip local-file header starts with. Matched on the raw bytes,
#: never on a URL or a content type: a server may label the archive anything.
ZIP_MAGIC = b"PK\x03\x04"

#: The largest XML member this adapter will inflate. Germany's longest federal codes are a
#: few megabytes of XML; 32 MiB leaves room for any of them and still stops an archive
#: that inflates a small download into something that would exhaust memory.
MAX_XML_BYTES = 32 * 1024 * 1024

#: An act's archive holds its XML plus the images its annexes print. More members than
#: this is not an act's archive.
MAX_MEMBERS = 2000

_ROOTS = {"dokumente"}

#: Provision numbers that are the act's own TABLE OF CONTENTS rather than a provision.
_TOC_ENBEZ = {"inhaltsübersicht", "inhaltsverzeichnis"}

#: Elements whose text is a block of its own: a separator goes either side, or a list
#: marker ("1.") would run into its item ("1.öffentliche Stellen").
_BLOCK = {
    "p",
    "br",
    "dl",
    "dt",
    "dd",
    "la",
    "table",
    "row",
    "entry",
    "title",
    "subtitle",
    "pre",
    "toc",
    "ident",
    "footnote",
    "footnotes",
}

#: Every element this adapter knows inside a norm. Anything else is COUNTED in
#: ``unknown_elements`` and its text is still kept: an unfamiliar tag costs structure,
#: never text.
_KNOWN = {
    # the norm and its two halves
    "norm",
    "metadaten",
    "textdaten",
    "text",
    "content",
    "fussnoten",
    # metadata fields
    "jurabk",
    "amtabk",
    "ausfertigung-datum",
    "fundstelle",
    "periodikum",
    "zitstelle",
    "langue",
    "kurzue",
    "standangabe",
    "standtyp",
    "standkommentar",
    "enbez",
    "titel",
    "gliederungseinheit",
    "gliederungskennzahl",
    "gliederungsbez",
    "gliederungstitel",
    "neuregelung",
    "aufhebung",
    # text markup
    "p",
    "br",
    "dl",
    "dt",
    "dd",
    "la",
    "sp",
    "b",
    "i",
    "u",
    "f",
    "sup",
    "sub",
    "small",
    "pre",
    "noindex",
    "nb",
    "img",
    "title",
    "subtitle",
    "toc",
    "ident",
    "fnr",
    "footnotes",
    "footnote",
    "kommentar",
    "revision",
    "a",
    "span",
    # tables (CALS)
    "table",
    "tgroup",
    "colspec",
    "spanspec",
    "thead",
    "tbody",
    "tfoot",
    "row",
    "entry",
}

_WS_RE = re.compile(r"\s+")
_KENNZAHL_RE = re.compile(r"^\d+$")


def _local(tag) -> str:
    if not isinstance(tag, str):  # a comment/PI node's tag is a callable, not a string
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _block_text(el) -> str:
    """Every text node under ``el`` in document order, with block elements kept apart."""
    if el is None:
        return ""
    parts: list[str] = []

    def walk(node) -> None:
        block = _local(node.tag) in _BLOCK
        if block:
            parts.append(" ")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if block:
            parts.append(" ")

    walk(el)
    return _norm("".join(parts))


def _field(meta, name: str) -> str | None:
    """The first ``name`` child of the metadata, as text, or ``None`` when not stated."""
    if meta is None:
        return None
    for child in meta:
        if _local(child.tag) == name:
            value = _block_text(child)
            return value or None
    return None


def unpack_zip(data: bytes) -> bytes:
    """The one XML file inside an act's ``xml.zip``, read in memory, or a refusal.

    Never extracted to disk, so a member's name cannot point anywhere. Exactly one XML
    member: two would mean guessing which one is the act. Its size is bounded by the
    header AND by an actual bounded read, because the header is the archive's own claim.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise AdapterRefusal(
            "not a readable zip archive", detail=record_text(exc, limit=200)
        ) from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise AdapterRefusal(
                "archive has too many members", detail=f"{len(members)} > {MAX_MEMBERS}"
            )
        xml = [m for m in members if not m.is_dir() and m.filename.lower().endswith(".xml")]
        if len(xml) != 1:
            raise AdapterRefusal(
                "archive does not hold exactly one XML file",
                detail=f"{len(xml)} XML members among {len(members)}",
            )
        member = xml[0]
        if member.file_size > MAX_XML_BYTES:
            raise AdapterRefusal(
                "XML member too large",
                detail=f"declared {member.file_size} > {MAX_XML_BYTES} bytes",
            )
        try:
            with archive.open(member) as fh:
                blob = fh.read(MAX_XML_BYTES + 1)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError) as exc:
            # A bad CRC, an encrypted member, an unsupported compression method, a truncated
            # stream: each is "this archive cannot be read", never a partial act.
            raise AdapterRefusal(
                "archive member unreadable", detail=record_text(exc, limit=200)
            ) from exc
        if len(blob) > MAX_XML_BYTES:
            raise AdapterRefusal(
                "XML member too large",
                detail=f"inflated past {MAX_XML_BYTES} bytes (its header said {member.file_size})",
            )
        return blob


def looks_like_gii(body) -> bool:
    """Cheap pre-check: a zip archive, or XML whose first element is ``<dokumente``.

    The parser is its own gate (it refuses an unknown root); this only spares a parse of
    every web page. Bytes or text are accepted, because the tracker holds both.
    """
    if isinstance(body, bytes | bytearray):
        if bytes(body[:4]) == ZIP_MAGIC:
            return True
        head = bytes(body[:600]).decode("utf-8", "ignore")
    elif isinstance(body, str):
        head = body[:600]
    else:
        return False
    head = head.lstrip("﻿").lstrip()
    if not head.startswith("<"):
        return False
    return "<dokumente" in head


def parse_gii(data: bytes | str, *, retrieved_on: str | None = None) -> ParsedLaw:
    """Parse a gesetze-im-internet act — the ``xml.zip`` or the XML inside it.

    Raises :class:`AdapterRefusal` rather than guessing. ``retrieved_on`` is the caller's
    capture date: the document cannot know it, and it never stands in for a date the
    document was supposed to state.
    """
    if isinstance(data, bytes | bytearray) and bytes(data[:4]) == ZIP_MAGIC:
        data = unpack_zip(bytes(data))

    try:
        root = _safe_fromstring(data)
    except DefusedXmlException as exc:  # entity expansion / external entity
        raise AdapterRefusal("unsafe xml refused", detail=type(exc).__name__) from exc
    except Exception as exc:  # noqa: BLE001 - any malformed input is one refusal reason
        raise AdapterRefusal("not well-formed xml", detail=record_text(exc, limit=200)) from exc

    root_name = _local(root.tag)
    if root_name not in _ROOTS:
        raise AdapterRefusal(
            "not a gesetze-im-internet document", detail=f"root element <{root_name}>"
        )

    norms = [n for n in root if _local(n.tag) == "norm"]
    if not norms:
        raise AdapterRefusal("no norms found", detail=f"<{root_name}> holds no <norm> element")

    title: str | None = None
    enacted_on: str | None = None
    provisions: list[Provision] = []
    unknown: dict[str, int] = {}
    skipped: dict[str, int] = {}
    # (kennzahl, label) per open structural level, outermost first.
    open_units: list[tuple[str, str]] = []
    body_chars = 0
    captured_chars = 0

    for el in root.iter():
        name = _local(el.tag)
        if name and name not in _KNOWN and name not in _ROOTS:
            unknown[name] = unknown.get(name, 0) + 1

    for index, norm in enumerate(norms):
        meta = next((c for c in norm if _local(c.tag) == "metadaten"), None)
        textdaten = next((c for c in norm if _local(c.tag) == "textdaten"), None)

        # The denominator: everything under textdaten except the editorial footnotes.
        body_parts: list[str] = []
        text_el = None
        footnotes = 0
        if textdaten is not None:
            for child in textdaten:
                child_name = _local(child.tag)
                if child_name == "fussnoten":
                    if _block_text(child):
                        footnotes += 1
                    continue
                if child_name == "text" and text_el is None:
                    text_el = child
                body_parts.append(_block_text(child))
        norm_body = _norm(" ".join(p for p in body_parts if p))
        text = _block_text(text_el)

        enbez = _field(meta, "enbez")
        if enbez and _norm(enbez).lower() in _TOC_ENBEZ:
            skipped["table of contents"] = skipped.get("table of contents", 0) + 1
            continue  # neither numerator nor denominator: see the module docstring
        if footnotes:
            skipped["editorial footnotes"] = skipped.get("editorial footnotes", 0) + footnotes

        body_chars += len(norm_body)

        unit = None
        if meta is not None:
            unit = next((c for c in meta if _local(c.tag) == "gliederungseinheit"), None)

        if index == 0 and enbez is None and unit is None:
            # The act's own metadata norm.
            title = _field(meta, "langue")
            enacted_on = _field(meta, "ausfertigung-datum")
            if text:
                provisions.append(Provision(number=None, heading=None, text=text, element="norm"))
                captured_chars += len(text)
            continue

        if unit is not None:
            kennzahl = (_field(unit, "gliederungskennzahl") or "").strip()
            label = " ".join(
                x for x in (_field(unit, "gliederungsbez"), _field(unit, "gliederungstitel")) if x
            )
            if kennzahl and _KENNZAHL_RE.match(kennzahl):
                # Close every open level that is not this unit's ancestor. The prefix test
                # reads the depth the portal wrote, rather than assuming three digits a level.
                while open_units and not (
                    kennzahl.startswith(open_units[-1][0])
                    and len(kennzahl) > len(open_units[-1][0])
                ):
                    open_units.pop()
            else:
                # No usable depth: treat it as a sibling of the innermost open level rather
                # than inventing a nesting the document did not state.
                if open_units:
                    open_units.pop()
            parent = tuple(lbl for _kz, lbl in open_units)
            open_units.append((kennzahl, label))
            if text:
                provisions.append(
                    Provision(
                        number=None,
                        heading=label or None,
                        text=text,
                        path=parent,
                        element="gliederungseinheit",
                    )
                )
                captured_chars += len(text)
            continue

        if enbez is None and not text:
            continue  # an empty norm with nothing to address: nothing lost, nothing kept

        provisions.append(
            Provision(
                number=enbez,
                heading=_field(meta, "titel"),
                text=text,
                path=tuple(lbl for _kz, lbl in open_units),
                element="norm",
            )
        )
        captured_chars += len(text)

    recovered = (captured_chars / body_chars) if body_chars else 0.0
    recovered = min(1.0, recovered)

    if not provisions:
        raise AdapterRefusal(
            "no provisions found",
            detail=f"{len(norms)} norms, {body_chars} chars of body text, {len(unknown)} unmodelled element kinds",
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
        title=title,
        provisions=provisions,
        enacted_on=enacted_on,
        valid_on=None,
        retrieved_on=retrieved_on,
        document_number=(root.get("doknr") or "").strip() or None,
        year=None,
        unknown_elements=unknown,
        skipped_parts=skipped,
        text_recovered_pct=recovered,
        body_chars=body_chars,
        format=FORMAT,
    )
