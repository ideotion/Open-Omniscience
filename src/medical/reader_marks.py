"""The reader's paper marks: a cited link to a paper this install keeps shows that paper's class (row 214).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. Paper classes were drawn only in the analysis's Papers subtab, so a reader could follow an
article's link to a retracted paper and see nothing (S07-01 S1 asks for retraction status wherever a
paper is shown). The reader's "Sources this article cites" list is where those links already are, so
each link to a kept PubMed, PMC or DOI record gets the same badges the Papers subtab draws: the class
the record states (journal record, preprint, retracted), the notices it links to (an erratum, an
expression of concern, a retraction notice) and a withdrawal mark, with the same hover text.

WHAT IT DOES NOT DO. It requests nothing (the lookup is :func:`src.medical.store.papers_cited_by`
over this install's ``medical.db``), creates no file (a lane never fetched answers with no marks), and
says NOTHING about a link whose paper is not kept here: R750, a paper missing here is not missing from
PubMed, so silence is the only honest answer. The marks are labels about the cited paper, never a
verdict on the article that cites it. The labels are the Papers subtab's English keys, so the reader's
i18n pass translates them in all twelve languages.
"""

from __future__ import annotations

import html
from typing import Any

#: The class badges and their hover text, the SAME keys as ``app-medical.js`` (``_CLASS_LABEL`` / ``_CLASS_HOVER``).
CLASS_LABEL = {"journal": "Journal record", "preprint": "Preprint", "retracted": "Retracted"}
CLASS_HOVER = {
    "journal": (
        "PubMed indexes this record as a journal publication. Peer review is the journal's claim; this app does not "
        "check it. Not retracted in this copy of the record: a retraction recorded later may not be in it yet."
    ),
    "preprint": "A preprint: not peer reviewed. PubMed lists it, which is not an endorsement.",
    "retracted": "The PubMed record says this paper was retracted. Read it as retracted, whatever the articles citing it say.",
}
#: The notice badges (``_NOTICE_LABEL`` in ``app-medical.js``).
NOTICE_LABEL = {"erratum": "Erratum published", "concern": "Expression of concern", "retraction": "Retraction notice"}
WITHDRAWN_LABEL = "Withdrawn from PubMed"


def link_marks(urls: list[str]) -> dict[int, list[dict[str, Any]]]:
    """``{position in urls: [the kept papers that link names]}``, local only; ``{}`` when nothing is kept.

    Each link is looked up on its own (its position stands in for an article id in
    :func:`~src.medical.store.papers_cited_by`), so a badge sits on the link that names the paper and
    never on its neighbour. A lane that was never fetched is not opened, so no file is created."""
    from src.medical import store as M
    from src.medical.fetch import cited_ids
    from src.versioned import store

    cited = {i: w for i, url in enumerate(urls) if url and len(w := cited_ids([url]))}
    if not cited or not store.lane_path(M.LANE).exists():
        return {}
    with store.lane_session(M.LANE) as s:
        found = M.papers_cited_by(s, cited)
    out: dict[int, list[dict[str, Any]]] = {}
    for p in found["papers"]:
        mark = {
            "pmid": p["pmid"],
            "provenance_class": p["provenance_class"],
            "notices": list(p["notices"]),
            "withdrawn": bool(p["withdrawn"]),
        }
        for i in p["article_ids"]:
            out.setdefault(int(i), []).append(mark)
    for marks in out.values():
        marks.sort(key=lambda m: m["pmid"])
    return out


def _badge(text: str, cls: str, hover: str | None = None) -> str:
    title = f" title='{html.escape(hover)}'" if hover else ""
    return f"<span class='med-badge med-{html.escape(cls)}'{title}>{html.escape(text)}</span>"


def marks_html(marks: list[dict[str, Any]]) -> str:
    """The badges for one link's kept papers, in the Papers subtab's order: class, notices, withdrawal.

    An unknown class is not drawn (a label this module cannot name would read as a claim). Empty input
    gives an empty string, so a link with no kept paper looks exactly as it did."""
    parts: list[str] = []
    for m in marks:
        cls = m.get("provenance_class")
        if cls in CLASS_LABEL:
            parts.append(_badge(CLASS_LABEL[cls], cls, CLASS_HOVER[cls]))
        for n in m.get("notices") or ():
            if n in NOTICE_LABEL:
                parts.append(_badge(NOTICE_LABEL[n], "notice-" + n))
        if m.get("withdrawn"):
            parts.append(_badge(WITHDRAWN_LABEL, "withdrawn"))
    return f" <span class='med-marks'>{''.join(parts)}</span>" if parts else ""
