"""
Rendering an edition — Markdown and a self-contained HTML page.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §10 (output and delivery), §11 (masthead, sections, references),
§12 (published artifacts carry EXTERNAL links only).

PURE. Renders take the persisted edition dict and return text — no DB, no model,
no network. That is what makes "re-render" safe: the numbers came from the
record, so a render cannot change one. It is also why toggling a producer
re-renders rather than re-computes.

THREE RULES the renderers enforce, not the caller:

* **Every link is EXTERNAL.** A local reader link (`/api/articles/{id}/view`)
  resolves to a DIFFERENT article on a recipient's install — the same id means
  something else in their corpus. Published output therefore links only to the
  original source URL, and where none exists it prints no link at all rather than
  one that lies.
* **Caveats are rendered, not summarised.** Each section's own caveat is printed
  with it. A document that drops them reads as more certain than the data is.
* **Model sentences are marked where they appear.** Not once in a footer — beside
  the prose, because that is where the reader is when it matters.

The HTML is self-contained: no external stylesheet, no font, no script, no
tracking pixel. A shared document that phones home would tell its recipient's
network what the operator reads.

LANGUAGE. Every sentence this file composes goes through a ``Translator`` — as a
whole sentence (``T.t``) or as a frame with named holes (``T.f``), never as
concatenated fragments, because a fragment is not a keyable unit and cannot be
translated into a language whose word order differs. The prose the nine computing
modules STORE in the record (their methods and caveats) is translated at its print
site by the same exact-match rule, which is why those modules needed no change.
``lang="en"`` is byte-identical to what this renderer produced before the layer
existed: ``Translator.t`` returns its input and ``Translator.f`` formats the frame
it was given.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

from src.bulletin.i18n import Translator

_AI_LABEL = "AI-derived — unreliable"


def _fmt(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _listed(
    rows: list[dict], *, limit: int, label: str, count_key: str = "articles", T: Translator
) -> tuple[list[dict], str]:
    """The rows a document can carry, and an exact account of the rest.

    A document has to be readable, so a long tail is not printed. What must never
    happen is the printed head reading as the whole: this renderer showed 8 of 114
    source countries and 8 of 34 languages with nothing to say the other 106 and 26
    existed, which turns "a country absent here was not collected from" — the
    masthead's own caveat — into a statement the page cannot support.

    The LIST is bounded. The TOTALS are exact and stated.
    """
    total = len(rows)
    if total <= limit:
        return rows, ""
    rest = rows[limit:]
    carried = sum(int(r.get(count_key) or 0) for r in rest)
    return rows[:limit], T.f(
        " ({limit} of {total} shown; the other {rest} {label} {carried} in total)",
        limit=limit,
        total=total,
        rest=total - limit,
        label=label,
        carried=_fmt(carried),
    )


def _title(edition: dict, T: Translator) -> str:
    p = edition.get("period") or {}
    cadence = T.t(str(p.get("cadence", "period")).capitalize())
    return T.f(
        "{cadence} bulletin — {start} to {end}",
        cadence=cadence,
        start=p.get("start", "?"),
        end=p.get("last_day", "?"),
    )


# --------------------------------------------------------------------------- #
#  Markdown
# --------------------------------------------------------------------------- #


def _ref_legend(edition: dict, T: Translator) -> list[str]:
    """Number the cited articles and explain the numbers, or say nothing.

    ``assign_refs`` is called HERE rather than by the route, and by the annexes
    builder too. It is deterministic over a record, so two callers cannot produce
    two numberings — which is the whole reason it is not left to each of them to
    remember. A record that names no article gets no legend and no numbers, because
    a legend for a convention the document never uses is furniture.
    """
    from src.bulletin.annexes import assign_refs

    n = len(assign_refs(edition))
    if not n:
        return []
    return [
        T.f(
            "A number like `[0001]` beside an article is its annex file — {n} of them, "
            "one per article this report cites, in the companion `…_Annexes.zip`. The number "
            "identifies the article, so an article cited twice keeps one number. Each file is "
            "named for the day its article was PUBLISHED, not for this report, so look the "
            "number up in the bundle's contents page to find its filename.",
            n=f"{n:,}",
        ),
        "",
    ]


def render_markdown(edition: dict, *, lang: str = "en", tr: Translator | None = None) -> str:
    """The edition as Markdown. Every figure comes from the record.

    ONE side effect, stated rather than left to be found: ``_ref_legend`` stamps a
    reference number onto each row that names an article, in memory. It is
    deterministic over a given record and never written back — the routes read a
    fresh dict from disk — so re-rendering still cannot change a number. The earlier
    word for this was "pure", which was true of the figures and not of the object.

    ``tr`` lets a caller own the translator and read its report afterwards, which is
    how the bulletin-language diagnostic measures a real edition rather than a guess.
    """
    T = tr or Translator(lang)
    p = edition.get("period") or {}
    m = edition.get("masthead") or {}
    out: list[str] = [f"# {_title(edition, T)}", ""]

    # The framing verb is "what ROSE in this corpus", never "what trended" — and
    # the lens is stated in the same breath, which is the point of the masthead.
    out += [
        T.f(
            "What rose in this corpus between **{start}** and **{end}** ({days} days).",
            start=p.get("start"),
            end=p.get("last_day"),
            days=p.get("days"),
        ),
        "",
    ]
    # The language line goes HERE, above the first figure, and is written after the
    # body so it can count what the body actually asked for. A reader meeting an
    # English caveat under a French heading is owed the reason before the caveat.
    lang_at = len(out)
    out += [
        f"## {T.t('This corpus, this period')}",
        "",
        T.f(
            "- **{articles}** articles, from **{sources}** sources that actually contributed",
            articles=_fmt(m.get("articles")),
            sources=_fmt(m.get("sources_contributing")),
        ),
        T.f(
            "- The three largest sources carried **{share}** of them",
            share=_pct(m.get("top_3_share")),
        ),
        T.f(
            "- Ingest on **{days}** of the period's {total} days",
            days=m.get("days_with_ingest", "—"),
            total=m.get("period_days", "—"),
        ),
        T.f(
            "- **{share}** of a corpus of {total}",
            share=_pct(m.get("corpus_share")),
            total=_fmt(m.get("corpus_articles")),
        ),
        "",
    ]

    for line in _masthead_splits(m, T):
        out += [line, ""]
    if m.get("caveat"):
        out += [f"> {T.t(m['caveat'])}", ""]
    out += _ref_legend(edition, T)

    for section in edition.get("sections") or []:
        out += _md_section(section, T)

    stories = (edition.get("stories") or {}).get("stories") or []
    if stories:
        out += [f"## {T.t('Stories')}", ""]
        for s in stories:
            out += _md_story(s, T)
        if (edition.get("stories") or {}).get("caveat"):
            out += [f"> {T.t(edition['stories']['caveat'])}", ""]

    out += _md_worklist(edition, T)
    out += _md_references(edition, T)
    out += [f"## {T.t('Methods & caveats')}", ""]
    if edition.get("method"):
        out += [T.t(edition["method"]), ""]
    if edition.get("caveat"):
        out += [f"> {T.t(edition['caveat'])}", ""]
    out += _md_disclosures(edition, T)
    out += [
        "---",
        "",
        T.f(
            "Generated {when} by Open Omniscience. Deterministic sections are computed "
            "from this operator's own corpus; the record they come from is `{record}`.",
            when=edition.get("generated_at") or datetime.now(UTC).isoformat(),
            record=edition.get("filename", "the edition JSON"),
        ),
    ]
    disclosure = T.disclosure()
    if disclosure:
        out[lang_at:lang_at] = [f"*{disclosure}*", ""]
    return "\n".join(out)


def _masthead_splits(m: dict, T: Translator) -> list[str]:
    """The masthead's per-day, per-channel, per-language and per-country splits.

    SHARED, for the reason ``_section_groups`` is: the two renderers had their own
    masthead and drifted, so the HTML page carried four bullet points and none of
    these lines at all. One function means the page a recipient opens and the file
    an operator keeps say the same thing.

    The channel split is the one to read first. It is the difference between a week
    of news and a week of one journal's back catalogue, and it had been computed and
    thrown away since the masthead was written: in the field edition, 407 scientific
    articles out of 72,225 are what put nineteen mitochondrial-fission terms at the
    top of the rising section.
    """
    lines: list[str] = []
    days = m.get("articles_by_day") or []
    if days:
        parts = [f"{str(r['day'])[5:]} {_fmt(r['articles'])}" for r in days]
        lines.append(T.f("By day: {parts}.", parts=", ".join(parts)))

    channels = m.get("channels") or []
    if channels:
        shown, tail = _listed(channels, limit=10, label=T.t("carried"), T=T)
        parts = [f"{T.t(str(r['source_type']))} {_fmt(r['articles'])}" for r in shown]
        lines.append(T.f("Channels: {parts}{tail}.", parts=", ".join(parts), tail=tail))

    langs = m.get("languages") or []
    if langs:
        shown, tail = _listed(langs, limit=16, label=T.t("carried"), T=T)
        parts = [f"{r['language'] or T.t('untagged')} {_fmt(r['articles'])}" for r in shown]
        lines.append(T.f("Languages: {parts}{tail}.", parts=", ".join(parts), tail=tail))

    countries = m.get("source_countries") or []
    if countries:
        shown, tail = _listed(countries, limit=20, label=T.t("carried"), T=T)
        parts = [f"{r['country']} {_fmt(r['articles'])}" for r in shown]
        unl = m.get("source_unlocated_articles") or 0
        unlocated = (
            T.f("; {n} from sources with no country recorded", n=_fmt(unl)) if unl else ""
        )
        lines.append(
            T.f(
                "Source countries: {parts}{tail}{unlocated}.",
                parts=", ".join(parts),
                tail=tail,
                unlocated=unlocated,
            )
        )
    return lines


def _channel_of(row: dict, T: Translator) -> str:
    """Where an across-channels row was first seen, ties intact.

    A tie is real: two channels can carry a concept on the same day and the
    mention clock is a date, so there is no finer order to appeal to. Printing
    one of them would invent a sequence the data does not contain.
    """
    tied = row.get("channels_tied") or []
    if tied:
        return T.f(
            "{channels} (tied)", channels=", ".join(T.t(str(c)) for c in tied)
        )
    channel = row.get("channel")
    return T.t(str(channel)) if channel else T.t("no channel recorded")


def _is_ratio(row: dict) -> bool | None:
    """Is this row's ``growth`` a measured ratio, or the no-baseline sentinel?

    ``queries.trending`` reports the recent COUNT in ``growth`` when the prior rate
    scaled to the window comes to less than one mention — a documented substitution
    with nothing to divide by. Told apart it is honest; conflated it is a fabricated
    magnitude, and this renderer conflated it: a field edition printed 5,701
    mentions against a prior of 4 as "×5701.0 vs the prior period", on 19 of its 20
    rows.

    Three states, because two would force a guess. ``None`` means the record does
    not say and cannot be asked — an old edition with neither the flag nor
    ``expected`` — and a row that cannot prove it is a ratio does not get to claim
    one. Editions written before the flag existed still carry ``expected``, which is
    what the flag is computed from, so re-rendering one is honest rather than
    faithful to the sentence it shipped with.
    """
    flag = row.get("growth_is_ratio")
    if flag is not None:
        return bool(flag)
    expected = row.get("expected")
    if expected is None:
        return None
    try:
        return float(expected) >= 1
    except (TypeError, ValueError):
        return None


def _term_row(row: dict, *, baseline_days: Any = None, T: Translator) -> tuple[str, str]:
    """A ``terms`` row as (term, description), chosen by the row's OWN fields.

    TWO sections emit a ``terms`` key with DIFFERENT shapes — rising concepts
    carry ``recent``/``growth``, across-channels carries ``first_seen``/
    ``channel`` — so dispatching on the key would render one of them through the
    other's sentence. It did: an across-channels row came out as
    "— — mentions (×None vs the prior period)", a line that means nothing. The
    row decides, not the container it arrived in.
    """
    term = str(row.get("term") or row.get("normalized") or "—")
    if "first_seen" in row:
        return term, T.f(
            "first seen {when} in {channel}",
            when=row.get("first_seen"),
            channel=_channel_of(row, T),
        )
    growth = row.get("growth")
    recent = _fmt(row.get("recent"))
    if growth is None:
        # No ratio computed — say the count and stop, rather than print "×None".
        return term, T.f("{n} mentions", n=recent)
    if _is_ratio(row) is False:
        # The sentinel. Say the two counts it stands between and name the reason;
        # the one thing not to do is dress the count as a multiple.
        prior = row.get("prior")
        window = (
            T.f("prior {days} days", days=baseline_days) if baseline_days else T.t("prior period")
        )
        if prior in (0, None):
            return term, T.f(
                "{n} mentions — new in this period, nothing prior to compare", n=recent
            )
        return (
            term,
            T.f(
                "{n} mentions, against {prior} in the {window} — too thin a baseline to divide by",
                n=recent,
                prior=_fmt(prior),
                window=window,
            ),
        )
    if _is_ratio(row) is None:
        return term, T.f("{n} mentions", n=recent)
    return term, T.f(
        "{n} mentions (×{growth} vs the prior period)", n=recent, growth=growth
    )


def _section_groups(section: dict, T: Translator) -> list[tuple[str, list[tuple[str, str]]]]:
    """A section's body as labelled groups of (subject, description) rows.

    Shared by both renderers so the two can never drift, and grouped because a
    section can carry more than one list: across-channels emits per-concept
    attributions AND a per-channel tally, and running them into one bullet list
    made "web" read as if it were a concept. A label is printed only when a
    section actually has more than one group, so single-list sections stay plain.
    """
    groups: list[tuple[str, list[tuple[str, str]]]] = []

    # Partitioned per ROW, never by the first row's shape: two sections emit `terms`
    # with different shapes, and a rising list holds both measured ratios and
    # no-baseline sentinels. One interleaved list made 19 counts and 1 real ratio
    # look like 20 of the same quantity, and the label above it belonged to the
    # OTHER section — printed only because rising happened to have a single group.
    rows = section.get("terms") or []
    baseline_days = section.get("baseline_days")
    first_seen = [r for r in rows if "first_seen" in r]
    rising = [r for r in rows if "first_seen" not in r]
    # THREE buckets, not two, because ``_is_ratio`` has three answers and a label
    # may only claim what its members can support: "no baseline to divide by" is a
    # finding, and a row that does not say cannot be filed under it.
    by_state: dict[bool | None, list[dict]] = {True: [], False: [], None: []}
    for r in rising:
        by_state[_is_ratio(r)].append(r)
    if first_seen:
        groups.append(
            (
                T.t("Where each concept appeared first"),
                [_term_row(r, T=T) for r in first_seen],
            )
        )
    for state, label in (
        (True, "Rose against a measurable baseline"),
        (False, "New or near-new — no baseline to divide by"),
        (None, "Counts only — this record does not say whether a ratio was measurable"),
    ):
        picked = by_state[state]
        if picked:
            groups.append(
                (
                    T.f(
                        "{label} ({n} of {total})",
                        label=T.t(label),
                        n=len(picked),
                        total=len(rising),
                    ),
                    [_term_row(r, baseline_days=baseline_days, T=T) for r in picked],
                )
            )

    topics = [
        (
            str(r["topic"]),
            T.f(
                "{articles} articles, {mentions} mentions",
                articles=_fmt(r["articles"]),
                mentions=_fmt(r.get("mentions")),
            ),
        )
        for r in section.get("topics") or []
    ]
    if topics:
        # The section's own caveat says "the untagged count beside it is the rest of
        # the period, not an empty category" — and no untagged count was ever printed
        # beside it. In the field edition 17,080 of 12,468,182 mentions carried a tag:
        # a table describing 0.14% of the period reads very differently once it says so.
        untagged = section.get("mentions_untagged")
        total = section.get("mentions_total")
        if untagged is not None:
            share = ""
            try:
                if total:
                    share = T.f(
                        " — {share} of them",
                        share=_pct(float(section["mentions_tagged"]) / float(total)),
                    )
            except (TypeError, ValueError, ZeroDivisionError):
                share = ""
            topics = topics + [
                (
                    T.t("Carrying no topic tag"),
                    T.f(
                        "{untagged} mentions of {total}; the table above covers the "
                        "tagged remainder{share}",
                        untagged=_fmt(untagged),
                        total=_fmt(total),
                        share=share,
                    ),
                )
            ]
        groups.append((T.t("By topic"), topics))

    channels = [
        (
            T.t(str(r["provenance"])),
            T.f("first with {n} concept(s)", n=_fmt(r["concepts_first_here"])),
        )
        for r in section.get("channels") or []
    ]
    if channels:
        groups.append((T.t("Concepts first seen in each channel"), channels))

    events = [
        (T.t(str(r["event_type"])), _fmt(r["events"]))
        for r in section.get("by_event_type") or []
    ]
    if events:
        groups.append((T.t("By event type"), events))
    providers = [
        (str(r["provider"]), _fmt(r["events"])) for r in section.get("by_provider") or []
    ]
    if providers:
        groups.append((T.t("By provider"), providers))
    # "Every field here is what the provider published — magnitude, severity tier,
    # coordinates, time — carried through unchanged and never combined" was the
    # caveat over a list of one number. The examples carry every one of those fields
    # and were dropped at render, so the caveat described a document nobody had.
    alerts = []
    for r in section.get("examples") or []:
        bits = []
        if r.get("magnitude") is not None:
            bits.append(T.f("M {magnitude}", magnitude=r["magnitude"]))
        if r.get("severity"):
            bits.append(T.t(str(r["severity"])))
        if r.get("event_time"):
            bits.append(str(r["event_time"])[:16])
        if r.get("provider"):
            bits.append(T.f("per {provider}", provider=r["provider"]))
        alerts.append((str(r.get("place") or r.get("title") or "—"), " · ".join(bits) or "—"))
    if alerts:
        groups.append(
            (
                T.f(
                    "What the providers reported ({n} of {total})",
                    n=len(alerts),
                    total=_fmt(section.get("events")),
                ),
                alerts,
            )
        )

    changes = []
    for r in section.get("law_examples") or []:
        bits = [str(r.get("jurisdiction") or "—")]
        if r.get("observed_at"):
            bits.append(T.f("observed {when}", when=str(r["observed_at"])[:10]))
        delta = r.get("delta_bytes")
        if delta is not None:
            bits.append(T.f("{n} bytes changed", n=_fmt(delta)))
        if r.get("flagged"):
            bits.append(T.t("flagged as large"))
        changes.append((str(r.get("title") or "—"), " · ".join(bits)))
    for r in section.get("wiki_examples") or []:
        bits = ["wikipedia"]
        if r.get("observed_at"):
            bits.append(T.f("observed {when}", when=str(r["observed_at"])[:10]))
        if r.get("flagged"):
            bits.append(T.t("flagged as large"))
        changes.append((str(r.get("title") or "—"), " · ".join(bits)))
    if changes:
        groups.append((T.t("Which documents changed"), changes))

    years = [
        (
            str(r["year"]),
            T.f("{n} articles on the same days", n=_fmt(r["articles"])),
        )
        for r in section.get("years") or []
    ]
    if years:
        groups.append((T.t("By year"), years))

    counts: list[tuple[str, str]] = []
    if section.get("law_revisions") is not None:
        counts.append(
            (
                T.t("Law revisions"),
                T.f(
                    "{n} ({flagged} flagged as large)",
                    n=_fmt(section["law_revisions"]),
                    flagged=_fmt(section.get("law_revisions_flagged")),
                ),
            )
        )
    if section.get("wiki_revisions") is not None:
        counts.append(
            (
                T.t("Wikipedia revisions"),
                T.f(
                    "{n} ({flagged} flagged as large)",
                    n=_fmt(section["wiki_revisions"]),
                    flagged=_fmt(section.get("wiki_revisions_flagged")),
                ),
            )
        )
    if counts:
        groups.append((T.t("Observed changes"), counts))

    return groups


def _coverage_blocks(section: dict, T: Translator) -> list[tuple[str | None, str, list[str]]]:
    """The country-coverage section as (group, heading, lines) blocks.

    Its shape is nested — a place, then two vantages under it — so it cannot go
    through ``_section_groups``' flat (subject, description) model. Shared between
    the two renderers for the same reason that one is.

    The two vantages are printed as two lines under one heading, never merged into
    a single ranking: a merged list would answer neither question. Each carries its
    own n, because "from 3 articles" and "from 3,000" are the difference between a
    finding and an anecdote.
    """
    blocks: list[tuple[str | None, str, list[str]]] = []

    def _side(side: dict, what: str) -> str | None:
        terms = side.get("terms") or []
        n = side.get("articles") or 0
        if not terms:
            return T.f(
                "*{what}: nothing in this period* (from {n} articles)",
                what=what,
                n=_fmt(n),
            )
        listed = ", ".join(
            T.f(
                "{term} {mentions} ({articles} art.)",
                term=t.get("term"),
                mentions=_fmt(t.get("mentions")),
                articles=_fmt(t.get("articles")),
            )
            for t in terms
        )
        return T.f(
            "**{what}**, from {n} articles: {listed}", what=what, n=_fmt(n), listed=listed
        )

    def _lines(row: dict) -> list[str]:
        lines = [f"*{T.t(row.get('reading'))}*", ""]
        for key, what in (("local", "Local"), ("international", "International")):
            line = _side(row.get(key) or {}, T.t(what))
            if line:
                lines.append(f"- {line}")
        return lines

    for i, row in enumerate(section.get("countries") or []):
        head = f"{row.get('name') or row.get('country')} ({row.get('country')})"
        if row.get("continent"):
            head += f" · {T.t(str(row['continent']))}"
        blocks.append((T.t("By country") if i == 0 else None, head, _lines(row)))

    for i, row in enumerate(section.get("continents") or []):
        # "contributing countries: 1" rather than "1 countries here": a count
        # interpolated into a sentence cannot agree with the noun beside it, and the
        # label:value form is correct in every language without per-form keys.
        head = T.f(
            "{continent} — contributing countries: {n}",
            continent=T.t(str(row.get("continent"))),
            n=_fmt(row.get("countries_contributing")),
        )
        blocks.append((T.t("By continent") if i == 0 else None, head, _lines(row)))
    return blocks


def _article_lines(row: dict, T: Translator) -> list[str]:
    """One article as a few lines, with its two classes of fact kept apart.

    The URL is the ORIGINAL page. A local article id resolves to a different article
    on a recipient's install (§12), so the id stays in the JSON record where the
    operator who owns the corpus can use it, and never becomes a link here.
    """
    src = row.get("source") or {}
    asserted = row.get("asserted") or {}
    deduced = row.get("deduced") or {}
    title = str(row.get("title") or "(untitled)")
    url = row.get("url")
    head = f"[{title}]({url})" if url else title
    # The reference number, when the record has been numbered. It is the article's
    # annex filename, so a reader following `[0012]` from here opens exactly one file
    # — which is why the numbering lives in one place and both sides call it.
    if row.get("ref"):
        head = f"`[{row['ref']}]` {head}"

    stated = [str(src.get("name") or src.get("domain") or T.t("unknown source"))]
    if asserted.get("published_at"):
        stated.append(str(asserted["published_at"])[:16])
    if asserted.get("author"):
        stated.append(T.f("by {author}", author=asserted["author"]))
    if asserted.get("language"):
        stated.append(T.f("lang {code}", code=asserted["language"]))

    read = []
    if deduced.get("word_count"):
        read.append(T.f("{n} words", n=_fmt(deduced["word_count"])))
    if deduced.get("detected_language") and deduced.get("detected_language") != asserted.get(
        "language"
    ):
        read.append(T.f("detected {code}", code=deduced["detected_language"]))
    sent = deduced.get("sentiment") or {}
    if sent.get("label"):
        read.append(
            T.f(
                "tone {label} ({basis})",
                label=T.t(str(sent["label"])),
                basis=T.t(str(sent.get("basis"))),
            )
        )

    lines = [
        f"- **{head}**",
        T.f("  - Source states: {facts}", facts=" · ".join(stated)),
    ]
    if read:
        lines.append(T.f("  - This app measured: {facts}", facts=" · ".join(read)))
    kws = row.get("keywords") or []
    if kws:
        lines.append(
            T.f(
                "  - Keywords: {terms}",
                terms=", ".join(f"{k.get('term')} ({_fmt(k.get('mentions'))})" for k in kws),
            )
        )
    facets = []
    for key, label in (("places", "Places"), ("entities", "Who"), ("dates", "Dates mentioned")):
        vals = row.get(key) or []
        if not vals:
            continue
        if key == "dates":
            facets.append(T.t(label) + ": " + ", ".join(str(v.get("date")) for v in vals))
        else:
            facets.append(T.t(label) + ": " + ", ".join(str(v.get("name")) for v in vals))
    if facets:
        lines.append(T.f("  - Deduced from the text — {facets}", facets=" · ".join(facets)))
    excerpt = (row.get("excerpt") or "").strip()
    if excerpt:
        tail = "…" if row.get("excerpt_truncated") else ""
        lines.append(f"  - > {excerpt}{tail}")
    return lines


def _cards_blocks(section: dict, T: Translator) -> list[tuple[str | None, str, list[str]]]:
    """The cards section as (group, heading, lines) blocks, one group per card type."""
    blocks: list[tuple[str | None, str, list[str]]] = []
    for entry in section.get("types") or []:
        card_type = str(entry.get("type") or "?")
        found, shown = entry.get("cards_found"), entry.get("cards_shown")
        group = T.t(card_type.replace("_", " "))
        if isinstance(found, int) and isinstance(shown, int) and found > shown:
            group += T.f(" — showing {shown} of {found}", shown=shown, found=found)
        first = True
        for card in entry.get("cards") or []:
            lines: list[str] = []
            if card.get("summary"):
                # A producer composes this around live values, so it is data: printed as
                # it stands and kept out of the coverage denominator rather than counted
                # as a missing translation no catalog entry could ever supply.
                lines += [T.data(str(card["summary"])), ""]
            pairs = card.get("signal_pairs")
            if pairs:
                # The LABEL translates, the VALUE does not. Translating the composed line
                # (what this did) could never match a key, so the labels stayed English
                # and the line depressed coverage.
                measured = " · ".join(
                    f"{T.t(str(p[0]))} {p[1]}"
                    for p in pairs
                    if isinstance(p, (list, tuple)) and len(p) == 2
                )
            else:
                # An edition written before signal_pairs existed carries only the composed
                # form. It has values in it, so it passes through as data.
                measured = T.data(str(card.get("signal_line") or ""))
            if measured:
                lines.append(T.f("- Measured: {signal}", signal=measured))
            if card.get("n") is not None:
                lines.append(T.f("- n: {n}", n=_fmt(card.get("n"))))
            if card.get("bucket"):
                lines.append(T.f("- Bucket: {bucket}", bucket=T.t(str(card["bucket"]))))
            if card.get("method"):
                lines.append(T.f("- Method: {method}", method=T.t(str(card["method"]))))
            arts = card.get("article_rows") or []
            total = card.get("corpus_articles")
            if arts:
                if isinstance(total, int) and total > len(arts):
                    lines += [
                        "",
                        T.f(
                            "**Articles ({shown} of {total} in this card):**",
                            shown=len(arts),
                            total=_fmt(total),
                        ),
                        "",
                    ]
                else:
                    lines += ["", T.f("**Articles ({n}):**", n=len(arts)), ""]
                for a in arts:
                    lines += _article_lines(a, T)
            elif isinstance(total, int) and total == 0:
                lines += [
                    "",
                    "*"
                    + T.t(
                        "This card's selection is a query or a whole-corpus distribution, "
                        "so it names no fixed article set."
                    )
                    + "*",
                ]
            if card.get("caveat"):
                lines += ["", f"> {T.t(card['caveat'])}"]
            blocks.append((group if first else None, str(card.get("title") or card_type), lines))
            first = False
    return blocks


def _cards_note(section: dict, T: Translator) -> str | None:
    """How much of the producer set actually ran."""
    ran, total = section.get("producers_run"), section.get("producers_total")
    bits = []
    if isinstance(ran, int) and isinstance(total, int):
        bits.append(T.f("Producers run: {ran} of {total}.", ran=ran, total=total))
    if section.get("truncated"):
        bits.append(
            T.t(
                "The wall-clock budget stopped further producers, so this is a partial "
                "set — a short list here is the budget, not a quiet corpus."
            )
        )
    found, kinds = section.get("cards_found"), section.get("card_types")
    if isinstance(found, int) and isinstance(kinds, int):
        bits.append(
            T.f("Cards surfaced: {found} across {kinds} types.", found=_fmt(found), kinds=kinds)
        )
    return " ".join(bits) or None


def _coverage_note(section: dict, T: Translator) -> str | None:
    """How many countries the document lists, of how many it counted."""
    total, listed = section.get("countries_total"), section.get("countries_listed")
    if not isinstance(total, int) or not isinstance(listed, int) or listed >= total:
        return None
    # label:value, not a sentence with the count inside it — "the other 1 were
    # counted" cannot agree with its own noun, and no locale has to be given per-form
    # keys for a phrasing that never conjugates.
    return T.f(
        "Contributing countries listed here: {listed} of {total}, largest first by the "
        "masthead's own split. Counted and not printed: {rest}. The continent figures "
        "below cover every contributing country, including those.",
        listed=listed,
        total=total,
        rest=total - listed,
    )


def _section_heading(section: dict, T: Translator) -> str:
    """A section's own slug as a heading, translated as a whole label.

    The slug is data (``rising_concepts``); the HEADING is this app's own words, so
    the humanised English is the key. A locale with no entry gets the English
    heading, which is the same rule every other sentence follows.
    """
    return T.t(str(section.get("section", "section")).replace("_", " ").capitalize())


def _md_section(section: dict, T: Translator) -> list[str]:
    out = [f"## {_section_heading(section, T)}", ""]
    if section.get("error"):
        out += [
            T.f("*This section could not be built: `{error}`.*", error=section["error"]),
            "",
        ]
        return out
    if section.get("skipped"):
        out += [T.f("*Not shown: {reason}.*", reason=T.t(str(section["skipped"]))), ""]
        return out

    w = section.get("window") or {}
    if w and not w.get("matches_period", True):
        # §12: a section whose window differs from the period must be VISIBLE.
        out += [
            T.f("*Window: {days} days — not the edition's period.*", days=w.get("days")),
            "",
        ]

    # The two nested sections carry their own shape and their own note. Keyed on the
    # section's OWN fields rather than on whether it produced any blocks: the case
    # where the note matters most is a card run whose budget stopped every producer,
    # and keying on the blocks printed "Nothing to report" over exactly that — a
    # budget reading as a quiet corpus, which is what the note exists to prevent.
    for owns, blocks, note, empty in (
        (
            "countries" in section or "continents" in section,
            _coverage_blocks(section, T),
            _coverage_note(section, T),
            T.t("No country contributed to this period."),
        ),
        (
            "types" in section,
            _cards_blocks(section, T),
            _cards_note(section, T),
            T.t("No card surfaced from the producers that ran."),
        ),
    ):
        if not owns:
            continue
        if note:
            out += [f"*{note}*", ""]
        if not blocks:
            out += [f"*{empty}*", ""]
        for group, head, lines in blocks:
            if group:
                out += [f"**{group}**", ""]
            out += [f"### {head}", ""] + lines + [""]
        if section.get("caveat"):
            out += [f"> {T.t(section['caveat'])}", ""]
        return out

    groups = _section_groups(section, T)
    if not groups:
        out.append(f"*{T.t('Nothing to report for this period.')}*")
    for label, rows in groups:
        if len(groups) > 1:
            out += [f"**{label}**", ""]
        out += [f"- **{subject}** — {rest}" for subject, rest in rows]
        if len(groups) > 1:
            out.append("")
    out.append("")
    if section.get("caveat"):
        out += [f"> {T.t(section['caveat'])}", ""]
    return out


def _md_story(story: dict, T: Translator) -> list[str]:
    terms = ", ".join(story.get("shared_terms") or []) or "—"
    voice = f" · **{T.t('one source only')}**" if story.get("single_source") else ""
    out = [
        f"### {terms}",
        "",
        T.f(
            "{articles} articles · {sources} sources{voice}",
            articles=_fmt(story.get("articles")),
            sources=_fmt(story.get("distinct_sources")),
            voice=voice,
        ),
        "",
    ]
    nar = story.get("narration") or {}
    if nar.get("text"):
        if nar.get("narrated"):
            mark = f"*{T.t(_AI_LABEL)}"
            if nar.get("partial"):
                mark += "; " + T.t(
                    "sentences that named something absent from the sources were removed"
                )
            out += [f"{mark}.*", "", nar["text"], ""]
        else:
            out += [nar["text"], ""]
            if nar.get("fallback_reason"):
                out += [
                    T.f(
                        "*No model text: {reason}.*",
                        reason=T.t(str(nar["fallback_reason"])),
                    ),
                    "",
                ]
    # The story's own articles. They were added to the record so "the document can
    # name them" and the renderer then did not, so a cluster of 115 arrived as a
    # count with no way in — and the annexes carried files the report never cited.
    out += _story_article_lines(story, T)
    return out


def _story_article_lines(story: dict, T: Translator) -> list[str]:
    """A story's articles, shared by both renderers so neither can drop them again."""
    rows = story.get("article_rows") or []
    if not rows:
        return []
    total = story.get("articles")
    head = (
        T.f("Showing {shown} of {total}:", shown=_fmt(len(rows)), total=_fmt(total))
        if isinstance(total, int) and total > len(rows)
        else T.t("Articles:")
    )
    out = [head, ""]
    for row in rows:
        out += _article_lines(row, T)
    out.append("")
    return out


