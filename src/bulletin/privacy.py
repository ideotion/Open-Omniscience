"""
What a reader of an exported artifact can see — design record §18.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

§18 asks for one thing before a first archive leaves a machine: an ENUMERATION.
Not a scrubber, not a policy — a list of what a recipient can read off the file,
stated where the operator clicks, so exporting is a decision made with the facts
rather than a button pressed on trust.

WHY A KEY-BASED SCRUBBER IS NOT THE ANSWER, and §18 says so itself: every item
below is legitimate content under an innocuous key. `title` is a headline and, for
an imported newsletter, a subject line that names a subscription. `url` is a link
and, for a hazard feed, a synthetic address that says which verticals this install
runs. A filter over key names cannot tell those apart; a reader looking at the file
can. So the mechanism is disclosure, and the disclosure is measured against THIS
export rather than described in general.

THREE HONESTY RULES THIS FILE OBEYS, and each has cost this project something
elsewhere:

* **``present`` is TRI-STATE.** ``True`` means measured and there; ``False`` means
  measured and absent; ``None`` means NOT MEASURED. An unmeasured item that
  reported ``False`` would be a fabricated all-clear, which is the ``.get(key, 0)``
  family wearing a privacy label — and here it would tell an operator that
  something is not in a file they are about to hand to someone.
* **A count is exact and a cap bounds only EXAMPLES.** Every ``n`` here is a real
  count over the population that will actually leave; ``examples`` is a bounded
  illustration and says which it is.
* **A vocabulary-derived rate is a FLOOR.** The synthetic-URI count is computed
  from the schemes this app is known to mint, so a scheme added later is invisible
  to it until it is added here. It is published as a floor rather than a total.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func

from src.database.models import Article, Source

_LOG = logging.getLogger(__name__)

#: The three artifacts that can leave this machine, and how they differ.
#: ``report`` is the published document; ``annexes`` the ZIP whose files its
#: reference numbers resolve to; ``evidence`` the owner-only archive of the whole
#: period. They carry different things, so the enumeration is per artifact rather
#: than one general list a reader would have to apply themselves.
KINDS = ("report", "annexes", "evidence")

#: URL schemes this app MINTS for things that were never fetched from a web
#: address. Their presence in an export says which verticals the install runs.
#: A FLOOR: a scheme added later is invisible here until it is added here, which
#: is why the item publishes ``basis`` rather than implying a total.
SYNTHETIC_SCHEMES = ("hazard://",)

#: Domains this app mints for locally-imported material. `newsletters.import.local`
#: is the .eml import bucket, so an article under it carries a SUBJECT LINE as its
#: title — which names a subscription, and is exactly the §18 item.
LOCAL_IMPORT_DOMAINS = ("newsletters.import.local", "mailbox.import.local")

_CAVEAT = (
    "This lists what a READER of the exported file can see. It is not a security "
    "boundary and nothing here is removed for you: the exports are plaintext, and "
    "every item below is legitimate content that no filter over field names could "
    "tell from ordinary data. An item reported as not measured is NOT an item "
    "reported as absent."
)

_METHOD = (
    "measured against the exact set of articles this export would carry, on this "
    "corpus, at this moment; counts are exact and examples are a bounded "
    "illustration of them"
)


def _item(
    key: str,
    what: str,
    why: str,
    *,
    present: bool | None,
    basis: str,
    n: int | None = None,
    examples: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": key,
        "what": what,
        # What a recipient can INFER, which is the part an operator is actually
        # deciding about. "Source names" is not the disclosure; "which publications
        # this person reads" is.
        "why_it_matters": why,
        "present": present,
        "basis": basis,
    }
    if n is not None:
        row["n"] = int(n)
    if examples:
        row["examples"] = list(examples)
        row["examples_are_bounded"] = True
    return row


def _count_and_examples(session, ids: list[int], where, column, *, join_source=False, limit=3):
    """An exact count over ``ids``, plus a few examples of ``column``.

    The COUNT is over the whole set; the examples are the first few. Separated
    deliberately — a displayed figure is never secretly a cap.

    ``join_source`` is not optional bookkeeping: a predicate over ``Source`` with no
    join is a CARTESIAN PRODUCT, so the count comes back as articles times matching
    sources. SQLAlchemy warns about it and the number still looks plausible, which
    is exactly how a privacy figure would ship wrong.
    """
    if not ids:
        return 0, []
    n = 0
    examples: list[str] = []
    # Chunked so a large period never builds one enormous IN (...) clause.
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        q = session.query(column)
        if join_source:
            q = q.join(Source, Article.source_id == Source.id)
        rows = q.filter(Article.id.in_(chunk)).filter(where).all()
        n += len(rows)
        for r in rows:
            if len(examples) < limit and r[0]:
                examples.append(str(r[0]))
    return n, examples


def export_privacy(
    session,
    edition: dict,
    *,
    kind: str,
    article_ids: list[int] | None = None,
    full_text: bool = True,
) -> dict[str, Any]:
    """The §18 enumeration for one export of one edition.

    ``article_ids`` is the population that will actually leave — the period's
    articles for an evidence archive, the cited ones for an annexes bundle. When it
    is None the per-article items report NOT MEASURED rather than absent, because
    "we did not look" and "there are none" are opposite answers and only one of
    them is safe to act on.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown export kind {kind!r}; expected one of {KINDS}")

    head = edition.get("masthead") or {}
    ids = list(article_ids) if article_ids is not None else None
    measured = ids is not None
    unmeasured_basis = (
        "not measured — this call was not told which articles the export carries, "
        "so this is an unanswered question rather than a clean answer"
    )

    items: list[dict[str, Any]] = []

    # 1. Source names and domains -------------------------------------------- #
    top = head.get("top_sources") or []
    items.append(
        _item(
            "source_names_and_domains",
            "The names and domains of the sources that contributed.",
            "Together they are this operator's reading list: which publications, in "
            "which countries, in which languages.",
            present=True,
            basis=(
                "the masthead names the largest contributors in every export; the "
                "evidence archive additionally carries every contributing source in "
                "sources.json"
                if kind == "evidence"
                else "the masthead names the largest contributors"
            ),
            n=head.get("sources_contributing"),
            examples=[str(s.get("domain")) for s in top[:3] if s.get("domain")],
        )
    )

    # 2. Article ids and corpus totals ---------------------------------------- #
    # The REPORT carries no local ids by construction (§9.2): a local id resolves to
    # a different article on a recipient's install, so published output links only
    # to original URLs. The other two artifacts are files, and they do carry them.
    items.append(
        _item(
            "article_ids_and_corpus_totals",
            "This install's own article numbers, and how many articles it holds.",
            "The totals are a lower bound on the size of this archive; across "
            "several editions they give its growth rate. The ids mean nothing on "
            "another machine, which is why the published document carries none.",
            present=kind != "report",
            basis=(
                "the published document carries external links only (§9.2), so it "
                "names no local id; the masthead's corpus total is in every export"
                if kind == "report"
                else "one file per article, named by this install's own id"
            ),
            n=head.get("corpus_articles"),
        )
    )

    # 3. App version ---------------------------------------------------------- #
    # MEASURED, not assumed. The edition record has never carried one, and saying
    # "absent" without looking would be the same fabricated all-clear this file
    # exists to avoid.
    version = edition.get("app_version") or edition.get("version")
    items.append(
        _item(
            "app_version",
            "The version of this app that produced the edition.",
            "A version is a weak install fingerprint: it narrows which build a "
            "recipient is looking at, and across several exports it tracks upgrades.",
            present=bool(version),
            basis=(
                f"the edition record carries app_version {version!r}"
                if version
                else "the edition record carries no version field, checked rather than assumed"
            ),
        )
    )

    # 4. Newsletter subject lines --------------------------------------------- #
    if measured:
        n_news, ex_news = _count_and_examples(
            session,
            ids or [],
            Source.domain.in_(LOCAL_IMPORT_DOMAINS),
            Article.title,
            join_source=True,
        )
        news_present: bool | None = n_news > 0
        news_basis = (
            "articles whose source is a local .eml/mailbox import bucket; their "
            "titles ARE the subject lines"
        )
    else:
        n_news, ex_news, news_present, news_basis = None, [], None, unmeasured_basis
    items.append(
        _item(
            "newsletter_subject_lines",
            "The subject lines of newsletters imported from local mail.",
            "A subject line names a subscription, and a list of them describes what "
            "this person has signed up to receive — which no web source reveals.",
            present=news_present,
            basis=news_basis,
            n=n_news,
            examples=ex_news,
        )
    )

    # 5. Synthetic URIs -------------------------------------------------------- #
    if measured:
        clauses = [Article.url.startswith(s) for s in SYNTHETIC_SCHEMES]
        where = clauses[0]
        for extra in clauses[1:]:
            where = where | extra
        n_syn, ex_syn = _count_and_examples(session, ids or [], where, Article.url)
        syn_present: bool | None = n_syn > 0
        syn_basis = (
            "article URLs whose scheme is one this app mints rather than fetches "
            f"({', '.join(SYNTHETIC_SCHEMES)}). A FLOOR: a scheme added later is "
            "invisible to this count until it is added to SYNTHETIC_SCHEMES."
        )
    else:
        n_syn, ex_syn, syn_present, syn_basis = None, [], None, unmeasured_basis
    items.append(
        _item(
            "synthetic_uris",
            "Addresses this app minted for things it did not fetch from the web.",
            "They say which verticals this install runs — hazard feeds, imported "
            "mail — which is a fact about the operator's setup, not about the news.",
            present=syn_present,
            basis=syn_basis,
            n=n_syn,
            examples=ex_syn,
        )
    )

    # 6. Signing key ----------------------------------------------------------- #
    # §18's sharpest item, and the answer today is that it does not arise: nothing
    # in the bulletin path signs anything. Recorded as measured-absent WITH the
    # condition that would change it, so the next person to add a signature meets
    # the requirement rather than rediscovering it.
    items.append(
        _item(
            "signing_key",
            "A public key identifying this install, if editions were signed.",
            "A signature proves who made a document — and the same key on every "
            "edition is a persistent identifier for this install across every "
            "recipient, which is the opposite of what most operators expect a "
            "signature to cost them.",
            present=False,
            basis=(
                "nothing in the bulletin export path signs anything today, so no key "
                "travels. IF signing is ever added: either use a per-edition "
                "ephemeral key, or state the trade-off here, because a shared "
                "long-lived key links every recipient's copy to the same install."
            ),
        )
    )

    # 7. Timestamps ------------------------------------------------------------ #
    items.append(
        _item(
            "timestamps_and_timezone",
            "Generation and collection times, at the machine's own offset.",
            "Collection times cluster around when this operator's machine is awake, "
            "so a run of them narrows a timezone and, over a period, a routine.",
            present=True,
            basis=(
                "the document footer carries generated_at; the annexes and the "
                "evidence archive additionally carry each article's collected_at"
                if kind != "report"
                else "the document footer carries generated_at"
            ),
        )
    )

    # 8. Publishers' full text -------------------------------------------------- #
    # The item that carries an OPEN QUESTION rather than an answer (see the note
    # below): whether redistributing stored full text is the operator's to do is a
    # question about each publisher's terms, and it is the maintainer's to rule on.
    if kind == "report":
        text_present: bool | None = False
        text_basis = "the document carries bounded excerpts, never a stored article in full"
    elif kind == "annexes":
        text_present = bool(full_text)
        text_basis = (
            "full_text is ON for this bundle, so each annex carries its article's "
            "whole stored text"
            if full_text
            else "full_text is OFF for this bundle, so each annex carries metadata "
            "and an excerpt"
        )
    else:
        text_present = True
        text_basis = "the evidence archive carries every article's whole stored text, by design"
    items.append(
        _item(
            "publisher_full_text",
            "The full stored text of articles this operator did not write.",
            "A file that travels carries someone else's words in full. Whether that "
            "is the operator's to pass on is a question about each publisher's "
            "terms — this app states that the text is there and does not answer it.",
            present=text_present,
            basis=text_basis,
            n=len(ids) if (ids is not None and text_present) else None,
        )
    )

    unmeasured = [i["key"] for i in items if i["present"] is None]
    return {
        "schema": "oo-bulletin-export-privacy-1",
        "kind": kind,
        "items": items,
        "items_total": len(items),
        # Counted apart from "absent", and named, so a reader can see WHICH question
        # went unanswered rather than inferring a clean bill of health from a total.
        "unmeasured": unmeasured,
        "unmeasured_count": len(unmeasured),
        "articles_measured": len(ids) if ids is not None else None,
        "method": _METHOD,
        "caveat": _CAVEAT,
    }


