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
"""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

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
    rows: list[dict], *, limit: int, label: str, count_key: str = "articles"
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
    return rows[:limit], (
        f" ({limit} of {total} shown; the other {total - limit} {label} "
        f"{_fmt(carried)} in total)"
    )


def _title(edition: dict) -> str:
    p = edition.get("period") or {}
    cadence = str(p.get("cadence", "period")).capitalize()
    return f"{cadence} bulletin — {p.get('start', '?')} to {p.get('last_day', '?')}"


# --------------------------------------------------------------------------- #
#  Markdown
# --------------------------------------------------------------------------- #


def render_markdown(edition: dict) -> str:
    """The edition as Markdown. Pure; the numbers come from the record."""
    p = edition.get("period") or {}
    m = edition.get("masthead") or {}
    out: list[str] = [f"# {_title(edition)}", ""]

    # The framing verb is "what ROSE in this corpus", never "what trended" — and
    # the lens is stated in the same breath, which is the point of the masthead.
    out += [
        f"What rose in this corpus between **{p.get('start')}** and "
        f"**{p.get('last_day')}** ({p.get('days')} days).",
        "",
        "## This corpus, this period",
        "",
        f"- **{_fmt(m.get('articles'))}** articles, from **{_fmt(m.get('sources_contributing'))}** "
        f"sources that actually contributed",
        f"- The three largest sources carried **{_pct(m.get('top_3_share'))}** of them",
        f"- Ingest on **{m.get('days_with_ingest', '—')}** of the period's "
        f"{m.get('period_days', '—')} days",
        f"- **{_pct(m.get('corpus_share'))}** of a corpus of {_fmt(m.get('corpus_articles'))}",
        "",
    ]

    for line in _masthead_splits(m):
        out += [line, ""]
    if m.get("caveat"):
        out += [f"> {m['caveat']}", ""]

    for section in edition.get("sections") or []:
        out += _md_section(section)

    stories = (edition.get("stories") or {}).get("stories") or []
    if stories:
        out += ["## Stories", ""]
        for s in stories:
            out += _md_story(s)
        if (edition.get("stories") or {}).get("caveat"):
            out += [f"> {edition['stories']['caveat']}", ""]

    out += _md_references(edition)
    out += ["## Methods & caveats", ""]
    if edition.get("method"):
        out += [edition["method"], ""]
    if edition.get("caveat"):
        out += [f"> {edition['caveat']}", ""]
    out += _md_disclosures(edition)
    out += [
        "---",
        "",
        f"Generated {edition.get('generated_at') or datetime.now(UTC).isoformat()} "
        f"by Open Omniscience. Deterministic sections are computed from this "
        f"operator's own corpus; the record they come from is "
        f"`{edition.get('filename', 'the edition JSON')}`.",
    ]
    return "\n".join(out)


def _masthead_splits(m: dict) -> list[str]:
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
        lines.append(f"By day: {', '.join(parts)}.")

    channels = m.get("channels") or []
    if channels:
        shown, tail = _listed(channels, limit=10, label="carried")
        parts = [f"{r['source_type']} {_fmt(r['articles'])}" for r in shown]
        lines.append(f"Channels: {', '.join(parts)}{tail}.")

    langs = m.get("languages") or []
    if langs:
        shown, tail = _listed(langs, limit=16, label="carried")
        parts = [f"{r['language'] or 'untagged'} {_fmt(r['articles'])}" for r in shown]
        lines.append(f"Languages: {', '.join(parts)}{tail}.")

    countries = m.get("source_countries") or []
    if countries:
        shown, tail = _listed(countries, limit=20, label="carried")
        parts = [f"{r['country']} {_fmt(r['articles'])}" for r in shown]
        unl = m.get("source_unlocated_articles") or 0
        unlocated = f"; {_fmt(unl)} from sources with no country recorded" if unl else ""
        lines.append(f"Source countries: {', '.join(parts)}{tail}{unlocated}.")
    return lines


def _channel_of(row: dict) -> str:
    """Where an across-channels row was first seen, ties intact.

    A tie is real: two channels can carry a concept on the same day and the
    mention clock is a date, so there is no finer order to appeal to. Printing
    one of them would invent a sequence the data does not contain.
    """
    tied = row.get("channels_tied") or []
    if tied:
        return f"{', '.join(str(c) for c in tied)} (tied)"
    return str(row.get("channel") or "no channel recorded")


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


def _term_row(row: dict, *, baseline_days: Any = None) -> tuple[str, str]:
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
        return term, f"first seen {row.get('first_seen')} in {_channel_of(row)}"
    growth = row.get("growth")
    recent = _fmt(row.get("recent"))
    if growth is None:
        # No ratio computed — say the count and stop, rather than print "×None".
        return term, f"{recent} mentions"
    if _is_ratio(row) is False:
        # The sentinel. Say the two counts it stands between and name the reason;
        # the one thing not to do is dress the count as a multiple.
        prior = row.get("prior")
        window = f"prior {baseline_days} days" if baseline_days else "prior period"
        if prior in (0, None):
            return term, f"{recent} mentions — new in this period, nothing prior to compare"
        return (
            term,
            f"{recent} mentions, against {_fmt(prior)} in the {window} — "
            "too thin a baseline to divide by",
        )
    if _is_ratio(row) is None:
        return term, f"{recent} mentions"
    return term, f"{recent} mentions (×{growth} vs the prior period)"


def _section_groups(section: dict) -> list[tuple[str, list[tuple[str, str]]]]:
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
            ("Where each concept appeared first", [_term_row(r) for r in first_seen])
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
                    f"{label} ({len(picked)} of {len(rising)})",
                    [_term_row(r, baseline_days=baseline_days) for r in picked],
                )
            )

    topics = [
        (str(r["topic"]), f"{_fmt(r['articles'])} articles, {_fmt(r.get('mentions'))} mentions")
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
                    share = f" — {_pct(float(section['mentions_tagged']) / float(total))} of them"
            except (TypeError, ValueError, ZeroDivisionError):
                share = ""
            topics = topics + [
                (
                    "Carrying no topic tag",
                    f"{_fmt(untagged)} mentions of {_fmt(total)}; the table above covers "
                    f"the tagged remainder{share}",
                )
            ]
        groups.append(("By topic", topics))

    channels = [
        (str(r["provenance"]), f"first with {_fmt(r['concepts_first_here'])} concept(s)")
        for r in section.get("channels") or []
    ]
    if channels:
        groups.append(("Concepts first seen in each channel", channels))

    events = [
        (str(r["event_type"]), _fmt(r["events"])) for r in section.get("by_event_type") or []
    ]
    if events:
        groups.append(("By event type", events))
    providers = [
        (str(r["provider"]), _fmt(r["events"])) for r in section.get("by_provider") or []
    ]
    if providers:
        groups.append(("By provider", providers))
    # "Every field here is what the provider published — magnitude, severity tier,
    # coordinates, time — carried through unchanged and never combined" was the
    # caveat over a list of one number. The examples carry every one of those fields
    # and were dropped at render, so the caveat described a document nobody had.
    alerts = []
    for r in section.get("examples") or []:
        bits = []
        if r.get("magnitude") is not None:
            bits.append(f"M {r['magnitude']}")
        if r.get("severity"):
            bits.append(str(r["severity"]))
        if r.get("event_time"):
            bits.append(str(r["event_time"])[:16])
        if r.get("provider"):
            bits.append(f"per {r['provider']}")
        alerts.append((str(r.get("place") or r.get("title") or "—"), " · ".join(bits) or "—"))
    if alerts:
        groups.append((f"What the providers reported ({len(alerts)} of {_fmt(section.get('events'))})", alerts))

    changes = []
    for r in section.get("law_examples") or []:
        bits = [str(r.get("jurisdiction") or "—")]
        if r.get("observed_at"):
            bits.append(f"observed {str(r['observed_at'])[:10]}")
        delta = r.get("delta_bytes")
        if delta is not None:
            bits.append(f"{_fmt(delta)} bytes changed")
        if r.get("flagged"):
            bits.append("flagged as large")
        changes.append((str(r.get("title") or "—"), " · ".join(bits)))
    for r in section.get("wiki_examples") or []:
        bits = ["wikipedia"]
        if r.get("observed_at"):
            bits.append(f"observed {str(r['observed_at'])[:10]}")
        if r.get("flagged"):
            bits.append("flagged as large")
        changes.append((str(r.get("title") or "—"), " · ".join(bits)))
    if changes:
        groups.append(("Which documents changed", changes))

    years = [
        (str(r["year"]), f"{_fmt(r['articles'])} articles on the same days")
        for r in section.get("years") or []
    ]
    if years:
        groups.append(("By year", years))

    counts: list[tuple[str, str]] = []
    if section.get("law_revisions") is not None:
        counts.append(
            (
                "Law revisions",
                f"{_fmt(section['law_revisions'])} "
                f"({_fmt(section.get('law_revisions_flagged'))} flagged as large)",
            )
        )
    if section.get("wiki_revisions") is not None:
        counts.append(
            (
                "Wikipedia revisions",
                f"{_fmt(section['wiki_revisions'])} "
                f"({_fmt(section.get('wiki_revisions_flagged'))} flagged as large)",
            )
        )
    if counts:
        groups.append(("Observed changes", counts))

    return groups


def _md_section(section: dict) -> list[str]:
    key = str(section.get("section", "section")).replace("_", " ")
    out = [f"## {key.capitalize()}", ""]
    if section.get("error"):
        out += [f"*This section could not be built: `{section['error']}`.*", ""]
        return out
    if section.get("skipped"):
        out += [f"*Not shown: {section['skipped']}.*", ""]
        return out

    w = section.get("window") or {}
    if w and not w.get("matches_period", True):
        # §12: a section whose window differs from the period must be VISIBLE.
        out += [f"*Window: {w.get('days')} days — not the edition's period.*", ""]

    groups = _section_groups(section)
    if not groups:
        out.append("*Nothing to report for this period.*")
    for label, rows in groups:
        if len(groups) > 1:
            out += [f"**{label}**", ""]
        out += [f"- **{subject}** — {rest}" for subject, rest in rows]
        if len(groups) > 1:
            out.append("")
    out.append("")
    if section.get("caveat"):
        out += [f"> {section['caveat']}", ""]
    return out


def _md_story(story: dict) -> list[str]:
    terms = ", ".join(story.get("shared_terms") or []) or "—"
    voice = " · **one source only**" if story.get("single_source") else ""
    out = [
        f"### {terms}",
        "",
        f"{_fmt(story.get('articles'))} articles · "
        f"{_fmt(story.get('distinct_sources'))} sources{voice}",
        "",
    ]
    nar = story.get("narration") or {}
    if nar.get("text"):
        if nar.get("narrated"):
            mark = f"*{_AI_LABEL}"
            if nar.get("partial"):
                mark += "; sentences that named something absent from the sources were removed"
            out += [f"{mark}.*", "", nar["text"], ""]
        else:
            out += [nar["text"], ""]
            if nar.get("fallback_reason"):
                out += [f"*No model text: {nar['fallback_reason']}.*", ""]
    return out


def _md_references(edition: dict) -> list[str]:
    """Sources that contributed — the reference list.

    External identity only. A local article id means a different article on a
    recipient's install, so it never leaves this machine in a published document.
    """
    top = (edition.get("masthead") or {}).get("top_sources") or []
    if not top:
        return []
    out = ["## References", "", "Largest contributors this period:", ""]
    for row in top:
        dom = row.get("domain") or "—"
        out.append(f"- {row.get('name') or dom} (`{dom}`) — {_fmt(row.get('articles'))} articles")
    out += [
        "",
        "*Article-level links are omitted on purpose: a local article id resolves to a "
        "different article on another install.*",
        "",
    ]
    return out


def _selection_line(edition: dict) -> str | None:
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
        parts.append(f"{shown} of {total} sections")
    if isinstance(st_shown, int) and isinstance(st_total, int) and st_shown < st_total:
        parts.append(f"{st_shown} of {st_total} stories")
    if not parts:
        return None
    return (
        f"This edition shows {' and '.join(parts)}; the rest were excluded by the "
        "operator before publishing. The record it was rendered from is unchanged."
    )


def _md_disclosures(edition: dict) -> list[str]:
    d = edition.get("disclosures") or {}
    sel = _selection_line(edition)
    # An operator's exclusion is a disclosure in its own right, so it prints even
    # when the edition carries no other one — otherwise the one case where the
    # document is least complete is the case where it says least about itself.
    if not d and not sel:
        return []
    out = ["### What this edition cannot see", ""]
    if sel:
        out.append(f"- {sel}")
    q = d.get("quarantined_in_period")
    if q:
        out.append(f"- {_fmt(q)} article(s) in the period are quarantined and excluded throughout.")
    u = d.get("mentions_without_a_date")
    if u:
        out.append(f"- {_fmt(u)} keyword mention(s) carry no date and are invisible to every window.")
    backlog = d.get("reindex_backlog") or {}
    if backlog.get("available") and backlog.get("articles_pending"):
        out.append(
            f"- {_fmt(backlog['articles_pending'])} imported article(s) await re-index, so they "
            "carry no keywords yet and are missing from every keyword figure here."
        )
    elif backlog.get("available") is False:
        out.append("- The re-index backlog could not be read — unknown, not zero.")
    cov = d.get("baseline_coverage") or {}
    if cov.get("complete") is False:
        out.append(f"- {cov.get('note')}")
    if len(out) == 2:
        out.append("- Nothing excluded beyond what the methods above state.")
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


def render_html(edition: dict) -> str:
    """The edition as ONE self-contained HTML page.

    No external stylesheet, font, script or image — a shared document that phones
    home would tell its recipient's network what the operator reads. Light and
    dark are both styled, because a document is read wherever it is opened.
    """
    p = edition.get("period") or {}
    m = edition.get("masthead") or {}
    body: list[str] = []

    body.append(f"<h1>{_e(_title(edition))}</h1>")
    body.append(
        f'<p class="lede">What rose in this corpus between {_e(p.get("start"))} and '
        f'{_e(p.get("last_day"))} — {_e(p.get("days"))} days.</p>'
    )

    body.append("<h2>This corpus, this period</h2><ul>")
    body.append(
        f"<li><strong>{_fmt(m.get('articles'))}</strong> articles from "
        f"<strong>{_fmt(m.get('sources_contributing'))}</strong> contributing sources</li>"
    )
    body.append(
        f"<li>The three largest carried <strong>{_pct(m.get('top_3_share'))}</strong></li>"
    )
    body.append(
        f"<li>Ingest on <strong>{_e(m.get('days_with_ingest'))}</strong> of "
        f"{_e(m.get('period_days'))} days</li>"
    )
    body.append(
        f"<li><strong>{_pct(m.get('corpus_share'))}</strong> of a corpus of "
        f"{_fmt(m.get('corpus_articles'))}</li>"
    )
    body.append("</ul>")
    for line in _masthead_splits(m):
        body.append(f'<p class="meta">{_e(line)}</p>')
    if m.get("caveat"):
        body.append(f'<p class="caveat">{_e(m["caveat"])}</p>')

    for section in edition.get("sections") or []:
        body.extend(_html_section(section))

    stories = (edition.get("stories") or {}).get("stories") or []
    if stories:
        body.append("<h2>Stories</h2>")
        for s in stories:
            body.extend(_html_story(s))
        cav = (edition.get("stories") or {}).get("caveat")
        if cav:
            body.append(f'<p class="caveat">{_e(cav)}</p>')

    top = m.get("top_sources") or []
    if top:
        body.append("<h2>References</h2><table><tr><th>Source</th><th>Articles</th></tr>")
        for row in top:
            body.append(
                f"<tr><td>{_e(row.get('name') or row.get('domain'))} "
                f'<span class="meta">{_e(row.get("domain"))}</span></td>'
                f"<td>{_fmt(row.get('articles'))}</td></tr>"
            )
        body.append("</table>")
        body.append(
            '<p class="meta">Article-level links are omitted on purpose: a local article '
            "id resolves to a different article on another install.</p>"
        )

    body.append("<h2>Methods &amp; caveats</h2>")
    if edition.get("method"):
        body.append(f'<p class="meta">{_e(edition["method"])}</p>')
    if edition.get("caveat"):
        body.append(f'<p class="caveat">{_e(edition["caveat"])}</p>')
    for line in _md_disclosures(edition):
        if line.startswith("- "):
            body.append(f'<p class="meta">{_e(line[2:])}</p>')
        elif line.startswith("### "):
            body.append(f"<h3>{_e(line[4:])}</h3>")

    body.append(
        "<footer>Generated "
        f"{_e(edition.get('generated_at') or datetime.now(UTC).isoformat())} by Open "
        "Omniscience from this operator's own corpus. Deterministic sections are computed "
        f"from the record <code>{_e(edition.get('filename') or 'the edition JSON')}</code>."
        "</footer>"
    )

    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(_title(edition))}</title><style>{_CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>\n"
    )


def _html_section(section: dict) -> list[str]:
    key = str(section.get("section", "section")).replace("_", " ").capitalize()
    out = [f"<h2>{_e(key)}</h2>"]
    if section.get("error"):
        out.append(f'<p class="meta">This section could not be built: {_e(section["error"])}.</p>')
        return out
    if section.get("skipped"):
        out.append(f'<p class="meta">Not shown: {_e(section["skipped"])}.</p>')
        return out

    w = section.get("window") or {}
    if w and not w.get("matches_period", True):
        out.append(
            f'<p class="caveat">Window: {_e(w.get("days"))} days — not the edition\'s period.</p>'
        )

    groups = _section_groups(section)
    if not groups:
        out.append('<p class="meta">Nothing to report.</p>')
    for label, rows in groups:
        if len(groups) > 1:
            out.append(f"<h3>{_e(label)}</h3>")
        items = "".join(
            f"<li><strong>{_e(subject)}</strong> — {_e(rest)}</li>" for subject, rest in rows
        )
        out.append(f"<ul>{items}</ul>")
    if section.get("caveat"):
        out.append(f'<p class="caveat">{_e(section["caveat"])}</p>')
    return out


def _html_story(story: dict) -> list[str]:
    terms = ", ".join(story.get("shared_terms") or []) or "—"
    voice = " · one source only" if story.get("single_source") else ""
    out = [
        f"<h3>{_e(terms)}</h3>",
        f'<p class="meta">{_fmt(story.get("articles"))} articles · '
        f'{_fmt(story.get("distinct_sources"))} sources{_e(voice)}</p>',
    ]
    nar = story.get("narration") or {}
    if nar.get("text"):
        if nar.get("narrated"):
            label = _AI_LABEL
            if nar.get("partial"):
                label += " · sentences naming something absent from the sources were removed"
            out.append(f'<p class="ai">{_e(label)}</p>')
            out.append(f'<p class="ai-text">{_e(nar["text"])}</p>')
        else:
            out.append(f"<p>{_e(nar['text'])}</p>")
            if nar.get("fallback_reason"):
                out.append(f'<p class="meta">No model text: {_e(nar["fallback_reason"])}.</p>')
    return out


def render(edition: dict, fmt: str) -> str:
    """Render ``edition`` as ``markdown`` or ``html``."""
    f = (fmt or "").strip().lower()
    if f in ("md", "markdown"):
        return render_markdown(edition)
    if f == "html":
        return render_html(edition)
    raise ValueError(f"unknown format {fmt!r}; known formats: markdown, html")