def _worklist_lines(edition: dict, T: Translator) -> list[str]:
    """Phase 2 as a plan, shared by both renderers. Empty when none is attached.

    It prints only when a caller has attached one, because phase 2 is an OPTION
    offered after phase 1 exists — that is the whole shape of the two-phase design.
    The heading says PLAN and the first line says nothing has run, in that order,
    because a reader skimming headings must not mistake a proposal for a result.
    """
    plan = edition.get("ai_worklist") or {}
    jobs = plan.get("jobs") or []
    if not plan:
        return []
    lines = [
        "*"
        + T.t(
            "A PLAN — nothing below has run. Phase 1 above is a complete document "
            "without any of it."
        )
        + "*",
        "",
    ]
    if not jobs:
        lines += [T.t("Nothing for a local model to add to this edition."), ""]
        return lines
    for job in jobs:
        lines.append(f"**{T.t(str(job.get('what')))}**")
        lines.append("")
        lines.append(
            T.f(
                "- {units} unit(s), {calls} model call(s)",
                units=_fmt(job.get("units")),
                calls=_fmt(job.get("calls")),
            )
        )
        if job.get("articles_total") is not None:
            lines.append(
                T.f("- Over {n} articles in total", n=_fmt(job["articles_total"]))
            )
        if job.get("already_done"):
            lines.append(
                T.f("- Already done in this edition: {n}", n=_fmt(job["already_done"]))
            )
        if job.get("already_in_target") is not None:
            lines.append(
                T.f(
                    "- Already in the target language: {n}",
                    n=_fmt(job["already_in_target"]),
                )
            )
        if job.get("language_unknown"):
            lines.append(
                T.f(
                    "- Language not recorded, so not assumed either way: {n}",
                    n=_fmt(job["language_unknown"]),
                )
            )
        corpora = job.get("corpora") or []
        if corpora:
            head = ", ".join(
                f"{c.get('label')} ({_fmt(c.get('articles'))})" for c in corpora[:6]
            )
            tail = (
                T.f(" … and {n} more", n=len(corpora) - 6) if len(corpora) > 6 else ""
            )
            lines.append(T.f("- Corpora: {corpora}{tail}", corpora=head, tail=tail))
        lines.append(T.f("- Adds: {adds}", adds=T.t(str(job.get("adds")))))
        lines.append(
            T.f("- If skipped: {cost}", cost=T.t(str(job.get("if_skipped"))))
        )
        lines.append("")

    dur = plan.get("duration") or {}
    total = T.f(
        "**Total: {calls} model call(s).**", calls=_fmt(plan.get("calls_total"))
    )
    if dur.get("known"):
        mins = (dur.get("seconds") or 0) / 60.0
        lines += [
            T.f(
                "{total} About {minutes} minute(s) — {method}",
                total=total,
                minutes=f"{mins:.0f}",
                method=T.t(str(dur.get("method"))),
            ),
            "",
        ]
    else:
        lines += [
            T.f(
                "{total} No duration is offered: {reason}",
                total=total,
                reason=T.t(str(dur.get("reason"))),
            ),
            "",
        ]
    if plan.get("caveat"):
        lines += [f"> {T.t(plan['caveat'])}", ""]
    return lines


