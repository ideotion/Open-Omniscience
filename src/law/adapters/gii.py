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
  every heading. The headings themselves are NOT lost: every structural unit is emitted
  as a heading-only provision, in place, so renaming a Part or a Chapter changes the
  tracked text once, where it happened, rather than twice (or, without the units, not at
  all). Counted the same way.
* images (``<IMG>``, mostly signs and forms in annexes) — there is no text to keep, so
  they are counted in ``skipped_parts`` rather than vanishing from a figure that would
  then read as complete.

Official notes INSIDE the text (``<Footnotes>`` under ``Content``, e.g. the BGB's
"Amtlicher Hinweis") are part of the enacted text and are kept.

THE RECOVERY FIGURE. The denominator is every text node under the root except the
metadata, the editorial footnotes and the table of contents; the numerator is what was
placed into provisions. Both count characters that are not whitespace (``body_chars``
therefore does too), so the figure measures words left behind rather than how text nodes
were joined. Text in a place this adapter does not read (a sibling of
``<text>`` under ``textdaten``, a ``<norm>`` nested in a norm, a root child that is not
a norm) is therefore in the first and not the second, which is what keeps
:data:`~src.law.adapters.TEXT_RECOVERY_FLOOR` a real check: enough of it refuses the
document. On the fourteen large acts measured (BGB, ZPO, StGB, SGB V, EStG …) it reads
100 %, and that is the figure saying nothing was left behind, not a default.

PATHS. The XML is flat: a unit is opened by its own norm and never closed, so a path is
inferred from the ``gliederungskennzahl`` prefix. An annex (``Anlage``, ``Anhang``) after
the last chapter belongs to the act, not to that chapter, so an annex closes every open
unit; without that, every annex would be addressed as part of the final chapter, and the
address is what ``law.db`` stores. Nesting deeper than :data:`MAX_DEPTH` is refused: no
federal act comes near it (the BGB reaches 6), and an unbounded depth is a way for a tiny
file to cost gigabytes.

THE DATES. ``enacted_on`` is ``ausfertigung-datum`` exactly as the portal states it. For
most acts that is the day the act was signed; for the old codes it is the date of the
version the consolidation descends from (BGB 1896, StGB 1871, ZPO and StPO the 1950
re-promulgation), and this adapter does not second-guess it. ``valid_on`` stays
``None``: the file states WHAT last amended the text (``standkommentar``, prose such as
"Zuletzt geändert durch Art. 1 G v. 22.3.2025"), not a point in time the consolidation
represents, and the ``builddate`` attribute is when the portal BUILT the file. Reading
either as a validity date would be the collapse the date discipline exists to prevent.
``document_number`` is the portal's own ``doknr`` (``BJNR000010949``); ``year`` is not
stated as a field, so it is ``None`` rather than sliced out of a date.

SAFETY: untrusted, network-fetched bytes. The archive is opened in memory and never
written to disk (so a member name cannot traverse anywhere); exactly one XML member is
accepted; its size is bounded by the header, and the read itself is bounded, because a
header can lie: a member that inflates past its declared size fails the archive's own CRC
check and is refused. The text walk is iterative, so a deeply nested document cannot
exhaust the interpreter's stack. The XML goes
through ``defusedxml`` like every other adapter's.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

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

#: The deepest structural nesting this adapter accepts. The BGB, the deepest act measured,
#: reaches 6 levels; each provision's path is shared rather than copied, and this bound is
#: what keeps a crafted document from making that path the size of the file.
MAX_DEPTH = 32

#: Provision numbers that open an ANNEX: it belongs to the act, not to the last chapter.
_ANNEX_RE = re.compile(r"^(anlage|anhang)\b", re.IGNORECASE)

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
    # A sentence number is printed as a superscript ("(1) ¹Natürliche Personen …"): without
    # a separator it fuses with the first word ("1Natürliche"), a token no reader typed.
    "sup",
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


def _ink(text: str) -> int:
    """Characters that are not whitespace: what the recovery figure counts.

    Whitespace is where text nodes are JOINED, and the same words joined per provision or
    across the whole document differ only there; counting it would make the figure measure
    the join rather than whether any words were left behind.
    """
    return len(text) - sum(1 for ch in text if ch.isspace())


def _block_text(el) -> str:
    """Every text node under ``el`` in document order, with block elements kept apart.

    Iterative, with an explicit stack: a recursive walk raises ``RecursionError`` on a
    document nested about a thousand levels deep, which the defused parser itself accepts.
    """
    if el is None:
        return ""
    parts: list[str] = []
    # (node, leaving): entering emits the opening separator and the node's text; leaving
    # emits the closing separator and the node's tail (the text after it, inside its parent).
    stack: list[tuple[Any, bool]] = [(el, False)]
    while stack:
        node, leaving = stack.pop()
        block = _local(node.tag) in _BLOCK
        if leaving:
            if block:
                parts.append(" ")
            if node is not el and node.tail:
                parts.append(node.tail)
            continue
        if block:
            parts.append(" ")
        if node.text:
            parts.append(node.text)
        stack.append((node, True))
        stack.extend((child, False) for child in reversed(list(node)))
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
            # Unreachable with today's zipfile, which stops at the declared size and then
            # fails the CRC (refused above); kept so a library change cannot remove the bound.
            raise AdapterRefusal("XML member too large", detail=f"read past {MAX_XML_BYTES} bytes")
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
    head = head.lstrip("\ufeff").lstrip()
    # The FIRST element must be <dokumente>, after at most a declaration, a doctype and
    # comments: a page that merely mentions the tag further in is not the portal's XML.
    return _first_element_is_dokumente(head)


