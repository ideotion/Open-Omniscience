"""The report's annexes: one file per article it cites, and a contents page.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask, 2026-08-11: bundle "the bulletin's report mentioned article and a
detailed table of content as well articles (with direct and deduced metadata,
including AI translations and summaries) in the format of bundled .md files, named
with reference number", zipped, with the report referencing articles by that
number, and one button that downloads both.

**THIS IS NOT THE EVIDENCE ARCHIVE, and the difference is the point.**
``evidence.build_evidence_archive`` writes every article in the period — "all of
them, not a sample" — as JSON to a server-side directory, so an edition's counts
can be recomputed. It is measured in gigabytes and is not a browser download. The
ANNEXES are the report's own citation set: the articles the document names, as
readable Markdown, small enough to travel beside it. One is for proving the
numbers; the other is for reading the sources.

REFERENCE NUMBERS ARE ASSIGNED HERE AND NOWHERE ELSE. ``assign_refs`` is pure,
deterministic over a given record, and called by BOTH the renderer and the bundle
builder — so the report's ``[0001]`` and the file ``…_Article_0001.md`` cannot
disagree. Two callers that each numbered their own way would be the recorded
one-key-two-meanings defect with a filename attached: a reader following a
reference to the wrong article would have no way to tell.

FULL TEXT IS THE DEFAULT, AS ASKED, AND IT IS DISCLOSED. ``articles.py`` says a
shareable document should carry an excerpt, because putting a period's full text in
one turns a summary into a redistribution of other people's writing. That still
holds for the REPORT, which is why the report still carries excerpts. The annexes
are the operator's own working set of the sources they cited, and they say so, in
the contents page and in every file. ``full_text=False`` produces an
excerpt-only bundle for an operator who intends to pass it on.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import UTC, date, datetime
from typing import Any

from src.bulletin.i18n import Translator

_LOG = logging.getLogger(__name__)

#: The report's own name pattern, and the annexes' — the maintainer's, verbatim.
#: THREE DATES, EACH FROM A DIFFERENT FACT (maintainer, 2026-08-11). They are not
#: interchangeable and the whole point of separating them is that each answers a
#: different question a reader might have:
#:
#: * the REPORT and the ZIP carry the date the bundle was CREATED — when this
#:   document came into being, which is what an operator filing it is filing;
#: * each ARTICLE file carries the article's own PUBLICATION date — asserted by the
#:   publisher, never the day this app happened to collect it, so a 2019 piece cited
#:   in a 2026 bulletin reads as 2019;
#: * the CONTENTS page carries the creation date, because it describes the bundle
#:   rather than any one article.
#:
#: CONSEQUENCE, stated because it changes how the bundle is read: an article's
#: filename can no longer be derived from its reference number. The contents page
#: lists the filename against every number for exactly that reason, and the report's
#: legend says so.
_CADENCE_LABEL = {
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "trimester": "Trimester",
    "semester": "Semester",
    "yearly": "Yearly",
}

#: Raw text carried before the remaining articles fall back to their excerpt. The
#: bundle is the report's citation set — a few hundred articles at most — so this is
#: a backstop against a pathological edition, never an expected path. When it fires
#: it is STATED in the contents page: a bundle quietly holding excerpts where it
#: promised full text would be worse than a large download.
DEFAULT_TEXT_BUDGET_BYTES = 64 * 1024 * 1024

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _label(cadence: str) -> str:
    c = (cadence or "").strip().lower()
    return _CADENCE_LABEL.get(c, c.title() or "Period")


UNDATED = "undated"


def _day(raw: Any) -> date | None:
    """The date part of an ISO timestamp, or None. Never a guess."""
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def creation_date(edition: dict) -> date:
    """The day this bulletin came into being.

    ``generated_at`` is stamped by ``store.persist_edition``, so it is the record's
    own account of when it was made — and using it rather than ``now()`` is what
    makes the name STABLE: downloading the same edition next month must not produce a
    differently-named file, or an operator's archive gains a second copy of one
    document under two names. It also keeps the ordinal below meaningful, since two
    editions made on one day share a stem and the ordinal is what separates them; a
    download-time date would give the same stem to two editions made weeks apart and
    the ordinal, computed per creation day, could not tell them apart.

    A record with no readable ``generated_at`` falls back to today, which is honest:
    the bundle genuinely is being created now, and nothing is claimed that is not so.
    """
    return _day(edition.get("generated_at")) or datetime.now(UTC).date()


def bundle_stem(edition: dict, *, ordinal: int = 1) -> str:
    """``20260811_OOS_Bulletin_Weekly``, with ``_2`` and up for a repeat.

    The date is the bundle's CREATION day and the ordinal is what distinguishes two
    bulletins created on it — the "several bulletins produced the same day" case. It
    is a POSITION among that day's editions, not a next-free counter, so
    re-downloading one always produces the same filename.
    """
    cadence = str((edition.get("period") or {}).get("cadence") or "").strip()
    stem = f"{creation_date(edition).strftime('%Y%m%d')}_OOS_Bulletin_{_label(cadence)}"
    n = int(ordinal or 1)
    return stem if n <= 1 else f"{stem}_{n}"


def report_filename(edition: dict, *, ordinal: int = 1, fmt: str = "markdown") -> str:
    ext = "html" if (fmt or "").strip().lower() == "html" else "md"
    return f"{bundle_stem(edition, ordinal=ordinal)}.{ext}"


def annexes_filename(edition: dict, *, ordinal: int = 1) -> str:
    return f"{bundle_stem(edition, ordinal=ordinal)}_Annexes.zip"


def contents_filename(edition: dict) -> str:
    """``20260811_Table_of_Contents.md`` — the creation date, because this file
    describes the BUNDLE rather than any one article."""
    return f"{creation_date(edition).strftime('%Y%m%d')}_Table_of_Contents.md"


def article_filename(published_at: Any, ref: str) -> str:
    """``20260805_Article_0001.md`` — the article's own PUBLICATION date.

    Not the day it was collected, and not the bundle's date: a 2019 piece cited in a
    2026 bulletin reads as 2019, which is a fact about the source rather than about
    this app's schedule.

    ``published_at`` is what the PUBLISHER asserted and is frequently absent —
    extraction fails, or a page carries no date. That case is named ``undated``
    rather than filled with the collection date, because substituting the day we
    happened to fetch something for the day it was published is exactly the
    conflation this naming was changed to remove.
    """
    day = _day(published_at)
    stamp = day.strftime("%Y%m%d") if day else UNDATED
    return f"{stamp}_Article_{_SAFE.sub('', str(ref))}.md"


def edition_ordinal(filename: str | None, siblings: list[dict]) -> int:
    """Which bundle this edition is, among those CREATED on the same day.

    Each ``siblings`` row needs ``filename``, ``cadence`` and ``generated_at`` —
    ``store.list_editions()`` supplies the first two from the filename; the third
    lives inside each record, so the caller reads it (see ``api.bulletin._siblings``,
    which only opens the same-cadence ones, since nothing else can share a stem).

    The position is taken over SORTED FILENAMES rather than write times: a file's
    mtime changes when it is touched, and a name that moves under the operator is
    worse than an arbitrary but fixed order. An edition that was never persisted has
    no filename and is the first.
    """
    if not filename:
        return 1
    me = next((r for r in siblings if r.get("filename") == filename), None)
    if me is None:
        return 1
    key = (_day(me.get("generated_at")), me.get("cadence"))
    same = sorted(
        r["filename"]
        for r in siblings
        if r.get("filename") and (_day(r.get("generated_at")), r.get("cadence")) == key
    )
    try:
        return same.index(filename) + 1
    except ValueError:
        return 1


# --------------------------------------------------------------------------- #
#  reference numbers
# --------------------------------------------------------------------------- #
def _row_lists(node: Any) -> Any:
    """Every ``article_rows`` list under ``node``, in encounter order.

    A generic depth-first walk rather than a hardcoded path, so a section that
    starts naming articles is picked up without this file being edited — the
    alternative is an enumeration, and an enumeration is wrong the day someone adds
    the thing it does not list. Lists keep their order and dicts keep their
    insertion order, so "encounter order" is the document's reading order.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "article_rows" and isinstance(value, list):
                yield value
            else:
                yield from _row_lists(value)
    elif isinstance(node, list):
        for item in node:
            yield from _row_lists(item)