def _md_worklist(edition: dict, T: Translator) -> list[str]:
    lines = _worklist_lines(edition, T)
    if not lines:
        return []
    return [f"## {T.t('What the local AI could add — a plan')}", ""] + lines


def _md_references(edition: dict, T: Translator) -> list[str]:
    """Sources that contributed — the reference list.

    External identity only. A local article id means a different article on a
    recipient's install, so it never leaves this machine in a published document.
    """
    top = (edition.get("masthead") or {}).get("top_sources") or []
    if not top:
        return []
    out = [
        f"## {T.t('References')}",
        "",
        T.t("Largest contributors this period:"),
        "",
    ]
    for row in top:
        dom = row.get("domain") or "—"
        out.append(
            T.f(
                "- {name} (`{domain}`) — {n} articles",
                name=row.get("name") or dom,
                domain=dom,
                n=_fmt(row.get("articles")),
            )
        )
    out += [
        "",
        "*"
        + T.t(
            "Article-level links are omitted on purpose: a local article id resolves "
            "to a different article on another install."
        )
        + "*",
        "",
    ]
    return out


def _selection_line(edition: dict, T: Translator) -> str | None:
    """What the operator left out, if anything.

    A document that silently omits three of its seven sections reads as complete.
    The operator chooses what to publish — that is the ruling — but a reader is
    entitled to know they are reading a selection, so the count travels with the
    document.
    """
    sel = edition.get("selection") or {}
    shown, total = sel.get("sections_shown"), sel.get("sections_total")
    st_shown, st_total = sel.get("stories_shown"), sel.get("stories_total")
    parts = []
    if isinstance(shown, int) and isinstance(total, int) and shown < total:
        parts.append(T.f("{shown} of {total} sections", shown=shown, total=total))
    if isinstance(st_shown, int) and isinstance(st_total, int) and st_shown < st_total:
        parts.append(T.f("{shown} of {total} stories", shown=st_shown, total=st_total))
    if not parts:
        return None
    return T.f(
        "This edition shows {parts}; the rest were excluded by the operator before "
        "publishing. The record it was rendered from is unchanged.",
        parts=f" {T.t('and')} ".join(parts),
    )


