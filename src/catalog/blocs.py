"""Country GROUPS, and the fact that membership changes over time.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field feedback 2026-08-07, rulings 45 and 47. Two lenses were ruled — continents AND
World Bank regions — and one property governs both: **membership is time-varying, and a
figure computed with the wrong roster is wrong in a way no reader can detect.** BRICS was
five members until 2024, NATO gained Finland in 2023 and Sweden in 2024, the UK left the
EU in 2020. Compute "the EU" over a 1995 series with today's roster and the number looks
entirely normal.

So membership resolves AS OF the figure's year, and every surface states the vintage of
the registry it resolved against — including side-by-side comparison, which feels like it
is "not computing anything" and is exactly where a stale roster hides.

THREE STATES, not two. ``joined`` and ``left`` cannot express a SUSPENDED member (several
African Union members have been suspended after coups), and collapsing suspension into
either one is a false claim about a real situation. ``suspended_from`` is therefore its
own field, and ``members_as_of`` reports suspended members separately rather than
silently keeping or dropping them — the caller decides, because the right answer differs
between "who is in this bloc" and "who is bound by its statistics".

WHAT IS POPULATED HERE, AND WHAT IS DELIBERATELY EMPTY:

* **Continents** — real and complete, resolved from the shipped ``CONTINENT_OF`` table
  (253 territories). A country's continent does not change, so these carry no dates.
* **Political blocs** (BRICS, NATO, EU, G7, G20, ASEAN, …) — **EMPTY**. Their accession
  dates are sourced facts, and the sandbox that wrote this module cannot reach a source.
  Ruling 45's own instruction is that a member whose accession date cannot be sourced is
  recorded ``joined=None`` WITH the gap stated, and that no date is ever guessed to make a
  series continuous. An empty table that says why is honest; a table of plausible dates is
  not, and would be indistinguishable from a correct one on inspection.
* **World Bank regions** — **populated 2026-08-07** from a live ``/v2/country`` read: all
  217 economies across the seven regions. They are NOT continents — Sub-Saharan Africa
  excludes Egypt, Libya, Tunisia, Algeria and Morocco — which is precisely why ruling 47
  asked for both lenses rather than treating one as a rename of the other.

  Their membership is UNDATED, and that is a real weakness rather than a simplification.
  The Bank reassigns economies between regions — Afghanistan and Pakistan moved out of
  South Asia, and the region was renamed to match — but publishes no dated history of
  those moves, only the current assignment. So the registry vintage is the only thing
  saying which assignment a figure was computed under, where a bloc can say it per member.
  Pairing a WB-region figure across vintages can therefore compare different country sets
  silently; the group's ``notes`` say so on every payload.

A KNOWN LIMIT, stated rather than papered over: a country that did not yet exist in the
requested year (South Sudan before 2011) is still listed as a member and simply reports no
value, so it lands in the aggregation's coverage gap alongside countries that existed and
did not report. Separating the two needs sourced independence dates, which is the same
acquisition task as the bloc dates. The coverage wording is neutral between the two cases
("did not report this indicator for this period"), which is true either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.catalog.countries import CONTINENT_OF, CONTINENTS

__all__ = [
    "BLOC_REGISTRY_AS_OF",
    "Group",
    "Membership",
    "group_names",
    "groups_of_kind",
    "members_as_of",
    "resolve_group",
]

#: When this registry's MEMBERSHIP data was last curated. Every payload carries it, per
#: ruling 45 — a roster is only meaningful beside the date it was true.
BLOC_REGISTRY_AS_OF = "2026-08"

#: Continents are a partition of territories, not a political grouping, so they are not
#: a "bloc" and the Global bucket (the transnational `int`/`eu` codes) is not a continent.
_NOT_A_CONTINENT = {"Global"}


@dataclass(frozen=True)
class Membership:
    """One area's membership of one group, with its own sourced dates.

    ``joined is None`` means one of two very different things, and the difference is
    carried by ``dates_apply``: for a continent there is no accession to date, and for a
    bloc it means the date could not be sourced. Never a guess in either case.
    """

    area: str
    joined: str | None = None  # ISO date, or None
    left: str | None = None
    suspended_from: str | None = None
    source: str | None = None  # the URL the dates were read from


@dataclass(frozen=True)
class Group:
    """A named set of areas — a continent, a World Bank region or a political bloc."""

    key: str
    label: str
    kind: str  # "continent" | "wb_region" | "bloc"
    members: tuple[Membership, ...] = ()
    #: False for continents: membership is not dated because it does not change.
    dates_apply: bool = True
    #: Stated when the group is known to exist but its membership is not held here.
    unpopulated_reason: str | None = None
    notes: str | None = None


def _continent_groups() -> tuple[Group, ...]:
    by_continent: dict[str, list[str]] = {}
    for area, continent in CONTINENT_OF.items():
        if continent in _NOT_A_CONTINENT:
            continue
        by_continent.setdefault(continent, []).append(area)
    out = []
    for continent in CONTINENTS:
        if continent in _NOT_A_CONTINENT or continent not in by_continent:
            continue
        out.append(
            Group(
                key=continent.lower().replace(" ", "-"),
                label=continent,
                kind="continent",
                members=tuple(
                    Membership(area=a) for a in sorted(by_continent[continent])
                ),
                dates_apply=False,
                notes=(
                    "A geographic partition of territories, not a political grouping. "
                    "Membership carries no dates because it does not change; a territory "
                    "that did not exist in a given year simply reports no value."
                ),
            )
        )
    return tuple(out)


_BLOC_GAP = (
    "Membership is not held: accession and departure dates are sourced facts and none "
    "were available offline. Ruling 45 forbids guessing a date to make a series "
    "continuous, so this group is listed as known-but-unpopulated rather than filled "
    "with plausible values. It becomes usable when the networked research pass returns "
    "dated, sourced rosters."
)

#: The World Bank's own region for each of the 217 economies in its country list, read
#: off /v2/country on 2026-08-07. These regions are NOT continents — "Sub-Saharan Africa"
#: excludes Egypt, Libya, Tunisia, Algeria and Morocco, which the Bank files under MENA —
#: which is why both lenses ship and neither substitutes for the other.
#:
#: The MENA region has been RENAMED and RESHAPED: it is "Middle East, North Africa,
#: Afghanistan & Pakistan", and those two countries moved out of South Asia. The
#: arithmetic corroborates it rather than taking it on trust — South Asia comes out at
#: SIX members here, where it has historically had eight. Malta is also in MEA, not ECS.
#: A series pairing a pre-change SAS or MEA figure with a post-change one is therefore
#: comparing different populations, which is why this table is dated and registered.
_WB_REGION_MEMBERS: dict[str, tuple[str, ...]] = {
    "EAS": (
        "as", "au", "bn", "cn", "fj", "fm", "gu", "hk", "id", "jp", "kh", "ki", "kp",
        "kr", "la", "mh", "mm", "mn", "mo", "mp", "my", "nc", "nr", "nz", "pf", "pg",
        "ph", "pw", "sb", "sg", "th", "tl", "to", "tv", "vn", "vu", "ws",
    ),
    "ECS": (
        "ad", "al", "am", "at", "az", "ba", "be", "bg", "by", "ch", "cy", "cz", "de",
        "dk", "ee", "es", "fi", "fo", "fr", "gb", "ge", "gi", "gl", "gr", "hr", "hu",
        "ie", "im", "is", "it", "jg", "kg", "kz", "li", "lt", "lu", "lv", "mc", "md",
        "me", "mk", "nl", "no", "pl", "pt", "ro", "rs", "ru", "se", "si", "sk", "sm",
        "tj", "tm", "tr", "ua", "uz", "xk",
    ),
    "LCN": (
        "ag", "ar", "aw", "bb", "bo", "br", "bs", "bz", "cl", "co", "cr", "cu", "cw",
        "dm", "do", "ec", "gd", "gt", "gy", "hn", "ht", "jm", "kn", "ky", "lc", "mf",
        "mx", "ni", "pa", "pe", "pr", "py", "sr", "sv", "sx", "tc", "tt", "uy", "vc",
        "ve", "vg", "vi",
    ),
    "MEA": (
        "ae", "af", "bh", "dj", "dz", "eg", "il", "iq", "ir", "jo", "kw", "lb", "ly",
        "ma", "mt", "om", "pk", "ps", "qa", "sa", "sy", "tn", "ye",
    ),
    "NAC": ("bm", "ca", "us"),
    "SAS": ("bd", "bt", "in", "lk", "mv", "np"),
    "SSF": (
        "ao", "bf", "bi", "bj", "bw", "cd", "cf", "cg", "ci", "cm", "cv", "er", "et",
        "ga", "gh", "gm", "gn", "gq", "gw", "ke", "km", "lr", "ls", "mg", "ml", "mr",
        "mu", "mw", "mz", "na", "ne", "ng", "rw", "sc", "sd", "sl", "sn", "so", "ss",
        "st", "sz", "td", "tg", "tz", "ug", "za", "zm", "zw",
    ),
}

#: The Channel Islands is a World Bank economy (`CHI`, alpha-2 `JG`) and a member of
#: Europe & Central Asia, but `JG` is not ISO 3166-1 and `to_iso2` correctly refuses it —
#: so no figure for it can ever reach an aggregate through this app's pipeline. It is
#: listed as a member anyway. Dropping it to make the region's coverage completable would
#: be exactly the move this module exists to prevent: a real member deleted so a number
#: stops carrying a caveat. It surfaces as a permanent coverage gap, which is the truth.
UNREPRESENTABLE_MEMBERS: frozenset[str] = frozenset({"jg"})

#: Known groups whose membership is deliberately EMPTY. Naming them is the point: a
#: caller can say "BRICS exists and we cannot yet compute it", which is a different and
#: more useful answer than "no such group".
_UNPOPULATED: tuple[Group, ...] = tuple(
    Group(key=key, label=label, kind="bloc", unpopulated_reason=_BLOC_GAP)
    for key, label in (
        ("brics", "BRICS"),
        ("g7", "G7"),
        ("g20", "G20"),
        ("nato", "NATO"),
        ("african-union", "African Union"),
        ("asean", "ASEAN"),
        ("mercosur", "Mercosur"),
        ("caricom", "CARICOM"),
        ("gcc", "Gulf Cooperation Council"),
        ("opec", "OPEC"),
        ("commonwealth", "Commonwealth of Nations"),
        ("francophonie", "Organisation internationale de la Francophonie"),
        ("european-union", "European Union"),
    )
) + tuple(
    Group(
        key=key,
        label=label,
        kind="wb_region",
        members=tuple(Membership(area=a) for a in _WB_REGION_MEMBERS[code]),
        # The Bank reassigns economies between regions (Afghanistan and Pakistan moved
        # out of South Asia), but it publishes no dated history of those moves -- only
        # the CURRENT assignment. So membership here is undated, and the registry
        # vintage is the only thing that says which assignment a figure was computed
        # under. That is weaker than the bloc model and is stated rather than hidden.
        dates_apply=False,
        notes=(
            "The World Bank's own region, as of the registry vintage. NOT a continent: "
            "Sub-Saharan Africa excludes Egypt, Libya, Tunisia, Algeria and Morocco. The "
            "Bank reassigns economies without publishing a dated history, so a figure "
            "from an earlier vintage may have been computed over a different set."
        ),
    )
    for key, label, code in (
        ("wb-east-asia-pacific", "East Asia & Pacific", "EAS"),
        ("wb-europe-central-asia", "Europe & Central Asia", "ECS"),
        ("wb-latin-america-caribbean", "Latin America & Caribbean", "LCN"),
        ("wb-middle-east-north-africa",
         "Middle East, North Africa, Afghanistan & Pakistan", "MEA"),
        ("wb-north-america", "North America", "NAC"),
        ("wb-south-asia", "South Asia", "SAS"),
        ("wb-sub-saharan-africa", "Sub-Saharan Africa", "SSF"),
    )
)


_GROUPS: dict[str, Group] = {
    g.key: g for g in (*_continent_groups(), *_UNPOPULATED)
}


def group_names() -> list[str]:
    """Every known group key, populated or not."""
    return sorted(_GROUPS)


def groups_of_kind(kind: str) -> list[Group]:
    return [g for g in _GROUPS.values() if g.kind == kind]


def resolve_group(key: str) -> Group | None:
    return _GROUPS.get((key or "").strip().lower())


def _year_of(period: str | None) -> int | None:
    """The 4-digit year at the head of a period label, or None."""
    if not period:
        return None
    head = str(period).strip()[:4]
    return int(head) if head.isdigit() else None


def _active(m: Membership, year: int | None) -> tuple[bool, bool]:
    """``(is_member, is_suspended)`` for one membership as of ``year``."""
    if year is None:
        return (m.left is None, m.suspended_from is not None)
    joined = _year_of(m.joined)
    left = _year_of(m.left)
    suspended = _year_of(m.suspended_from)
    if joined is not None and year < joined:
        return (False, False)
    if left is not None and year >= left:
        return (False, False)
    return (True, suspended is not None and year >= suspended)


def members_as_of(key: str, period: str | None = None) -> dict:
    """Who was in this group in ``period`` — with the registry vintage attached.

    ``period`` is the figure's own period label (``"2019"``, ``"2019-Q3"``); ``None``
    means "as the registry currently stands", which is the right answer for a question
    with no year in it and the WRONG one for a historical series — so the resolved year
    is echoed back and callers state it.

    Suspended members come back in their own list rather than being silently kept or
    dropped, because "who is in this bloc" and "whose statistics it covers" are different
    questions and this module does not get to choose between them.
    """
    group = resolve_group(key)
    if group is None:
        return {
            "group": key,
            "known": False,
            "members": [],
            "as_of": BLOC_REGISTRY_AS_OF,
            "reason": f"No group named {key!r} is registered.",
        }

    if group.unpopulated_reason:
        return {
            "group": group.key,
            "label": group.label,
            "kind": group.kind,
            "known": True,
            "populated": False,
            "members": [],
            "suspended": [],
            "as_of": BLOC_REGISTRY_AS_OF,
            "dates_apply": group.dates_apply,
            "reason": group.unpopulated_reason,
        }

    year = _year_of(period)
    members: list[str] = []
    suspended: list[str] = []
    undated: list[str] = []
    for m in group.members:
        is_member, is_suspended = _active(m, year)
        if not is_member:
            continue
        members.append(m.area)
        if is_suspended:
            suspended.append(m.area)
        if group.dates_apply and m.joined is None:
            undated.append(m.area)

    return {
        "group": group.key,
        "label": group.label,
        "kind": group.kind,
        "known": True,
        "populated": True,
        "members": sorted(members),
        "suspended": sorted(suspended),
        # Members carried WITHOUT a sourced accession date, so their presence in a
        # historical year is asserted by the registry rather than evidenced. Empty for a
        # continent, where no accession exists to date.
        "undated_members": sorted(undated),
        "period": period,
        "resolved_year": year,
        "dates_apply": group.dates_apply,
        "as_of": BLOC_REGISTRY_AS_OF,
        "notes": group.notes,
        "caveat": (
            (
                f"Membership resolved as of {year}. "
                if year is not None
                else "No period was given, so membership is as the registry currently "
                "stands — which is the wrong roster for a historical series. "
            )
            + f"Registry curated {BLOC_REGISTRY_AS_OF}."
        ),
    }