def _where(section: dict, entry: dict | None, card: dict | None) -> str:
    bits = [str(section.get("section") or "section").replace("_", " ")]
    if entry and entry.get("type"):
        bits.append(str(entry["type"]).replace("_", " "))
    if card and card.get("title"):
        bits.append(str(card["title"]))
    return " · ".join(bits)


def assign_refs(edition: dict) -> list[dict]:
    """Number every article the document names, and stamp the number onto each row.

    Returns the index: one entry per DISTINCT article, in the order a reader meets
    it, each carrying every place it is cited. An article named twice keeps ONE
    reference number and gets one annex file — the number identifies the article,
    not the mention.

    Deterministic, therefore idempotent: called twice over the same record it
    produces the same numbering, which is what lets the renderer and the bundle
    builder both call it without coordinating.
    """
    index: dict[int, dict] = {}
    order: list[int] = []

    def _take(rows: list, where: str) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            aid = row.get("id")
            if aid is None:
                continue
            aid = int(aid)
            if aid not in index:
                order.append(aid)
                index[aid] = {
                    "id": aid,
                    "title": row.get("title"),
                    "url": row.get("url"),
                    "source": (row.get("source") or {}).get("domain")
                    or (row.get("source") or {}).get("name"),
                    "published_at": (row.get("asserted") or {}).get("published_at"),
                    "cited_in": [],
                }
            if where and where not in index[aid]["cited_in"]:
                index[aid]["cited_in"].append(where)

    # Sections, in the order they render, with the card path labelled.
    for section in edition.get("sections") or []:
        if not isinstance(section, dict):
            continue
        entries = section.get("types")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for card in entry.get("cards") or []:
                    if isinstance(card, dict):
                        _take(card.get("article_rows") or [], _where(section, entry, card))
        # Anything else in the section that names articles.
        for rows in _row_lists({k: v for k, v in section.items() if k != "types"}):
            _take(rows, _where(section, None, None))

    for story in (edition.get("stories") or {}).get("stories") or []:
        if not isinstance(story, dict):
            continue
        terms = ", ".join((story.get("shared_terms") or [])[:4]) or "story"
        _take(story.get("article_rows") or [], f"story · {terms}")

    # Stamp the refs back onto every row so the renderer can print them wherever the
    # article appears. Done in a second pass over the SAME walk, so a row can never
    # carry a number the index does not know.
    refs = {aid: f"{i + 1:04d}" for i, aid in enumerate(order)}
    for aid, ref in refs.items():
        index[aid]["ref"] = ref
    for rows in _row_lists(edition):
        for row in rows:
            if isinstance(row, dict) and row.get("id") is not None:
                got = refs.get(int(row["id"]))
                if got:
                    row["ref"] = got

    return [index[aid] for aid in order]