def _md_disclosures(edition: dict, T: Translator) -> list[str]:
    d = edition.get("disclosures") or {}
    sel = _selection_line(edition, T)
    # An operator's exclusion is a disclosure in its own right, so it prints even
    # when the edition carries no other one — otherwise the one case where the
    # document is least complete is the case where it says least about itself.
    if not d and not sel:
        return []
    out = [f"### {T.t('What this edition cannot see')}", ""]
    if sel:
        out.append(f"- {sel}")
    q = d.get("quarantined_in_period")
    if q:
        out.append(
            T.f(
                "- {n} article(s) in the period are quarantined and excluded throughout.",
                n=_fmt(q),
            )
        )
    u = d.get("mentions_without_a_date")
    if u:
        out.append(
            T.f(
                "- {n} keyword mention(s) carry no date and are invisible to every window.",
                n=_fmt(u),
            )
        )
    backlog = d.get("reindex_backlog") or {}
    if backlog.get("available") and backlog.get("articles_pending"):
        out.append(
            T.f(
                "- {n} imported article(s) await re-index, so they carry no keywords yet "
                "and are missing from every keyword figure here.",
                n=_fmt(backlog["articles_pending"]),
            )
        )
    elif backlog.get("available") is False:
        out.append(
            "- " + T.t("The re-index backlog could not be read — unknown, not zero.")
        )
    cov = d.get("baseline_coverage") or {}
    if cov.get("complete") is False:
        out.append(f"- {T.t(str(cov.get('note')))}")
    if len(out) == 2:
        out.append("- " + T.t("Nothing excluded beyond what the methods above state."))
    out.append("")
    return out


