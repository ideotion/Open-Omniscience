"""
Per-jurisdiction law coverage/freshness diagnostic.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S5 of the law-vertical brief (2026-07-17): "the maintainer's next 'is law working?'
is answered by one JSON." Per-jurisdiction tracked-document counts, baseline
coverage, freshness ages, and a per-document verdict tally (reusing the exact
classification the Governments -> Law UI already shows, src.api.law._verdict_of,
so there is never a second, drifting guess at what a status string means).

THE COMPLETENESS PRINCIPLE (brief §2, maintainer-clarified 2026-07-17): a tracked
document is an entry point, never a coverage claim. "Covering a jurisdiction" means
covering its OWN official enumeration of its legal corpus (France alone has 76
codes en vigueur).

S4 (2026-09-07) supplies the first real denominators. A live enumeration ADAPTER is
still network-gated and unbuilt, but 39 dated official counts across 32 countries were
already committed in the catalog and were going unread — Armenia's 208,987 acts,
Colombia's 87,392 normas, Cabo Verde's 76,947, Belarus's and Georgia's 26 codes each,
Uruguay's 13. Those are real, sourced denominators and this report now prints them
beside the tracked count, together with the countries that HAVE one and in which this
install tracks nothing at all.

What it still refuses to do is divide. A tracked document is act/code-level (ruling
A3) and the enumerated units range over codes, acts, volumes, gazette issues, treaties
and cases; a volume or a gazette issue contains many acts, and nothing in the catalog
declares which units count the same objects. Inferring that from the unit string is
the exact move ruling 47's extensive/intensive rail forbids ("declare it explicitly on
each catalog entry rather than inferring it from the unit string"), so no fraction is
computed anywhere and the reason travels with every jurisdiction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from src.database.models import LawDocument

#: The three coverage states, kept APART because they are three different facts and a
#: reader who cannot tell them apart learns nothing. Overloading one sentinel across
#: them is the recorded one-key-two-meanings defect.
COVERAGE_NO_COUNTRY = "no-country-on-tracked-documents"
COVERAGE_NO_ENUMERATION = "no-official-enumeration"
COVERAGE_UNIT_UNDECLARED = "enumerated-unit-undeclared"

_COVERAGE_REASONS = {
    COVERAGE_NO_COUNTRY: (
        "The documents tracked under this jurisdiction state no country, so the catalog's "
        "official enumerations (which are keyed by country) could not be looked up at all. "
        "This is a gap in what we know, not a statement that no enumeration exists."
    ),
    COVERAGE_NO_ENUMERATION: (
        "The catalog holds no dated official count for this jurisdiction's country, so "
        "there is no denominator to report. Coverage unknown."
    ),
    COVERAGE_UNIT_UNDECLARED: (
        "This jurisdiction's own official enumeration is known and printed below, and NO "
        "fraction is computed from it. Nothing in the catalog declares whether the "
        "enumerated unit counts the same objects a tracked document is — a tracked "
        "document is act/code-level (ruling A3), while the units actually present range "
        "over codes, acts, volumes, gazette issues and treaties, and a volume or a gazette "
        "issue contains many acts. Dividing across that would be a fabricated coverage "
        "figure, so the two numbers are published side by side and left that way until a "
        "ruling declares commensurability per entry (the precedent is ruling 47's "
        "extensive/intensive rail: declare it on the entry, never infer it from a unit "
        "string)."
    ),
}


def _figure(source: dict) -> dict | None:
    """Pure: one catalog row's official-enumeration figure, with its disclosures.

    Everything here is copied from the catalog verbatim. TWO disclosure channels, and
    both are needed because the caveat does not always live in the same place:

    * ``off_domain_source`` is DERIVED — the figure's ``source_url`` is not on the
      source's own domain, i.e. it was not read off the publisher's page. Two of the 39
      figures are this (Council of Europe's count cites Wikipedia; Mauritania's cites a
      news site), and it is checkable rather than remembered.
    * ``source_notes`` is the row's own notes, VERBATIM, because a figure's caveat
      sometimes sits there instead: the African Union's 80 is described in its notes as
      "a manual tally ... treat this as approximate, not authoritative", while its
      ``source_url`` is perfectly on-domain and the derived check cannot see it. No
      prose heuristic is applied to pull the caveat out — the reader gets the sentence.
    """
    oc = source.get("official_count")
    if not isinstance(oc, dict) or not isinstance(oc.get("value"), int):
        return None
    host = (urlparse(str(oc.get("source_url") or "")).hostname or "").lower()
    domain = str(source.get("domain") or "").lower()
    on_domain = bool(host) and bool(domain) and (
        host == domain or host.endswith("." + domain) or domain.endswith("." + host)
    )
    out = {
        "value": oc["value"],
        "unit": oc.get("unit"),
        "as_of": oc.get("as_of"),
        "source_url": oc.get("source_url"),
        "domain": source.get("domain"),
        "country": source.get("country"),
        "off_domain_source": not on_domain,
    }
    if source.get("notes"):
        out["source_notes"] = source["notes"]
    return out


def official_enumerations(catalog: dict | None = None) -> dict[str, list[dict]]:
    """Pure: the catalog's dated official enumeration figures, keyed by ISO-2 country.

    S4 of the law-vertical brief. These are the REAL denominators the completeness
    principle asks for — a jurisdiction's own official count of its legal corpus, each
    one read off a named page on a stated date by the session that recorded it (the
    catalog validator already refuses an undated or source-less count, precisely so a
    figure can never be an estimate). A country with several counts keeps all of them:
    Mali publishes both consolidated codes and gazette issues, and collapsing two
    different measurements into one number would invent a third.

    A ``value: 0`` is a REAL measurement and is kept as one — Nigeria's two figures are
    zero because the producing session fetched nigerialii.org and found the platform
    genuinely empty ("Real, important gap, not an estimate"). An absent figure and a
    measured zero are different facts and must never collapse.
    """
    if catalog is None:
        from src.law.catalog import load_legal_catalog

        catalog = load_legal_catalog()
    by_country: dict[str, list[dict]] = {}
    for s in catalog.get("sources", []):
        fig = _figure(s)
        if fig is None:
            continue
        country = str(s.get("country") or "").lower()
        if not country:
            continue
        by_country.setdefault(country, []).append(fig)
    return by_country


def _pdf_reach(session: Session, catalog: dict | None = None) -> dict:
    """S7 / question L6: say plainly how much of the law catalog a default install
    cannot read, instead of letting the report be silently narrower than the catalog.

    ``[pdf]`` is an optional pip extra (``pypdf``) and ``src.ingest.pdf`` degrades
    loudly without it, which is honest at the call site and invisible in a coverage
    report. L6's stated default is to keep it optional and SAY SO here; this is that
    sentence, with the numbers attached, because "some sources are PDF" and "63 of 275
    sources publish nothing else" are different facts.

    Both counts are FLOORS and say so in the payload. ``.pdf`` is a URL suffix, and a
    portal that serves a PDF from an extensionless URL (content-type only) is invisible
    to it; ``formats`` is a per-row declaration the producing session wrote down, and
    52 of the 275 rows declare none at all.
    """
    if catalog is None:
        from src.law.catalog import load_legal_catalog

        catalog = load_legal_catalog()
    from src.ingest.pdf import ocr_available, pdf_available

    available = pdf_available()
    declared = [s for s in catalog.get("sources", []) if (s.get("structured") or {}).get("formats")]
    pdf_only = [
        s for s in declared
        if [str(f).lower() for f in s["structured"]["formats"]] == ["pdf"]
    ]
    tracked_pdf = (
        session.query(LawDocument)
        .filter(LawDocument.url.ilike("%.pdf"))
        .count()
    )
    total_tracked = session.query(LawDocument).count()
    return {
        "pdf_extractor_available": available,
        "ocr_available": ocr_available(),
        "tracked_documents_whose_url_ends_pdf": tracked_pdf,
        "tracked_documents": total_tracked,
        "catalog_sources_with_a_declared_format_list": len(declared),
        "catalog_sources_publishing_pdf_only": len(pdf_only),
        "catalog_sources": len(catalog.get("sources", [])),
        "method": (
            "pypdf's presence (the [pdf] extra) and the OCR fallback's, reported as "
            "found; the tracked-document figure counts this install's own rows whose "
            "url ends .pdf; the catalog figures count rows whose declared format list "
            "is exactly [pdf]. BOTH catalog and tracked figures are FLOORS: a portal "
            "serving a PDF from an extensionless URL is invisible to a suffix test, and "
            "rows that declare no format list at all are not counted either way."
        ),
        "caveat": (
            (
                "The [pdf] extra is NOT installed, so this install cannot read a PDF "
                f"statute at all: {tracked_pdf} of the {total_tracked} documents it "
                f"tracks are PDFs by URL, and {len(pdf_only)} of the "
                f"{len(catalog.get('sources', []))} catalog sources publish nothing but "
                "PDF. Everything below is therefore narrower than the catalog, and that "
                "narrowing is a property of the install rather than of the law. "
                "Install the [pdf] extra to close it."
            )
            if not available
            else (
                "The [pdf] extra is installed, so a PDF statute is readable here. The "
                "counts below are kept because they are what a default install would "
                "lose, not because anything is currently degraded."
            )
        ),
    }


def law_coverage_report(
    session: Session, *, enumerations: dict[str, list[dict]] | None = None
) -> dict:
    """Counts + method, no score. See module docstring for the completeness caveat.

    ``enumerations`` defaults to the real committed catalog (byte-identical behaviour
    for every caller); a test passes a crafted map so a unit test is not asserting
    against the 225-source harvest, while one guard deliberately drives the real file.
    """
    from src.api.law import _verdict_of  # the ONE classification, reused (never a 2nd guess)

    docs = session.query(LawDocument).order_by(LawDocument.jurisdiction, LawDocument.id).all()
    by_jur: dict[str, list[LawDocument]] = {}
    for d in docs:
        by_jur.setdefault(d.jurisdiction, []).append(d)

    # S4: the catalog's own dated official counts, joined to a jurisdiction ONLY through
    # the country its own tracked documents state. Nothing is inferred from the
    # jurisdiction code: it is deliberately "ISO-ish" (uk, eu, int) and `uk` documents
    # state `gb`, so reading the code as a country would both miss that pair and risk
    # attaching some other country's enumeration to a code that happens to collide with
    # its ISO-2. LawDocument.country is the field S4b added for exactly this, and a
    # document that states none joins nothing — reported as its own state, not as
    # "no enumeration exists".
    # ONE catalog parse, shared by both consumers below. Read separately they cost 553 ms
    # each on the shipped file, and this report is a member of the all-diagnostics bundle
    # -- paying twice for the same bytes is avoidable rather than acceptable.
    from src.law.catalog import load_legal_catalog

    catalog = load_legal_catalog()
    enum_by_country = (
        official_enumerations(catalog) if enumerations is None else enumerations
    )
    tracked_countries: set[str] = set()

    now = datetime.now(UTC)

    def _age_hours(dt) -> float | None:
        if dt is None:
            return None
        # SQLite stores naive datetimes; the app writes them from datetime.now(UTC),
        # so treat a naive value as UTC rather than mixing aware/naive subtraction.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (now - dt).total_seconds() / 3600.0

    jurisdictions = []
    for jur, rows in sorted(by_jur.items()):
        tracked = len(rows)
        baselined = sum(1 for r in rows if r.baseline_text is not None)
        verdicts: dict[str, int] = {}
        ages: list[float] = []
        never_checked = 0
        for r in rows:
            age = _age_hours(r.last_checked_at)
            if age is None:
                # Never checked: no real outcome to classify -- counted ONLY in the
                # dedicated `never_checked` field, never smeared into `verdicts` too
                # (which would double-count the same fact two different ways).
                never_checked += 1
            else:
                ages.append(age)
                v = _verdict_of(r.last_status)
                verdicts[v] = verdicts.get(v, 0) + 1
        countries = sorted({(r.country or "").lower() for r in rows if r.country})
        tracked_countries.update(countries)
        figures = [f for c in countries for f in enum_by_country.get(c, [])]
        if not countries:
            state = COVERAGE_NO_COUNTRY
        elif not figures:
            state = COVERAGE_NO_ENUMERATION
        else:
            state = COVERAGE_UNIT_UNDECLARED
        jurisdictions.append(
            {
                "jurisdiction": jur,
                "tracked": tracked,
                "baselined": baselined,
                "baseline_pct": round(100 * baselined / tracked, 1) if tracked else 0.0,
                "never_checked": never_checked,
                "oldest_check_age_hours": round(max(ages), 1) if ages else None,
                "newest_check_age_hours": round(min(ages), 1) if ages else None,
                "verdicts": verdicts,
                # THE COMPLETENESS PRINCIPLE: never a fabricated coverage fraction. The
                # tracked count and the jurisdiction's own enumeration sit side by side
                # and are NEVER divided — see _COVERAGE_REASONS.
                "coverage": {
                    "state": state,
                    "reason": _COVERAGE_REASONS[state],
                    "countries": countries,
                    "official_enumeration": figures,
                },
            }
        )

    total_docs = len(docs)
    total_baselined = sum(1 for d in docs if d.baseline_text is not None)
    # The gap made legible: countries whose OWN official enumeration this install knows
    # and in which it tracks nothing at all. Without this the report can only describe
    # the jurisdictions already being watched, which is the shape that lets a vertical
    # look healthy while covering almost nothing.
    untracked = sorted(set(enum_by_country) - tracked_countries)
    return {
        "documents": total_docs,
        "baselined": total_baselined,
        "jurisdictions": jurisdictions,
        "extraction": _pdf_reach(session, catalog),
        "enumeration": {
            "countries_with_an_official_count": len(enum_by_country),
            "figures": sum(len(v) for v in enum_by_country.values()),
            "countries_enumerated_but_untracked": len(untracked),
            "untracked": [
                {"country": c, "official_enumeration": enum_by_country[c]} for c in untracked
            ],
            "method": (
                "Every dated official count committed in the law catalog, keyed by ISO-2 "
                "country and copied verbatim (value, unit, as_of, source_url). The "
                "catalog validator already refuses a count with no as_of or no "
                "source_url, so each of these was read off a named page on a stated "
                "date rather than estimated. A country with several counts keeps all of "
                "them rather than being collapsed into one. `off_domain_source` is "
                "derived — the figure was not read off the publisher's own domain — and "
                "`source_notes` carries the catalog row's own words, because a figure's "
                "caveat sometimes lives there instead (the African Union's 80 is a "
                "manual tally its notes call approximate, from an on-domain page)."
            ),
            "caveat": (
                "These are denominators, not coverage: they are joined to a tracked "
                "jurisdiction only through the country its own documents state, and no "
                "fraction is computed from any of them. A value of 0 is a REAL "
                "measurement, not a gap — Nigeria's two zeros were fetched and found "
                "genuinely empty. Some units are floors or approximations and say so in "
                "the unit itself (the UN's 'over 560, not an exact figure')."
            ),
        },
        "method": (
            "Per-jurisdiction tracked-document counts, baseline coverage, freshness "
            "ages (hours since last_checked_at), and -- for documents that have "
            "actually been checked at least once -- their last_status classified "
            "into a small honest verdict set (robots_blocked / error / empty / "
            "changed / reverted / baselined / unchanged / other — the same "
            "classification the Governments -> Law UI shows). A document never yet "
            "checked has no outcome to classify, so it is counted only in "
            "`never_checked`, never smeared into `verdicts` too. Counts and ages "
            "only, no score."
        ),
        "caveat": (
            "A tracked-document count is an entry point, never a coverage claim: "
            "\"covering a jurisdiction\" means covering its OWN official enumeration "
            "of its legal corpus (e.g. France's 76 codes en vigueur). Where the "
            "catalog knows that enumeration it is printed beside the tracked count "
            "and the two are NEVER divided — a tracked document is act/code-level "
            "while the enumerated units run from codes to volumes to gazette issues, "
            "and nothing declares which of those count the same objects. Where the "
            "catalog knows no enumeration, coverage stays unknown. Either way no "
            "jurisdiction's tracked count is presented as if it were the whole corpus."
        ),
    }