# --------------------------------------------------------------------------- #
#  the bundle
# --------------------------------------------------------------------------- #
DISCLOSURE = (
    "These files hold the STORED TEXT of articles published by other people, copied "
    "out of your corpus so that the citations in the report can be checked against "
    "what they cite. The report is your work; this is the material it draws on. Two "
    "consequences worth stating plainly: your corpus is encrypted at rest and this "
    "ZIP is not, so keep it where you keep the corpus; and whether you may pass these "
    "files on to someone else is a question about each publisher's terms rather than "
    "about this app — the report reads on its own, and the annexes are what you keep."
)

_AI_LABEL = "AI-derived — unreliable"


def _md_kv(T: Translator, label: str, value: Any) -> str:
    """A label:value line, with the LABEL translated and the value left alone.

    label:value is the shape that survives translation: nothing agrees with an
    interpolated number, so no locale has to conjugate around a value it cannot see.
    The value is data — a date, a domain, a count — and is never looked up.
    """
    return f"- **{T.t(label)}:** {value if value not in (None, '', []) else '—'}"


def _analysis_block(T: Translator, rows: list[dict]) -> list[str]:
    """Stored model output for one article, labelled and with its provenance.

    An analysis is shown with the model that wrote it, the prompt version and when —
    the same provenance the reader shows — because a paragraph of model text with no
    origin is indistinguishable from something the corpus contains.
    """
    if not rows:
        return []
    out = ["## " + T.t(_AI_LABEL), ""]
    out.append(
        "> " + T.t(
            "Written by a local model, not by the publisher and not by this app's "
            "deterministic layer. Kept here because you asked for it; it is not evidence "
            "of anything and the full text below is what the source actually said."
        )
    )
    out.append("")
    for r in rows:
        kind = str(r.get("kind") or "analysis")
        # The KIND is one of a small fixed set this app writes, so it is chrome and
        # keyable; the target language is the operator's own choice and is data.
        head = T.t(kind.title())
        if r.get("target_language"):
            head = T.f("{kind} into {language}", kind=head, language=r["target_language"])
        prov = ", ".join(
            p
            for p in (
                T.f("model {name}", name=f"`{r['model']}`") if r.get("model") else None,
                T.f("prompt {version}", version=f"`{r['prompt_version']}`")
                if r.get("prompt_version")
                else None,
                str(r["created_at"]) if r.get("created_at") else None,
            )
            if p
        )
        out += [f"### {head}", ""]
        if prov:
            out += [f"*{prov}*", ""]
        out += [str(r.get("result") or "").strip(), ""]
    return out