# --------------------------------------------------------------------------- #
#  HTML
# --------------------------------------------------------------------------- #

_CSS = """
:root{--fg:#17181c;--muted:#5a5f6a;--bg:#fff;--rule:#e3e5ea;--mark:#8a4d0a;--ai:#5b3fa8}
@media(prefers-color-scheme:dark){:root{--fg:#e8e9ec;--muted:#a2a8b4;--bg:#15161a;
--rule:#2c2f36;--mark:#eab44e;--ai:#b9a4f0}}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1rem;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:44rem;margin:0 auto}
h1{font-size:1.7rem;line-height:1.25;margin:0 0 .25rem}
h2{font-size:1.15rem;margin:2.2rem 0 .6rem;padding-bottom:.3rem;border-bottom:1px solid var(--rule)}
h3{font-size:1rem;margin:1.4rem 0 .4rem}
/* An unstyled h4 takes the browser's 1em bold, which is the same size as the h3
   above it — a heading that does not outrank its parent is not a hierarchy. */
h4{font-size:.94rem;margin:1rem 0 .3rem;color:var(--muted)}
.lede{color:var(--muted);margin:0 0 1.5rem}
ul{padding-left:1.2rem}li{margin:.25rem 0}
.caveat{color:var(--mark);border-left:3px solid var(--mark);padding:.4rem 0 .4rem .8rem;
margin:.8rem 0;font-size:.92rem}
.ai{color:var(--ai);font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;margin:.6rem 0 .2rem}
.ai-text{border-left:3px solid var(--ai);padding-left:.8rem;margin:0 0 .9rem}
.meta{color:var(--muted);font-size:.9rem}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--rule);
color:var(--muted);font-size:.85rem}
table{border-collapse:collapse;width:100%;font-size:.93rem}
td,th{text-align:left;padding:.3rem .6rem .3rem 0;border-bottom:1px solid var(--rule)}
"""


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def _plain(s: Any) -> str:
    """A value as text, with an absent one absent rather than the word "None".

    ``str.format`` renders ``None`` as ``None``, which reads as a value. Every
    frame value on the HTML side goes through here because ``_e`` used to do it,
    and the escaping now happens once, later, over the whole filled sentence.
    """
    return "" if s is None else str(s)


