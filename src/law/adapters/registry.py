"""The adapter framework: one adapter per source FORMAT, one class per source SHAPE.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q906 = a asks for "one adapter per source format (CLML, LEGI XML, USLM, e-Gov XML,
Formex/HTML, gesetze-im-internet XML, Akoma Ntoso itself where a portal serves it);
text-only sources fill the same model with one provision". Q909 = a asks for three
source CLASSES, in a stated order of preference. This module is both vocabularies and
the lookup between them, and it is deliberately the ONLY place either is written.

**ONE ADAPTER IS REGISTERED: CLML.** That is not an omission — Q925 ⛔ (the adapter
ORDER and the first managed dataset) is PENDING, and choosing a second format would be
answering it. The framework exists so the answer, when it comes, is a registration and
a parser module rather than a change to any caller: ``adapter_for`` already resolves by
token, ``parse_with`` already normalises the refusal, and the model, the tracker and the
reader already read a ``ParsedLaw`` without knowing which parser made it. The test that
matters proves exactly that — a second adapter is registered in a test and round-trips
without touching a line of production code.

A FORMAT TOKEN IS NOT A GUESS. ``adapter_for`` refuses an unknown token by name rather
than falling back to the HTML path, because a source declaring ``uslm`` and silently
getting the page-scraper would look like it worked: the text would be there, the
provisions would be wrong, and nothing would say so. The HTML path is what a source with
NO declared format gets, which is a different statement.

TEXT-ONLY SOURCES FILL THE SAME MODEL WITH ONE PROVISION (Q906's last clause). That is
``single_provision``, below, and it belongs here rather than in each caller so the
"whole document is one provision" address is written once — a caller inventing its own
would give the same document two different addresses on two code paths.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from src.law.adapters import AdapterRefusal, ParsedLaw, Provision

__all__ = [
    "SOURCE_CLASSES",
    "SOURCE_CLASS_NOTES",
    "UnknownFormatError",
    "adapter_for",
    "known_formats",
    "parse_with",
    "single_provision",
]

#: Q909 = a, in the ruled ORDER of preference: "Bulk open data first wherever it exists
#: …, then enumeration adapters (crawl an index politely), then gazette feeds for
#: countries with neither." The order is the ruling, so it is the tuple's order and not a
#: sort key somebody could change without noticing.
SOURCE_CLASSES: Final[tuple[str, ...]] = ("bulk", "enumeration", "gazette-feed")

#: What each class MEANS, in one sentence, because "bulk" and "enumeration" are not
#: self-explanatory and a catalogue row declaring the wrong one changes how politely
#: this app treats somebody's server.
SOURCE_CLASS_NOTES: Final[dict[str, str]] = {
    "bulk": (
        "the publisher offers the corpus as data — a dump, an archive or a documented "
        "per-document API — so nothing has to be crawled to find out what exists"
    ),
    "enumeration": (
        "there is no bulk channel, so the index is walked politely to discover "
        "documents; one request per page, at the host's own rate"
    ),
    "gazette-feed": (
        "neither exists, so the official gazette's own feed is followed and only what "
        "it announces is fetched"
    ),
}


class UnknownFormatError(ValueError):
    """A format token no adapter is registered for.

    Its own type because a caller legitimately catches it (a tracker records the source
    as unreadable and keeps its HTML reading) while never wanting to swallow a genuine
    programming ``ValueError`` raised inside a parser.
    """


#: format token -> parser. A parser takes ``(data, *, retrieved_on)`` and returns a
#: ``ParsedLaw`` or raises ``AdapterRefusal``. Deliberately a plain dict of one entry:
#: the second entry is Q925's to add.
_ADAPTERS: Final[dict[str, Callable[..., ParsedLaw]]] = {}


def _register_builtin() -> None:
    """Registered lazily, so importing this module does not import every parser.

    ``clml`` pulls in ``defusedxml``; a registry that imported six of these at module
    load would put every adapter's dependencies on the boot path of an install that
    tracks no law at all.
    """
    if _ADAPTERS:
        return
    from src.law.adapters.clml import parse_clml

    _ADAPTERS["clml"] = parse_clml


def known_formats() -> tuple[str, ...]:
    """Every format token an adapter is registered for, sorted.

    Sorted rather than insertion-ordered: this is read by surfaces that list what the
    app can read, and a list whose order depends on import order is a list that changes
    for no reason a reader can see.
    """
    _register_builtin()
    return tuple(sorted(_ADAPTERS))


def adapter_for(fmt: str) -> Callable[..., ParsedLaw]:
    """The parser for ``fmt``, or refuse BY NAME.

    Never a fallback. A source that declares ``uslm`` and silently gets the HTML
    page-scraper would look like it worked — text present, provisions wrong, nothing
    said — which is worse than the source being reported as unreadable.
    """
    _register_builtin()
    token = (fmt or "").strip().lower()
    try:
        return _ADAPTERS[token]
    except KeyError:
        raise UnknownFormatError(
            f"no adapter is registered for format {fmt!r}; registered formats are "
            f"{', '.join(known_formats()) or '(none)'}"
        ) from None


def register_adapter(fmt: str, parser: Callable[..., ParsedLaw]) -> None:
    """Register a parser for a format token.

    THE PUBLIC SEAM, and the thing that makes "a second adapter fits without code
    changes" a measurable claim rather than an aspiration: a test registers one here and
    drives the whole pipeline with it.

    A second registration for the same token REPLACES the first and says so in the
    exception message if the parser differs, because two adapters quietly claiming one
    format is how a document gets parsed by whichever module imported last.
    """
    _register_builtin()
    token = (fmt or "").strip().lower()
    if not token:
        raise UnknownFormatError("a format token cannot be empty")
    existing = _ADAPTERS.get(token)
    if existing is not None and existing is not parser:
        raise UnknownFormatError(
            f"format {token!r} is already registered to {existing!r}; two adapters "
            "claiming one format means the document is parsed by whichever imported last"
        )
    _ADAPTERS[token] = parser


def parse_with(fmt: str, data: bytes | str, *, retrieved_on: str | None = None) -> ParsedLaw:
    """Parse ``data`` with the adapter for ``fmt``. The ONE call site callers need.

    ``retrieved_on`` is threaded through because the document cannot know when we
    fetched it — the adapter contract's whole point is that the parser never invents
    that date.
    """
    return adapter_for(fmt)(data, retrieved_on=retrieved_on)


def single_provision(text: str, *, title: str | None = None, fmt: str = "text") -> ParsedLaw:
    """Q906's last clause: a text-only source fills the same model with ONE provision.

    Written here rather than in each caller so the address of "the whole document" is
    written ONCE. Two callers inventing their own would give one document two different
    addresses on two code paths, and a provision timeline would then show a document
    replacing itself every time the other path ran.

    ``text_recovered_pct`` is 1.0 and that is not a flattering default: for a text-only
    source the text IS the document, so a hundred percent of the body was recovered by
    definition. The figure means something different for a structured parser, which is
    why that one measures instead of asserting.
    """
    body = text or ""
    if not body.strip():
        raise AdapterRefusal("empty document", detail="a text-only source gave no text")
    return ParsedLaw(
        title=title,
        provisions=[Provision(number=None, heading=title, text=body, element="document")],
        format=fmt,
        body_chars=len(body),
        text_recovered_pct=1.0,
    )