def article_markdown(
    row: dict,
    *,
    stem: str,
    body: str | None,
    analyses: list[dict],
    truncated_reason: str | None = None,
    tr: Translator | None = None,
) -> str:
    """One annex file: the two classes of fact, then the model text, then the source.

    The order is deliberate. What the publisher ASSERTED comes first because it is
    the only part they are answerable for; what this app DEDUCED comes next, under
    its own heading, because a keyword or a place is a measurement and not a claim
    the article made; the model's text is third and labelled; the article's own words
    are last and unedited.
    """
    T = tr or Translator("en")
    ref = str(row.get("ref") or "----")
    src = row.get("source") or {}
    asserted = row.get("asserted") or {}
    deduced = row.get("deduced") or {}
    sent = deduced.get("sentiment")

    out = [
        f"# {ref} · {row.get('title') or T.t('(untitled)')}",
        "",
        T.f("Annex to **{stem}**, cited there as `[{ref}]`.", stem=stem, ref=ref),
        "",
        "## " + T.t("What the source asserted"),
        "",
        _md_kv(T, "Published", asserted.get("published_at")),
        _md_kv(T, "Byline", asserted.get("author")),
        _md_kv(T, "Declared language", asserted.get("language")),
        _md_kv(
            T,
            "Source",
            " · ".join(
                str(x) for x in (src.get("name"), src.get("domain"), src.get("country"),
                                 src.get("source_type")) if x
            )
            or "—",
        ),
        _md_kv(T, "Original", row.get("url")),
        "",
        "## " + T.t("What this app deduced"),
        "",
        "> " + T.t(
            "Measurements over the text, never confirmed. A place name is a surface form "
            "the extractor does not disambiguate; a mentioned date is a candidate no human "
            "has checked unless it says otherwise."
        ),
        "",
        _md_kv(T, "Collected", deduced.get("collected_at")),
        _md_kv(T, "Detected language", deduced.get("detected_language")),
        _md_kv(T, "Words", deduced.get("word_count")),
        _md_kv(T, "Reading time (min)", deduced.get("reading_time")),
        _md_kv(
            T,
            "Sentiment",
            # The label and the basis are ours; the score is the measurement. The
            # ABSENCE has to say why in the reader's language, or an English sentence
            # in a French annex reads as a broken field rather than as a stated gap.
            f"{sent.get('label')} ({sent.get('score')}) — {sent.get('basis')}"
            if sent
            else T.t(
                "not measured — the lexicon reads English only, so its absence is not a "
                "neutral reading"
            ),
        ),
        _md_kv(
            T,
            "Keywords",
            ", ".join(f"{k.get('term')} ({k.get('mentions')})" for k in row.get("keywords") or [])
            or None,
        ),
        _md_kv(
            T,
            "Places mentioned",
            ", ".join(
                f"{p.get('name')}"
                + (f" [{p.get('country')}]" if p.get("country") else "")
                for p in row.get("places") or []
            )
            or None,
        ),
        _md_kv(
            T,
            "Dates mentioned",
            ", ".join(
                f"{d.get('date')} ({d.get('status')})" for d in row.get("dates") or []
            )
            or None,
        ),
        _md_kv(
            T,
            "Entities",
            ", ".join(
                f"{e.get('name')} ({e.get('class')})" for e in row.get("entities") or []
            )
            or None,
        ),
        "",
    ]
    out += _analysis_block(T, analyses)

    out += ["## " + T.t("The article, as stored"), ""]
    if body:
        if truncated_reason:
            out += [f"> {truncated_reason}", ""]
        out += [body.strip(), ""]
    else:
        out += [
            "*" + T.t(
                "No text is included for this article. It may hold none, its stored text "
                "may not have been readable, or it may have been quarantined or removed "
                "since this edition was built — the file is here so the report's reference "
                "resolves, and the gap is stated rather than left blank."
            ) + "*",
            "",
        ]
    return "\n".join(out)