def render_html(edition: dict, *, lang: str = "en", tr: Translator | None = None) -> str:
    """The edition as ONE self-contained HTML page.

    No external stylesheet, font, script or image — a shared document that phones
    home would tell its recipient's network what the operator reads. Light and
    dark are both styled, because a document is read wherever it is opened.

    The page's ``lang`` attribute and its ``dir`` follow the chosen language, so a
    right-to-left edition is laid out right-to-left by the browser rather than by
    us guessing at it.
    """
    T = tr or Translator(lang)
    p = edition.get("period") or {}
    m = edition.get("masthead") or {}
    body: list[str] = []

    body.append(f"<h1>{_e(_title(edition, T))}</h1>")
    body.append(
        '<p class="lede">'
        + _e(
            T.f(
                "What rose in this corpus between {start} and {end} — {days} days.",
                start=_plain(p.get("start")),
                end=_plain(p.get("last_day")),
                days=_plain(p.get("days")),
            )
        )
        + "</p>"
    )
    lang_at = len(body)

    body.append(f"<h2>{_e(T.t('This corpus, this period'))}</h2><ul>")
    body.append(
        "<li>"
        + _inline(
            T.f(
                "**{articles}** articles from **{sources}** contributing sources",
                articles=_fmt(m.get("articles")),
                sources=_fmt(m.get("sources_contributing")),
            )
        )
        + "</li>"
    )
    body.append(
        "<li>"
        + _inline(
            T.f("The three largest carried **{share}**", share=_pct(m.get("top_3_share")))
        )
        + "</li>"
    )
    body.append(
        "<li>"
        + _inline(
            T.f(
                "Ingest on **{days}** of {total} days",
                days=_plain(m.get("days_with_ingest")),
                total=_plain(m.get("period_days")),
            )
        )
        + "</li>"
    )
    body.append(
        "<li>"
        + _inline(
            T.f(
                "**{share}** of a corpus of {total}",
                share=_pct(m.get("corpus_share")),
                total=_fmt(m.get("corpus_articles")),
            )
        )
        + "</li>"
    )
    body.append("</ul>")
    for line in _masthead_splits(m, T):
        body.append(f'<p class="meta">{_e(line)}</p>')
    if m.get("caveat"):
        body.append(f'<p class="caveat">{_e(T.t(m["caveat"]))}</p>')
    for line in _ref_legend(edition, T):
        if line:
            body.append(f'<p class="meta">{_e(line)}</p>')

    for section in edition.get("sections") or []:
        body.extend(_html_section(section, T))

    stories = (edition.get("stories") or {}).get("stories") or []
    if stories:
        body.append(f"<h2>{_e(T.t('Stories'))}</h2>")
        for s in stories:
            body.extend(_html_story(s, T))
        cav = (edition.get("stories") or {}).get("caveat")
        if cav:
            body.append(f'<p class="caveat">{_e(T.t(cav))}</p>')

    plan_lines = _worklist_lines(edition, T)
    if plan_lines:
        body.append(f"<h2>{_e(T.t('What the local AI could add — a plan'))}</h2>")
        body.extend(_html_lines(plan_lines))

    top = m.get("top_sources") or []
    if top:
        body.append(
            f"<h2>{_e(T.t('References'))}</h2><table><tr>"
            f"<th>{_e(T.t('Source'))}</th><th>{_e(T.t('Articles'))}</th></tr>"
        )
        for row in top:
            body.append(
                f"<tr><td>{_e(row.get('name') or row.get('domain'))} "
                f'<span class="meta">{_e(row.get("domain"))}</span></td>'
                f"<td>{_fmt(row.get('articles'))}</td></tr>"
            )
        body.append("</table>")
        body.append(
            '<p class="meta">'
            + _e(
                T.t(
                    "Article-level links are omitted on purpose: a local article id "
                    "resolves to a different article on another install."
                )
            )
            + "</p>"
        )

    body.append(f"<h2>{_e(T.t('Methods & caveats'))}</h2>")
    if edition.get("method"):
        body.append(f'<p class="meta">{_e(T.t(edition["method"]))}</p>')
    if edition.get("caveat"):
        body.append(f'<p class="caveat">{_e(T.t(edition["caveat"]))}</p>')
    for line in _md_disclosures(edition, T):
        if line.startswith("- "):
            body.append(f'<p class="meta">{_e(line[2:])}</p>')
        elif line.startswith("### "):
            body.append(f"<h3>{_e(line[4:])}</h3>")

    body.append(
        "<footer>"
        + _e(
            T.f(
                "Generated {when} by Open Omniscience from this operator's own corpus. "
                "Deterministic sections are computed from the record {record}.",
                when=edition.get("generated_at") or datetime.now(UTC).isoformat(),
                record=_plain(edition.get("filename") or "the edition JSON"),
            )
        )
        + "</footer>"
    )

    disclosure = T.disclosure()
    if disclosure:
        body.insert(lang_at, f'<p class="meta">{_e(disclosure)}</p>')

    dir_attr = ' dir="rtl"' if T.lang in _RTL else ""
    return (
        "<!doctype html>\n"
        f'<html lang="{_e(T.lang)}"{dir_attr}><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(_title(edition, T))}</title><style>{_CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>\n"
    )