def privacy_markdown(report: dict) -> str:
    """The enumeration as Markdown, for the inside of an exported archive.

    It travels WITH the file rather than only appearing in the app, because the
    operator who exported it is not always the person who later opens it — and by
    then the panel that stated this is somewhere else entirely.
    """
    out = [
        "# What a reader of this file can see",
        "",
        f"> {report.get('caveat', '')}",
        "",
        f"Measured for: **{report.get('kind')}**. "
        f"Method: {report.get('method')}.",
        "",
        "| what | in this export | how we know | why it matters |",
        "|---|---|---|---|",
    ]
    for item in report.get("items") or []:
        present = item.get("present")
        mark = "yes" if present is True else ("no" if present is False else "NOT MEASURED")
        n = item.get("n")
        if n is not None:
            mark += f" ({n:,})"
        out.append(
            "| "
            + " | ".join(
                str(x).replace("|", "\\|").replace("\n", " ")
                for x in (item.get("what"), mark, item.get("basis"), item.get("why_it_matters"))
            )
            + " |"
        )
    if report.get("unmeasured"):
        out += [
            "",
            "**Not measured:** "
            + ", ".join(report["unmeasured"])
            + ". An unanswered question is not a clean answer.",
        ]
    return "\n".join(out) + "\n"


def period_article_count(session, period) -> int:
    """How many articles an evidence archive for ``period`` would carry.

    Reuses the archive's OWN selector rather than restating its predicate, so the
    enumeration can never describe a different population than the one that will be
    written — a second copy of a WHERE clause is how two surfaces come to disagree
    about one number.
    """
    from src.bulletin.evidence import _period_article_ids

    return len(_period_article_ids(session, period))


def quarantined_in_period(session, period) -> int | None:
    """Quarantined articles in the period — excluded from every export, counted.

    Returns ``None`` when it cannot be counted, never 0: an unreadable count and an
    empty one are different facts.
    """
    from datetime import datetime

    from sqlalchemy import and_

    clock = func.coalesce(Article.published_at, Article.created_at)
    lo = datetime.combine(period.start, datetime.min.time())
    hi = datetime.combine(period.end, datetime.min.time())
    try:
        return int(
            session.query(func.count(Article.id))
            .filter(and_(clock >= lo, clock < hi, Article.quarantined.is_(True)))
            .scalar()
            or 0
        )
    except Exception:  # noqa: BLE001 - an unreadable count is unknown, never zero
        _LOG.warning("bulletin: could not count quarantined articles", exc_info=True)
        return None