def _shortfall(T: Translator, state: dict | None = None) -> list[str]:
    """What this bundle owes its reader about its OWN language, or nothing.

    DERIVED, never a standing claim. The sentence this replaced said the annexes had
    no translation yet; once they had one it would have gone on saying so, and a
    caveat that is false is worse than none. So it is computed from what the render
    actually resolved: nothing missing and nothing refused means nothing to disclose.

    Written LAST, after every sentence in the page has been asked for, or it would
    report a shortfall measured before most of the page existed. English gets no line
    -- it is the source, so there is no gap to describe.
    """
    r = T.report()
    n = r["strings_seen"]
    english = 0 if T.is_english else r["missing"] + r["rejected"]
    # Recorded for the CALLER before the line below registers its own frames. Otherwise
    # the returned figure counts them and the dict disagrees with the page it describes
    # by exactly one -- the same drift the report's disclosure line is memoised against.
    if state is not None:
        state["chrome_strings"] = n
        state["chrome_in_english"] = english
    if T.is_english or not n or not english:
        return []
    return [
        "> " + T.f(
            "**{n} of {total} sentences on these pages are printed in English**, having "
            "no {language} translation yet. Settings → Advanced → Diagnostics → *Bulletin "
            "language & render* names every one of them.",
            n=f"{english:,}",
            total=f"{n:,}",
            language=T.language_name(),
        ),
        "",
    ]