#: Right-to-left scripts among the twelve. Arabic is the one the UI ships today;
#: the set exists so a future addition is one entry rather than a new branch.
_RTL = frozenset({"ar", "he", "fa", "ur"})


_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_MD_BOLD = re.compile(r"\*\*([^*]+)\*\*")
# Deliberately tight: no whitespace and no angle brackets inside a code span, so a
# pair can never open inside a URL and close in the prose after it. A single stray
# backtick cannot form a pair on its own, which is the case that would otherwise
# produce broken markup from a link this document did not write.
_MD_CODE = re.compile(r"`([^`\s<>]+)`")


def _inline(s: str) -> str:
    """Escape, then re-admit the three inline forms the block builders emit.

    Deliberately NOT a Markdown parser. The blocks above are shared between the two
    renderers, so the HTML side has to read the same lines — and the only inline
    markup in them is a bold run and a link, both written by code in this file. It
    escapes first, so no input can smuggle markup through; the patterns then match
    the escaped text, where a link's own URL is already entity-safe.
    """
    out = _e(s)
    out = _MD_CODE.sub(r"<code>\1</code>", out)
    out = _MD_LINK.sub(r'<a href="\2" rel="noopener nofollow">\1</a>', out)
    return _MD_BOLD.sub(r"<strong>\1</strong>", out)


