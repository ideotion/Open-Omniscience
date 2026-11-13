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

THE COVERAGE FLOOR (v0.6.0, row C slice S1; Q107, Q912): the report also carries ``floor``, which answers the question the
per-jurisdiction rows cannot -- not "what does this install watch" but "of every country the twelve UI languages put on the
floor (``configs/language_countries.yml``, read through the ONE loader ``src.civic.coverage_floor.load_floor``), where does each
one stand". One of four states per country, never a blank: tracked, verified-not-yet-tracked, unverified, no-eligible-source.
It counts and lists, and it never divides: the denominator is a floor of countries, the numerators are states, and no score
is built from them.
"""

from __future__ import annotations

from collections.abc import Callable
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
#: The catalogue file is there and could not be read: the denominators are UNCHECKED, which is not "none exist".
COVERAGE_UNCHECKED = "catalogue-unreadable"

_COVERAGE_REASONS = {
    COVERAGE_UNCHECKED: (
        "The law catalogue file is present but could not be read, so this jurisdiction's official enumeration was "
        "not looked up. Unchecked, not absent: nothing here says no enumeration exists."
    ),
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
            "pypdf's presence and the OCR fallback's, reported as found; the "
            "tracked-document figure counts this install's own rows whose url ends "
            ".pdf; the catalog figures count rows whose declared format list is exactly "
            "[pdf]. BOTH catalog and tracked figures are FLOORS: a portal serving a PDF "
            "from an extensionless URL is invisible to a suffix test, and rows that "
            "declare no format list at all are not counted either way."
        ),
        # RULING L6 (2026-09-15) RETIRED THE "WITHOUT [pdf]" FRAMING, and the retirement
        # is not cosmetic: pypdf ships in the DEFAULT install now, so "the [pdf] extra is
        # not installed" no longer describes a choice an operator made — it describes a
        # broken or deliberately-stripped environment. Telling that operator to "install
        # the [pdf] extra to close it" would point them at a knob that is already on, and
        # the sibling sentence ("what a default install would lose") became false in the
        # same edit, because a default install now loses nothing. The COUNTS are
        # unchanged: they measure the catalogue, not the environment.
        "caveat": (
            (
                "pypdf is missing from this install, so it cannot read a PDF statute at "
                f"all: {tracked_pdf} of the {total_tracked} documents it tracks are PDFs "
                f"by URL, and {len(pdf_only)} of the "
                f"{len(catalog.get('sources', []))} catalog sources publish nothing but "
                "PDF. Everything below is therefore narrower than the catalog, and that "
                "narrowing is a property of this install rather than of the law. pypdf "
                "ships in the default install, so this is a dependency that did not "
                "arrive rather than a capability anyone chose to leave out — reinstall "
                "to close it."
            )
            if not available
            else (
                "pypdf ships in the default install, so a PDF statute is readable here. "
                "The counts below measure how much of the catalogue is PDF-only; they "
                "are a property of the world's gazettes, not a shortfall of this install."
            )
        ),
    }


#: The four states a floor country can be in, kept APART because each is a different fact and a reader who cannot tell them
#: apart learns nothing. ``no-eligible-source`` is a state like the others, never a blank: it is the one that says "there is
#: research to do here", where a blank would say "nothing to report".
FLOOR_TRACKED = "tracked"
FLOOR_VERIFIED_UNTRACKED = "verified-not-yet-tracked"
FLOOR_UNVERIFIED = "unverified"
FLOOR_NO_SOURCE = "no-eligible-source"
FLOOR_STATES: tuple[str, ...] = (FLOOR_TRACKED, FLOOR_VERIFIED_UNTRACKED, FLOOR_UNVERIFIED, FLOOR_NO_SOURCE)
#: Only when the catalogue could not be read: what is tracked is still true (it comes from the database), what could be
#: reached is not known. Unchecked, which is not "none".
FLOOR_UNCHECKED = "unchecked"

#: The catalogue's many-country codes. A source filed under one of these serves many countries at once (EUR-Lex, the African
#: Union, the UN Treaty Collection), so it is credited to NO single floor country: crediting Germany for an EU portal would
#: put a country on the floor's "reachable" side on the strength of a source that is not its own.
_MANY_COUNTRY_CODES: tuple[str, ...] = ("eu", "int")
#: Hong Kong and Macau are named by the Chinese seed row but are territories, and the floor file excludes territories by a
#: recorded scoping decision (S06-02 S1). They are reported beside ``zh``, never added to the floor.
ZH_NAMED_BEYOND_FLOOR: tuple[str, ...] = ("hk", "mo")
#: ``LawDocument.category`` values that are NOT law: an IP-office record and a court decision. The floor is a law floor, so a
#: tracked document of either class credits no country (it is counted in ``non_law_documents`` instead of vanishing), the same
#: line :func:`src.law.catalog.source_is_law_authority` draws on the source side.
_NON_LAW_DOCUMENT_CATEGORIES: frozenset[str] = frozenset({"ip", "case-law", "case_law"})

_FLOOR_METHOD = (
    "Every country in configs/language_countries.yml, read through src.civic.coverage_floor.load_floor; the official, "
    "de-facto and regional bases all count and each is kept. One state per country: tracked (a tracked document states the "
    "country; an IP record or a court decision is not law and does not count), verified-not-yet-tracked (a law-authority source is listed and a researcher or an adapter recorded a "
    "verification of it, no document tracked), unverified (a law-authority source is listed, none verified), "
    "no-eligible-source (none listed: research to do, not a verdict on the country). Verified is either channel: research "
    "status fetched or search-verified, or an adapter that read the host live or from a fixture. An IP office or a "
    "case-law site is not a law authority. A source filed under eu or int serves many countries and is credited to none "
    "(many_country_sources); a document that states no country is credited to none (unplaced_documents), and a country is "
    "never inferred from a jurisdiction code. A country under two languages is in both rows and once in by_state. "
    "Within a state, countries go by population reached (R679, the operator's dated table, see order); those it lacks, "
    "or all of them without one, go by code. Hong Kong and Macau are named by the Chinese seed row, are not on "
    "the floor (it excludes territories) and are reported beside zh."
)
_FLOOR_CAVEAT = (
    "A state is where the catalogue and this install stand, not a statement about a legal system: no-eligible-source means "
    "the catalogue lists no law-authority source, not that none exists. The floor file is itself unverified (see "
    "verification_status): its country set is a denominator, not a settled one. A tracked document is an entry point, "
    "never a coverage claim, and no fraction or score is computed here."
)


def _floor_unchecked(reason: str | None, docs: list) -> dict:
    """The floor block when the catalogue could not be read: the database half (what is tracked) is still true, the rest
    is null with the reason, and no country is read as "no source" for a lookup that never happened."""
    return floor_report(docs, None, reason=reason)


def floor_order(population: dict | None) -> tuple[dict, Callable[[str], tuple[int, float, str]]]:
    """The order of countries within a state (R679): population reached, from the operator's DATED table.

    Returns ``(order block, sort key)``. The table is an operator drop-in (``src.stats.population``), absent by default:
    with no usable table every country is listed by code and the block says why, so "listed by code" is never mistaken for
    a ranking. With one, countries go by population, largest first, and a country the table lacks follows by code and is
    named in ``missing`` (filled by the caller), never given an invented figure. The populations themselves are not
    copied into the report: the order and the table's source and date are what it states.
    """
    if population is None:
        from src.stats.population import load_population_table

        population = load_population_table()
    if population.get("status") != "ok":
        reason = population.get("reason") or "no usable population table"
        return {"by": "code", "source": None, "as_of": None, "reason": reason, "missing": []}, (lambda cc: (0, 0.0, cc))
    weights: dict = population.get("weights") or {}
    block: dict = {"by": "population", "source": population.get("source"), "as_of": population.get("as_of"), "reason": None,
             "missing": []}
    return block, (lambda cc: (0, -float(weights[cc]), cc) if cc in weights else (1, 0.0, cc))


def floor_report(
    docs: list, catalog: dict | None, floor: dict | None = None, *, reason: str | None = None, population: dict | None = None
) -> dict:
    """Pure: where each country on the language coverage floor stands, per language and per state.

    ``docs`` are the tracked :class:`LawDocument` rows, ``catalog`` the parsed law catalogue (``None`` = it could not be read,
    ``reason`` says why), ``floor`` the parsed floor (default: the one loader), ``population`` the operator's population table
    as :func:`src.stats.population.load_population_table` returns it (default: that loader), which orders the countries
    within each state (:func:`floor_order`). Counts and lists only; no fraction, no score.
    """
    from src.law.catalog import source_is_law_authority, source_is_verified

    if floor is None:
        from src.civic.coverage_floor import load_floor

        floor = load_floor()
    countries: list[str] = list(floor.get("countries") or [])
    languages: dict = floor.get("languages") or {}
    out: dict = {
        "state": "checked",
        "reason": None,
        "as_of": floor.get("as_of") or None,
        "verification_status": floor.get("verification_status") or None,
        "countries": len(countries),
        "method": _FLOOR_METHOD,
        "caveat": _FLOOR_CAVEAT,
    }
    if not countries:
        # An absent or empty floor file is a floor of NOTHING, and a report of "0 of 0" would read as complete.
        return {
            **out,
            "state": "unchecked",
            "reason": "the floor file (configs/language_countries.yml) is absent, unreadable or lists no country",
            **dict.fromkeys(
                ("languages", "by_state", "order", "zh_beyond_floor", "many_country_sources", "unplaced_documents", "non_law_documents", "invalid_rows")
            ),
        }

    tracked: set[str] = set()
    unplaced: dict[str, int] = {}
    non_law: dict[str, int] = {}
    docs_by_language: dict[str, int] = {}
    for d in docs:
        category = (getattr(d, "category", None) or "").strip().lower()
        if category in _NON_LAW_DOCUMENT_CATEGORIES:
            non_law[category] = non_law.get(category, 0) + 1
            continue
        cc = (getattr(d, "country", None) or "").strip().lower()
        if cc:
            tracked.add(cc)
        else:
            unplaced[d.jurisdiction] = unplaced.get(d.jurisdiction, 0) + 1
        lang = (getattr(d, "language", None) or "").strip().lower()
        if lang:
            docs_by_language[lang] = docs_by_language.get(lang, 0) + 1

    # country -> is any of its law-authority sources verified.  A many-country code credits no country.
    reachable: dict[str, bool] = {}
    many: dict[str, dict[str, bool]] = {code: {} for code in _MANY_COUNTRY_CODES}
    if catalog is not None:
        for s in catalog.get("sources") or []:
            if not source_is_law_authority(s):
                continue
            cc = str(s.get("country") or "").strip().lower()
            verified = source_is_verified(s)
            if cc in many:
                many[cc][str(s.get("domain") or "")] = verified
            elif cc:
                reachable[cc] = reachable.get(cc, False) or verified

    def state_of(cc: str) -> str:
        if cc in tracked:
            return FLOOR_TRACKED
        if catalog is None:
            return FLOOR_UNCHECKED
        if cc not in reachable:
            return FLOOR_NO_SOURCE
        return FLOOR_VERIFIED_UNTRACKED if reachable[cc] else FLOOR_UNVERIFIED

    states = [*FLOOR_STATES, *([FLOOR_UNCHECKED] if catalog is None else [])]
    by_state: dict[str, list[str]] = {st: [] for st in states}
    order, order_key = floor_order(population)
    for cc in sorted(countries, key=order_key):
        by_state[state_of(cc)].append(cc)
    if order["by"] == "population":
        order["missing"] = sorted(cc for cc in countries if order_key(cc)[0])

    rows = []
    for code, block in languages.items():
        row: dict = {"language": code}
        counts = dict.fromkeys(states, 0)
        listed: dict[str, list[str]] = {}
        contested = []
        for entry in block.get("countries") or []:
            cc = entry["cc"]
            listed.setdefault(entry["basis"], []).append(cc)
            counts[state_of(cc)] += 1
            if entry.get("contested"):
                contested.append(cc)
        row.update(listed)  # one list per basis present (official / de-facto / regional), the basis kept
        if contested:
            row["contested"] = contested
        row["states"] = counts
        row["documents"] = docs_by_language.get(code, 0)
        rows.append(row)

    # zh is its own line (the standing Q911 emphasis): the three floor countries it lists are in its row above, and the two
    # territories its seed row names are here, beside it, with the state they would have if they were on the floor.
    out["languages"] = rows
    out["by_state"] = by_state
    out["order"] = order
    out["zh_beyond_floor"] = {cc: state_of(cc) for cc in ZH_NAMED_BEYOND_FLOOR}
    out["many_country_sources"] = many if catalog is not None else None
    out["unplaced_documents"] = unplaced
    out["non_law_documents"] = non_law
    out["invalid_rows"] = floor.get("invalid") or []
    if catalog is None:
        out.update(state="unchecked", reason=reason)
    return out


def law_coverage_report(
    session: Session, *, enumerations: dict[str, list[dict]] | None = None
) -> dict:
    """Counts + method, no score. See module docstring for the completeness caveat.

    ``enumerations`` defaults to the real committed catalog (byte-identical behaviour
    for every caller); a test passes a crafted map so a unit test is not asserting
    against the 225-source harvest, while one guard deliberately drives the real file.
    """
    from src.api.law import _verdict_of  # the ONE classification, reused (never a 2nd guess)
    from src.database.country_form import order_key

    docs = sorted(session.query(LawDocument).all(), key=lambda d: order_key(d.jurisdiction, d.id))  # see order_key
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
    from src.law.catalog import LawCatalogUnreadable, load_legal_catalog
    from src.monitoring.secret_scrub import http_detail

    # A catalogue that is there and cannot be read ends the denominators as UNCHECKED with the reason, in the report
    # itself: the tracked-document counts below come from the database and stay true, and nothing is read as "no
    # enumeration exists".
    catalog_error: str | None = None
    try:
        catalog = load_legal_catalog()
    except LawCatalogUnreadable as exc:
        catalog, catalog_error = None, http_detail(exc)
    enum_by_country = (
        {} if catalog_error else official_enumerations(catalog) if enumerations is None else enumerations
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
    states_used: set[str] = set()
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
        elif catalog_error:
            state = COVERAGE_UNCHECKED
        elif not figures:
            state = COVERAGE_NO_ENUMERATION
        else:
            state = COVERAGE_UNIT_UNDECLARED
        states_used.add(state)
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
    unchecked = {"state": "unchecked", "reason": catalog_error}
    # The usual keys stay, null: a figure that was not looked up is not a zero (an absent key would read as one).
    unchecked_extraction = {
        **unchecked,
        **dict.fromkeys(
            (
                "pdf_extractor_available", "ocr_available", "tracked_documents_whose_url_ends_pdf", "tracked_documents",
                "catalog_sources_with_a_declared_format_list", "catalog_sources_publishing_pdf_only", "catalog_sources",
                "method", "caveat",
            )
        ),
    }
    unchecked_enumeration = {
        **unchecked,
        **dict.fromkeys(
            ("countries_with_an_official_count", "figures", "countries_enumerated_but_untracked", "untracked", "method", "caveat")
        ),
    }
    return {
        "documents": total_docs,
        "baselined": total_baselined,
        "catalog": {"readable": catalog_error is None, "error": catalog_error},
        "jurisdictions": jurisdictions,
        # Each state's reason ONCE, for the states this report uses: a jurisdiction's `coverage.state` is the key into it.
        # Stated per jurisdiction it was the same paragraph again for every row (710 bytes for the commonest state).
        "coverage_reasons": {st: _COVERAGE_REASONS[st] for st in sorted(states_used)},
        "floor": _floor_unchecked(catalog_error, docs) if catalog_error else floor_report(docs, catalog),
        "extraction": unchecked_extraction if catalog_error else _pdf_reach(session, catalog),
        "enumeration": unchecked_enumeration if catalog_error else {
            "countries_with_an_official_count": len(enum_by_country),
            "figures": sum(len(v) for v in enum_by_country.values()),
            "countries_enumerated_but_untracked": len(untracked),
            # The row's key IS the country, so the figures drop their own copy of it (the same pair of letters, once per
            # figure; every other consumer of a figure keeps it, a jurisdiction can span several countries).
            "untracked": [
                {
                    "country": c,
                    "official_enumeration": [{k: v for k, v in f.items() if k != "country"} for f in enum_by_country[c]],
                }
                for c in untracked
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
            "changed / reverted / baselined / unchanged / re_extracted / deferred / other — the same "
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