def contents_markdown(
    edition: dict,
    index: list[dict],
    *,
    stem: str,
    analyses_by_id: dict[int, list[dict]],
    full_text: bool,
    truncated_from: int | None,
    report_lang: str = "en",
    tr: Translator | None = None,
    state: dict | None = None,
) -> str:
    """The contents page: what is here, how the numbers work, and what is missing.

    ``report_lang`` names the language the whole bundle is written in — the annexes
    follow the report rather than staying English, so the two no longer differ by
    construction. What this page still owes its reader is the SHORTFALL when one
    exists, and that sentence is now DERIVED from the translator's own report: a
    static "the annexes have no translation yet" would keep saying so after they were
    translated, which is the class of stale claim this module is careful about.

    The article text itself is never translated in any language — it is the
    publisher's own words, and that stays true whatever the chrome is in.
    """
    summaries = sum(
        1 for e in index if any(a.get("kind") == "summary" for a in analyses_by_id.get(e["id"], []))
    )
    translations = sum(
        1
        for e in index
        if any(a.get("kind") == "translation" for a in analyses_by_id.get(e["id"], []))
    )
    m = edition.get("masthead") or {}
    p = edition.get("period") or {}

    T = tr or Translator(report_lang)
    out = [
        "# " + T.f("Annexes — {stem}", stem=stem),
        "",
        f"> **{T.t(DISCLOSURE)}**",
        "",
        # Always stated, in every language, because it is the one fact about this
        # bundle that translation does NOT change: the chrome follows the report, the
        # publisher's words never do.
        "> " + T.t(
            "Every article's own text, title and byline are the publisher's words and "
            "are never translated here, in any language."
        ),
        "",
    ]
    out += [
        "## " + T.t("How the numbering works"),
        "",
        T.t(
            "A bracketed number in the report — `[0001]` — is one file here. One number "
            "per article: an article the report cites in two places keeps one number and "
            "has one file. The numbers run in the order a reader meets them in the report."
        ),
        "",
        T.f(
            "Each file is named for the day its article was **published** — `{dated}` — so "
            "a piece from years ago reads as years ago rather than as the day this bundle "
            "was made. An article the publisher gave no date is named `{undated}`; the "
            "collection date is not substituted for a publication date. So the filename "
            "cannot be worked out from the number alone, and the table below is where the "
            "two are matched.",
            dated=article_filename("2026-08-05", "0001"),
            undated=article_filename(None, "0001"),
        ),
        "",
        "## " + T.t("What is in this bundle"),
        "",
        _md_kv(
            T,
            "Report",
            f"`{stem}.md`  ({T.t('downloaded beside this ZIP, not inside it')})",
        ),
        # "Period covered" rather than "Period": the bare word is already keyed for a
        # sentence in the report, where at least one locale renders it as a genitive
        # fragment ("de la période"). A label needs the standalone form, so it needs
        # its own key -- one English word in two roles cannot share one slot.
        # ONE frame for the whole range, the way the report's own title does it: the
        # connector between two dates is a word, and a locale that reads right to left
        # needs it inside the sentence it is translating rather than welded in English
        # between two values.
        _md_kv(
            T,
            "Period covered",
            T.f(
                "{start} to {last} ({days} days)",
                start=p.get("start") or "—",
                last=p.get("last_day") or "—",
                days=p.get("days", "—"),
            ),
        ),
        # The cadence VALUE is one of a small fixed set this app writes, so it is chrome
        # and already keyed for the report's own title -- reused rather than re-keyed.
        _md_kv(T, "Cadence", T.t(str(p.get("cadence") or "").capitalize()) or None),
        _md_kv(T, "Articles cited by the report", f"{len(index):,}"),
        _md_kv(
            T,
            "Out of the period's collected articles",
            f"{m['articles']:,}" if isinstance(m.get("articles"), int) else "—",
        ),
        _md_kv(T, "With a stored model summary", f"{summaries:,}"),
        _md_kv(T, "With a stored model translation", f"{translations:,}"),
        _md_kv(
            T,
            "Article text",
            T.t("full stored text")
            if full_text
            else T.t("EXCERPT ONLY — this bundle was built without full text"),
        ),
        _md_kv(T, "Built", datetime.now(UTC).isoformat()),
        "",
    ]
    if truncated_from is not None:
        out += [
            "> " + T.f(
                "**Not every file carries the full text.** The bundle reached its text "
                "budget after {n} articles; the rest carry the excerpt the report shows, "
                "and each says so at the top of its own text section. This is stated "
                "because a bundle silently holding excerpts where it promised full text "
                "would be worse than a large download.",
                n=f"{truncated_from:,}",
            ),
            "",
        ]
    if not index:
        out += [
            "## " + T.t("No articles"),
            "",
            T.t(
                "The report for this period names no articles, so there is nothing to "
                "annex. That happens when an edition was built before the document carried "
                "article metadata, or when every section it produced is an aggregate. "
                "Regenerating the edition will populate it."
            ),
            "",
        ]
        out += _shortfall(T, state)
        return "\n".join(out)

    # The header cells are translated ONE WORD AT A TIME and the row is composed here:
    # a whole-row key would put the table's pipes inside a translation, where one lost
    # or added bar silently breaks the table for every reader of that locale.
    head = [
        "#",
        T.t("file"),
        T.t("title"),
        T.t("source"),
        T.t("published"),
        T.t("cited in"),
    ]
    out += [
        "## " + T.t("Articles"),
        "",
        "| " + " | ".join(head) + " |",
        "|" + "---|" * len(head),
    ]
    for e in index:
        cited = "; ".join(e.get("cited_in") or []) or "—"
        title = str(e.get("title") or "(untitled)").replace("|", "\\|")
        out.append(
            f"| `{e['ref']}` | `{article_filename(e.get('published_at'), e['ref'])}` | "
            f"{title} | {e.get('source') or '—'} | {e.get('published_at') or '—'} | {cited} |"
        )
    out.append("")
    out += _shortfall(T, state)
    return "\n".join(out)