def _html_lines(lines: list[str]) -> list[str]:
    """The shared block lines as HTML: bullets, quotes and paragraphs."""
    out: list[str] = []
    bullets: list[str] = []

    def _flush() -> None:
        if bullets:
            out.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line:
            _flush()
            continue
        stripped = line.lstrip()
        if stripped.startswith("- >"):
            # An excerpt inside a bullet: a quote, not a list item.
            _flush()
            out.append(f'<blockquote>{_inline(stripped[3:].strip())}</blockquote>')
        elif stripped.startswith("- "):
            bullets.append(_inline(stripped[2:]))
        elif stripped.startswith("> "):
            _flush()
            out.append(f'<p class="caveat">{_inline(stripped[2:])}</p>')
        elif stripped.startswith("*") and stripped.endswith("*") and len(stripped) > 2:
            _flush()
            out.append(f'<p class="meta">{_inline(stripped.strip("*"))}</p>')
        else:
            _flush()
            out.append(f"<p>{_inline(stripped)}</p>")
    _flush()
    return out


def _html_section(section: dict, T: Translator) -> list[str]:
    out = [f"<h2>{_e(_section_heading(section, T))}</h2>"]
    if section.get("error"):
        out.append(
            '<p class="meta">'
            + _e(
                T.f(
                    "This section could not be built: {error}.",
                    error=_plain(section["error"]),
                )
            )
            + "</p>"
        )
        return out
    if section.get("skipped"):
        out.append(
            '<p class="meta">'
            + _e(T.f("Not shown: {reason}.", reason=T.t(str(section["skipped"]))))
            + "</p>"
        )
        return out

    w = section.get("window") or {}
    if w and not w.get("matches_period", True):
        out.append(
            '<p class="caveat">'
            + _e(
                T.f(
                    "Window: {days} days — not the edition's period.",
                    days=_plain(w.get("days")),
                )
            )
            + "</p>"
        )

    for owns, blocks, note, empty in (
        (
            "countries" in section or "continents" in section,
            _coverage_blocks(section, T),
            _coverage_note(section, T),
            T.t("No country contributed to this period."),
        ),
        (
            "types" in section,
            _cards_blocks(section, T),
            _cards_note(section, T),
            T.t("No card surfaced from the producers that ran."),
        ),
    ):
        if not owns:
            continue
        if note:
            out.append(f'<p class="meta">{_e(note)}</p>')
        if not blocks:
            out.append(f'<p class="meta">{_e(empty)}</p>')
        for group, head, lines in blocks:
            if group:
                out.append(f"<h3>{_e(group)}</h3>")
            out.append(f"<h4>{_e(head)}</h4>")
            out.extend(_html_lines(lines))
        if section.get("caveat"):
            out.append(f'<p class="caveat">{_e(T.t(section["caveat"]))}</p>')
        return out

    groups = _section_groups(section, T)
    if not groups:
        out.append(f'<p class="meta">{_e(T.t("Nothing to report."))}</p>')
    for label, rows in groups:
        if len(groups) > 1:
            out.append(f"<h3>{_e(label)}</h3>")
        items = "".join(
            f"<li><strong>{_e(subject)}</strong> — {_e(rest)}</li>" for subject, rest in rows
        )
        out.append(f"<ul>{items}</ul>")
    if section.get("caveat"):
        out.append(f'<p class="caveat">{_e(T.t(section["caveat"]))}</p>')
    return out


def _html_story(story: dict, T: Translator) -> list[str]:
    terms = ", ".join(story.get("shared_terms") or []) or "—"
    voice = f" · {T.t('one source only')}" if story.get("single_source") else ""
    out = [
        f"<h3>{_e(terms)}</h3>",
        '<p class="meta">'
        + _e(
            T.f(
                "{articles} articles · {sources} sources{voice}",
                articles=_fmt(story.get("articles")),
                sources=_fmt(story.get("distinct_sources")),
                voice=voice,
            )
        )
        + "</p>",
    ]
    nar = story.get("narration") or {}
    if nar.get("text"):
        if nar.get("narrated"):
            label = T.t(_AI_LABEL)
            if nar.get("partial"):
                label += " · " + T.t(
                    "sentences naming something absent from the sources were removed"
                )
            out.append(f'<p class="ai">{_e(label)}</p>')
            out.append(f'<p class="ai-text">{_e(nar["text"])}</p>')
        else:
            out.append(f"<p>{_e(nar['text'])}</p>")
            if nar.get("fallback_reason"):
                out.append(
                    '<p class="meta">'
                    + _e(
                        T.f(
                            "No model text: {reason}.",
                            reason=T.t(str(nar["fallback_reason"])),
                        )
                    )
                    + "</p>"
                )
    lines = _story_article_lines(story, T)
    if lines:
        out.append(f'<p class="meta">{_e(lines[0])}</p>')
        out.extend(_html_lines(lines[1:]))
    return out


def render(
    edition: dict, fmt: str, *, lang: str = "en", tr: Translator | None = None
) -> str:
    """Render ``edition`` as ``markdown`` or ``html``, in ``lang``.

    An unknown format still raises rather than guessing, and an unknown LANGUAGE
    does not: a locale with no catalog renders in English and says so in the
    document, because refusing to produce a bulletin over a missing translation
    would be a worse answer than producing one that names its own gap.
    """
    f = (fmt or "").strip().lower()
    if f in ("md", "markdown"):
        return render_markdown(edition, lang=lang, tr=tr)
    if f == "html":
        return render_html(edition, lang=lang, tr=tr)
    raise ValueError(f"unknown format {fmt!r}; known formats: markdown, html")