def _first_element_is_dokumente(head: str) -> bool:
    """Skip a declaration, comments and a doctype, then ask whether ``<dokumente`` opens.

    A loop of ``find`` calls rather than a regular expression: each step consumes text and
    moves forward, so the cost is linear in the head however it is crafted. (A pattern with
    repeated optional comment groups backtracks exponentially on a run of empty comments.)
    """
    pos = 0
    while True:
        while pos < len(head) and head[pos].isspace():
            pos += 1
        if head.startswith("<?", pos):
            closer = "?>"
        elif head.startswith("<!--", pos):
            closer = "-->"
        elif head[pos : pos + 9].upper() == "<!DOCTYPE":
            closer = ">"
        else:
            break
        end = head.find(closer, pos + 2)
        if end < 0:
            return False
        pos = end + len(closer)
    tag = head[pos : pos + 11].lower()
    return tag.startswith("<dokumente") and (len(tag) == 10 or tag[10] in " \t\r\n>/")


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
    # (kennzahl, label) per open structural level, outermost first, and the path they make:
    # built once per change and SHARED by every provision under it, never copied per provision.
    open_units: list[tuple[str, str]] = []
    path: tuple[str, ...] = ()
    captured_chars = 0

    def skip(kind: str, n: int = 1) -> None:
        if n:
            skipped[kind] = skipped.get(kind, 0) + n

    for el in root.iter():
        name = _local(el.tag)
        if name and name not in _KNOWN and name not in _ROOTS:
            unknown[name] = unknown.get(name, 0) + 1

    # THE DENOMINATOR: every text node under the root, minus the metadata, the editorial
    # footnotes and the table of contents -- the three things left out on purpose.
    excluded_chars = 0
    for norm in norms:
        meta = next((c for c in norm if _local(c.tag) == "metadaten"), None)
        if _norm(_field(meta, "enbez") or "").lower() in _TOC_ENBEZ:
            excluded_chars += _ink(_block_text(norm))
            continue
        # Only where the format puts them: the norm's own metadata and the footnotes directly
        # under its textdaten. Each subtree is walked ONCE: searching every descendant would
        # re-walk a nested copy at every level, quadratic in a crafted file's depth. Text
        # under any other placement stays in the denominator and costs recovery.
        for child in norm:
            name = _local(child.tag)
            if name == "metadaten":
                excluded_chars += _ink(_block_text(child))
            elif name == "textdaten":
                for part in child:
                    if _local(part.tag) == "fussnoten":
                        excluded_chars += _ink(_block_text(part))
    body_chars = max(0, _ink(_block_text(root)) - excluded_chars)

    for index, norm in enumerate(norms):
        meta = next((c for c in norm if _local(c.tag) == "metadaten"), None)
        textdaten = next((c for c in norm if _local(c.tag) == "textdaten"), None)
        text_el = None
        if textdaten is not None:
            text_el = next((c for c in textdaten if _local(c.tag) == "text"), None)
        text = _block_text(text_el)

        enbez = _field(meta, "enbez")
        if enbez and _norm(enbez).lower() in _TOC_ENBEZ:
            skip("table of contents")
            continue  # neither numerator nor denominator: see the module docstring
        if textdaten is not None:
            skip(
                "norms with editorial footnotes",
                sum(1 for c in textdaten if _local(c.tag) == "fussnoten" and _block_text(c)),
            )
        skip("images", sum(1 for e in norm.iter() if _local(e.tag) == "img"))

        unit = None
        if meta is not None:
            unit = next((c for c in meta if _local(c.tag) == "gliederungseinheit"), None)

        if index == 0 and enbez is None and unit is None:
            # The act's own metadata norm.
            title = _field(meta, "langue")
            enacted_on = _field(meta, "ausfertigung-datum")
            if text:
                provisions.append(Provision(number=None, heading=None, text=text, element="norm"))
                captured_chars += _ink(text)
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
            elif open_units:
                # No usable depth: a sibling of the innermost open level, never a nesting the
                # document did not state.
                open_units.pop()
            if len(open_units) >= MAX_DEPTH:
                raise AdapterRefusal(
                    "structure nested too deeply", detail=f"more than {MAX_DEPTH} levels"
                )
            parent = tuple(lbl for _kz, lbl in open_units)
            open_units.append((kennzahl, label))
            path = (*parent, label)
            # The unit's heading is part of the act's text: emitted in place, so a renamed
            # Part or Chapter reads as one change, where it happened.
            provisions.append(
                Provision(
                    number=None,
                    heading=label or None,
                    text=text,
                    path=parent,
                    element="gliederungseinheit",
                )
            )
            captured_chars += _ink(text)
            continue

        if enbez is None and not text:
            continue  # an empty norm with nothing to address: nothing lost, nothing kept

        if enbez and _ANNEX_RE.match(_norm(enbez)) and open_units:
            # An annex belongs to the act, not to the last chapter before it.
            open_units = []
            path = ()

        provisions.append(
            Provision(
                number=enbez, heading=_field(meta, "titel"), text=text, path=path, element="norm"
            )
        )
        captured_chars += _ink(text)

    recovered = (captured_chars / body_chars) if body_chars else 0.0
    recovered = min(1.0, recovered)

    if not any(p.text for p in provisions):
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