def build_annexes(
    session,
    edition: dict,
    *,
    ordinal: int = 1,
    full_text: bool = True,
    text_budget_bytes: int = DEFAULT_TEXT_BUDGET_BYTES,
    report_lang: str = "en",
) -> dict:
    """Build the annexes ZIP in memory. Returns ``{filename, data, ...}``.

    In memory on purpose: the set is the report's citation list, not the period, so
    it is measured in megabytes and goes straight down a browser connection. The
    evidence archive is the one that streams to a directory, because that one is the
    whole corpus.

    A body that cannot be read leaves its file in place with the gap stated — the
    reference must resolve even when the text does not.
    """
    from src.bulletin.articles import article_analyses, article_bodies

    # ONE translator for the whole bundle. Shared on purpose: the contents page is
    # written last and its shortfall line counts what the ARTICLE files asked for too,
    # so a per-file translator would report a gap measured over one file.
    T = Translator(report_lang)
    index = assign_refs(edition)
    stem = bundle_stem(edition, ordinal=ordinal)
    ids = [e["id"] for e in index]

    bodies: dict[int, str] = {}
    analyses: dict[int, list[dict]] = {}
    if ids:
        try:
            analyses = article_analyses(session, ids)
        except Exception:  # noqa: BLE001 - the bundle survives a missing analysis layer
            _LOG.warning("bulletin: annex analyses unreadable", exc_info=True)
        if full_text:
            try:
                bodies = article_bodies(session, ids)
            except Exception:  # noqa: BLE001
                _LOG.warning("bulletin: annex bodies unreadable", exc_info=True)

    # The rows themselves come from the RECORD, which already holds every fact the
    # edition computed over them. Re-deriving them here would let the annex and the
    # report disagree about an article they both describe.
    rows_by_id: dict[int, dict] = {}
    for rows in _row_lists(edition):
        for row in rows:
            if isinstance(row, dict) and row.get("id") is not None:
                rows_by_id.setdefault(int(row["id"]), row)

    # Filled by the contents page, which is where the shortfall sentence is composed:
    # the numbers this returns are the ones a reader saw, not a later re-measurement.
    lang_state: dict[str, int] = {}
    spent = 0
    truncated_from: int | None = None
    written: list[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, entry in enumerate(index):
            aid = entry["id"]
            row = rows_by_id.get(aid) or entry
            reason = None
            body = bodies.get(aid)
            if body is None or not full_text:
                # ``bodies`` omits an article only when its text could not be read, or
                # it has been quarantined or removed since the edition was built. Which
                # of those it was is not knowable from here, so the sentence names the
                # possibilities instead of picking one.
                body = row.get("excerpt") or ""
                if full_text:
                    reason = T.t(
                        "Excerpt only — the stored text is not in this bundle: it could not "
                        "be read, or the article has been quarantined or removed since this "
                        "edition was built."
                    ) if body else None
                elif row.get("excerpt_truncated"):
                    reason = T.t("Excerpt only — this bundle was built without full text.")
            # Measured in BYTES, not characters. The bound exists to cap memory, and
            # this corpus is strongly non-Anglophone — a character is one to four
            # bytes, so counting characters would make the real ceiling up to four
            # times the number the parameter is named for.
            elif spent + len(body.encode("utf-8")) > int(text_budget_bytes):
                if truncated_from is None:
                    truncated_from = n
                body = row.get("excerpt") or ""
                reason = T.t(
                    "Excerpt only — the bundle reached its text budget before this "
                    "article. The contents page says how many files this affects."
                )
            else:
                spent += len(body)
            name = f"{stem}/{article_filename(entry.get('published_at'), entry['ref'])}"
            zf.writestr(
                name,
                article_markdown(
                    row,
                    stem=stem,
                    body=body,
                    analyses=analyses.get(aid, []),
                    truncated_reason=reason,
                    tr=T,
                ),
            )
            written.append(name)

        # Written LAST because it reports what the loop above actually did.
        zf.writestr(
            f"{stem}/{contents_filename(edition)}",
            contents_markdown(
                edition,
                index,
                stem=stem,
                analyses_by_id=analyses,
                full_text=full_text,
                truncated_from=truncated_from,
                report_lang=report_lang,
                tr=T,
                state=lang_state,
            ),
        )

    data = buf.getvalue()
    return {
        "filename": annexes_filename(edition, ordinal=ordinal),
        "report_filename": report_filename(edition, ordinal=ordinal),
        "data": data,
        "bytes": len(data),
        "articles": len(index),
        "files": len(written) + 1,
        "full_text": bool(full_text),
        "text_truncated_from": truncated_from,
        "disclosure": T.t(DISCLOSURE),
        # Measured, not assumed: which language the chrome came out in and how much of
        # it fell back to English. A caller that wants to tell an operator "your annexes
        # are French" needs the second number to know whether that is true.
        "language": T.lang,
        "chrome_strings": lang_state.get("chrome_strings", 0),
        "chrome_in_english": lang_state.get("chrome_in_english", 0),
    }
