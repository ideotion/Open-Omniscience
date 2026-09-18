"""Q726's licence obligation: CC BY-SA 4.0, named, with a link to the page history.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q726 = a, verbatim: "``docs/SECURITY.md`` lists every Wikimedia host; the Wikipedia
surface states the robots exemption the way ``stats/fetch.py:22–25`` does; the reader
shows the CC BY-SA 4.0 attribution with a link to the page history."

THE HISTORY LINK IS THE ATTRIBUTION, NOT A CONVENIENCE. CC BY-SA asks for credit to
the authors, and a wiki article's authors are its edit history — there is no byline to
print. The licence's own "reasonable to the medium" clause is met online by linking to
that history, which is why this module builds a ``?action=history`` URL rather than
only naming a revision. The revision link the reader already had says WHICH TEXT this
is; the history link says WHO WROTE IT. Both, and they are different obligations.

WHAT THIS MODULE REFUSES TO GUESS. It builds URLs for a KNOWN edition and a KNOWN
title and returns ``None`` otherwise. An article whose wiki cannot be determined gets
no attribution block at all rather than one pointing at ``en`` — a licence notice that
credits the wrong project is worse than none, because it is a false statement about
someone else's work made in a place a reader will believe.

TEXT IS NOT LICENCE. This module names the licence the WIKITEXT arrives under. It says
nothing about images, which on Wikipedia carry their own per-file licences and which
this app does not ingest — stated because a blanket "this page is CC BY-SA" over
content that included images would be wrong in a way nobody would notice.

NO I/O. Pure string work, so the reader can call it while offline, which is the only
state a local reader is guaranteed to be in.
"""

from __future__ import annotations

from typing import Any

#: The licence Wikipedia's text is published under. Named in full, with its version:
#: "CC BY-SA" without a version is ambiguous across four incompatible releases.
LICENCE_NAME: str = "CC BY-SA 4.0"

#: The deed, not the legal code: the deed is the page a reader can act on, and it
#: links to the legal code for anyone who needs it.
LICENCE_URL: str = "https://creativecommons.org/licenses/by-sa/4.0/"

#: Wikipedia also publishes text under the GFDL. Named because a re-user choosing
#: that path is entitled to know it exists; this app's own surfaces cite CC BY-SA.
ALSO_AVAILABLE_UNDER: str = "GFDL"


def _host(wiki: str) -> str | None:
    code = (wiki or "").strip().lower()
    if not code or not code.replace("-", "").isalnum():
        return None
    return f"{code}.wikipedia.org"


def _title_param(title: str) -> str | None:
    """MediaWiki's own URL spelling of a title: spaces are underscores.

    Percent-encoding is left to the caller's escaper. Returning ``None`` for an empty
    title is deliberate — a history URL with no title is the project's main page, and
    silently crediting that instead of the article is exactly the wrong-attribution
    failure this module exists to avoid.
    """
    cleaned = " ".join((title or "").split())
    if not cleaned:
        return None
    return cleaned.replace(" ", "_")


def page_url(wiki: str, title: str) -> str | None:
    """The article itself on the wiki, or ``None`` when either part is unknown."""
    host, slug = _host(wiki), _title_param(title)
    if not host or not slug:
        return None
    return f"https://{host}/wiki/{slug}"


def history_url(wiki: str, title: str) -> str | None:
    """The page's edit history — the authors CC BY-SA asks to be credited."""
    host, slug = _host(wiki), _title_param(title)
    if not host or not slug:
        return None
    return f"https://{host}/w/index.php?title={slug}&action=history"


def revision_url(wiki: str, revision: Any) -> str | None:
    """One exact revision, when the stored text names one."""
    host = _host(wiki)
    if not host:
        return None
    text = str(revision or "").strip()
    if not text.isdigit():
        return None
    return f"https://{host}/w/index.php?oldid={text}"


def attribution(wiki: str, title: str, *, revision: Any = None) -> dict[str, Any] | None:
    """Everything a licence notice needs, or ``None`` when it cannot be built honestly.

    The returned dict carries URLs and TOKENS only. Not one sentence: the words a
    reader sees are composed by the caller through the i18n engine and ship ×12,
    because a licence notice rendered in English to an Arabic-reading operator is a
    notice they were not given.
    """
    page = page_url(wiki, title)
    history = history_url(wiki, title)
    if not page or not history:
        return None
    return {
        "wiki": (wiki or "").strip().lower(),
        "title": " ".join((title or "").split()),
        "licence": LICENCE_NAME,
        "licence_url": LICENCE_URL,
        "also_under": ALSO_AVAILABLE_UNDER,
        "page_url": page,
        "history_url": history,
        "revision_url": revision_url(wiki, revision),
        # The narrow claim, so the caller cannot widen it by accident.
        "covers": "text",
    }
