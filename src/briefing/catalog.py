"""
The card catalog: what every Lead producer IS, and what an operator may tune.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Settings restructure PR-7 (maintainer rulings 1/2/3/17, 2026-07-31). Producers
were previously reachable only as ``(name, callable)`` pairs in a registry, with
their family known solely at card-construction time and their thresholds buried
as module constants. That is enough to RUN them and not nearly enough to let
someone see or adjust them, so this module adds the missing declarative layer:
every producer's family, a plain label, one line on what it looks for, and --
where it has been wired -- its tunables.

THREE RULES THIS FILE EXISTS TO ENFORCE
---------------------------------------
1. **A safe range is stated, never silently applied** (ruling 3). Every tunable
   carries ``lo``/``hi`` and, where the bound is load-bearing rather than merely
   sensible, a ``floor_reason`` saying WHY. :func:`clamp_settings` returns the
   adjustments it made so the caller can show them; nothing here quietly
   rewrites a number behind the operator's back.

2. **A floor that prevents an underpowered claim may not be tuned away.** Some
   of these bounds are not taste. ``flooded_topic``'s ``z_min`` floor is 1.96 --
   the two-tailed p<0.05 critical value -- because below it the test stops
   distinguishing a real surge from ordinary variance, and a card built on that
   would be a fabricated signal wearing a statistic's clothes. Likewise every
   "distinct sources" floor is >= 2: at 1 a single chatty source corroborates
   itself, which is precisely the shape these producers exist to expose. The
   operator can make a producer STRICTER without limit; they cannot make it
   claim more than the evidence supports.

3. **Tuning is not scoring.** Nothing here weights, ranks or blends producers.
   These are the thresholds each producer already applied; the change is that
   they are now visible and adjustable, so ``assert_no_score_fields`` and the
   no-composite-score rule are untouched by construction.

The ``overtold`` family is wired end to end as the reference pattern (ruling 2);
the other seven are catalogued and can be switched off per producer, and gain
their own tunables by adding ``tunables=`` here and reading
:func:`settings_for` in the producer -- no new machinery per family.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tunable:
    """One adjustable threshold of one producer.

    ``lo``/``hi`` are the SAFE RANGE, shown to the operator rather than enforced
    in silence. ``impact`` is the one-line plain-language consequence of moving
    it -- the thing that makes a number meaningful to someone who did not write
    the producer. ``floor_reason``, when set, says why the low bound is where it
    is; it is displayed beside the control, because a limit whose reason is
    hidden reads as an arbitrary restriction.
    """

    key: str
    label: str
    default: float
    lo: float
    hi: float
    impact: str
    kind: str = "int"  # "int" | "float"
    unit: str = ""
    floor_reason: str = ""

    def coerce(self, value: object) -> float | int | None:
        """``value`` as this tunable's type, or None when it is not a number."""
        try:
            num = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if num != num or num in (float("inf"), float("-inf")):  # NaN / inf
            return None
        return int(round(num)) if self.kind == "int" else num


@dataclass(frozen=True)
class ProducerSpec:
    """A producer as the operator sees it: family, name, what it looks for."""

    name: str
    family: str
    label: str
    description: str
    tunables: tuple[Tunable, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------- #
#  The overtold family, wired end to end (ruling 2's reference pattern)
#
#  These four all answer the same question -- "are these voices as independent
#  as they look?" -- so they share a vocabulary: a DISTINCT-SOURCES floor (never
#  below 2), a window, and a cap on how many cards one producer may contribute.
# --------------------------------------------------------------------------- #
_SOURCES_FLOOR_REASON = (
    "At least 2: with 1, a single talkative source would corroborate itself — "
    "the very illusion these Leads exist to expose."
)
_MORE_SOURCES_IMPACT = (
    "Higher = fewer, stronger Leads: more independent voices must agree before "
    "one appears."
)
_WINDOW_IMPACT = (
    "How far back to look. Wider catches slower coordination; narrower keeps "
    "the Lead about right now."
)
_CAP_IMPACT = "How many of these Leads may reach Home at once."


def _cap(default: int) -> Tunable:
    return Tunable(
        key="max_cards",
        label="Most Leads at once",
        default=default,
        lo=1,
        hi=10,
        impact=_CAP_IMPACT,
    )


_OVERTOLD: tuple[ProducerSpec, ...] = (
    ProducerSpec(
        name="echo_chamber",
        family="overtold",
        label="Sources moving in lockstep",
        description=(
            "Several sources published near-identical text on the same story — a "
            "shared newswire, or coordination. Either way they may count as one voice."
        ),
        tunables=(
            Tunable(
                key="min_sources",
                label="Minimum sources in lockstep",
                default=3,
                lo=2,
                hi=20,
                impact=_MORE_SOURCES_IMPACT,
                floor_reason=_SOURCES_FLOOR_REASON,
            ),
            Tunable(
                key="days",
                label="Look back",
                default=14,
                lo=1,
                hi=90,
                unit="days",
                impact=_WINDOW_IMPACT,
            ),
            _cap(3),
        ),
    ),
    ProducerSpec(
        name="source_laundering",
        family="overtold",
        label="Many sources, one origin",
        description=(
            "Several distinct sources all cite the same external origin — apparent "
            "corroboration that traces back to a single voice."
        ),
        tunables=(
            Tunable(
                key="min_sources",
                label="Minimum distinct citing sources",
                default=3,
                lo=2,
                hi=20,
                impact=_MORE_SOURCES_IMPACT,
                floor_reason=_SOURCES_FLOOR_REASON,
            ),
            Tunable(
                key="min_articles",
                label="Minimum citing articles",
                default=3,
                lo=2,
                hi=50,
                impact=(
                    "Higher = only origins cited repeatedly qualify, not a one-off "
                    "pair of mentions."
                ),
            ),
            _cap(4),
        ),
    ),
    ProducerSpec(
        name="flooded_topic",
        family="overtold",
        label="A source flooding one topic",
        description=(
            "A source gave far more of its recent coverage to one topic than its own "
            "history would predict — compared against itself, never against others."
        ),
        tunables=(
            Tunable(
                key="recent_days",
                label="Recent window",
                default=7,
                lo=1,
                hi=60,
                unit="days",
                impact="What counts as “recently” for the surge being measured.",
            ),
            Tunable(
                key="baseline_days",
                label="History to compare against",
                default=84,
                lo=14,
                hi=365,
                unit="days",
                impact=(
                    "The source's own past, used as the yardstick. Longer is steadier "
                    "but slower to notice a genuine change of beat."
                ),
                floor_reason=(
                    "At least 14 days: a shorter history is too thin to say what is "
                    "normal for this source."
                ),
            ),
            Tunable(
                key="min_recent_articles",
                label="Minimum recent articles",
                default=8,
                lo=3,
                hi=100,
                impact=(
                    "Higher = the surge must be built on more articles before it is "
                    "reported."
                ),
                floor_reason=(
                    "At least 3: below that there is not enough to compare, and the "
                    "test would be reporting noise."
                ),
            ),
            Tunable(
                key="min_share",
                label="Minimum share of coverage",
                default=0.25,
                lo=0.05,
                hi=0.95,
                kind="float",
                impact=(
                    "How much of the source's recent output the topic must occupy. "
                    "Higher = only pronounced floods."
                ),
            ),
            Tunable(
                key="z_min",
                label="Statistical strength (z)",
                default=2.5,
                lo=1.96,
                hi=6.0,
                kind="float",
                impact=(
                    "How far above its own baseline the surge must sit. Higher = "
                    "fewer, more certain Leads."
                ),
                floor_reason=(
                    "Never below 1.96 — the p<0.05 threshold. Under it the test can no "
                    "longer tell a real surge from ordinary variation, so a Lead would "
                    "be asserting more than the evidence supports."
                ),
            ),
            _cap(4),
        ),
    ),
    ProducerSpec(
        name="copypasta",
        family="overtold",
        label="The same phrasing, many sources",
        description=(
            "A verbatim phrase appears across many distinct sources in articles that "
            "are NOT whole duplicates — the shape a talking point makes."
        ),
        tunables=(
            Tunable(
                key="min_sources",
                label="Minimum distinct sources",
                default=3,
                lo=2,
                hi=20,
                impact=_MORE_SOURCES_IMPACT,
                floor_reason=_SOURCES_FLOOR_REASON,
            ),
            Tunable(
                key="recent_days",
                label="Look back",
                default=14,
                lo=1,
                hi=90,
                unit="days",
                impact=_WINDOW_IMPACT,
            ),
            Tunable(
                key="k",
                label="Minimum phrase length",
                default=8,
                lo=5,
                hi=30,
                unit="words",
                impact=(
                    "How long a shared phrase must be. Longer = only distinctive "
                    "wording counts."
                ),
                floor_reason=(
                    "At least 5 words: shorter runs recur by chance in ordinary "
                    "prose, so they would flag coincidence as coordination."
                ),
            ),
            _cap(4),
        ),
    ),
)


# --------------------------------------------------------------------------- #
#  The other seven families: catalogued and switchable now, tunable next.
#  Adding tunables here + reading settings_for() in the producer is the whole
#  change -- there is no per-family machinery to build.
# --------------------------------------------------------------------------- #
def _p(name: str, family: str, label: str, description: str) -> ProducerSpec:
    return ProducerSpec(name=name, family=family, label=label, description=description)


_OTHERS: tuple[ProducerSpec, ...] = (
    # rising
    _p("rising_now", "rising", "Rising now",
       "Keywords moving faster in a recent window than in the period before it."),
    _p("manufactured_emergence", "rising", "Emergence with no anchor",
       "A topic appearing suddenly across sources with no datable primary event behind it."),
    # undertold
    _p("lonely_signal", "undertold", "A lonely signal",
       "Something your corpus recorded that almost no other source picked up."),
    _p("region_gone_quiet", "undertold", "A region gone quiet",
       "A country you usually receive coverage from has stopped arriving."),
    # investigate
    _p("capacity_implausible", "investigate", "An implausible capacity",
       "A stated figure sits far outside what comparable figures in your corpus show."),
    _p("ownership_change", "investigate", "An ownership change",
       "Reporting that a source or company changed hands — worth knowing who owns the voice."),
    _p("model_legislation", "investigate", "Model legislation",
       "Near-identical legal text appearing across jurisdictions."),
    _p("weather_corroboration", "investigate", "Weather worth corroborating",
       "A cluster of articles describing a weather event you could check against a record."),
    _p("space_time_convergence", "investigate", "Converging on one place",
       "Independent sources converging on the same place within a short window."),
    _p("buried_topic", "investigate", "A buried topic",
       "A topic covered far less by one source than the rest of your corpus."),
    _p("edit_war_burst", "investigate", "An edit war",
       "A tracked Wikipedia page is churning far above its usual rate."),
    # debunk
    _p("framing_split", "debunk", "The same event, opposite framing",
       "Sources describing one event in measurably different terms."),
    _p("headline_body_mismatch", "debunk", "Headline against body",
       "A headline that its own article does not support."),
    _p("disputed_chronology", "debunk", "A disputed chronology",
       "Sources placing the same event at different times."),
    # watch
    _p("record_reshaped", "watch", "A record was reshaped",
       "A figure you already stored has changed in a later version."),
    _p("law_change", "watch", "A tracked law changed",
       "One of the legal documents you track has a new revision."),
    _p("watch_matches", "watch", "A watch matched",
       "A condition you saved has been met by newly collected articles."),
    _p("recycled_claim", "watch", "A recycled claim",
       "A claim resurfacing after a long dormancy."),
    ProducerSpec(
        name="severity_alerts",
        family="watch",
        label="A provider-declared hazard",
        description=(
            "A hazard a provider itself declared severe — never our own judgement. "
            "The same two settings also decide which hazards the Home alert strip "
            "shows first; nothing is ever removed from the World map or the corpus."
        ),
        tunables=(
            Tunable(
                key="min_magnitude",
                label="Show first at magnitude",
                default=6.0,
                lo=4.5,
                hi=8.0,
                kind="float",
                unit="M",
                impact=(
                    "Which earthquakes reach the compact strip first. Lower = a longer "
                    "list; higher = only the largest. Every event stays on the World map "
                    "and in your corpus either way."
                ),
                floor_reason=(
                    "6.0 is the lower bound of the USGS 'strong' band, so the number and "
                    "the band label agree. A provider ORANGE or RED alert always clears "
                    "the floor whatever its magnitude — and a magnitude never becomes an "
                    "urgency tier the provider did not declare."
                ),
            ),
            Tunable(
                key="strip_cap",
                label="Most hazards in the strip",
                default=5,
                lo=1,
                hi=20,
                impact=(
                    "How many hazards the Home strip lists before collapsing the rest "
                    "into one 'N more on the map' line."
                ),
            ),
        ),
    ),
    _p("on_the_horizon", "watch", "On the horizon",
       "An upcoming agenda date whose subject is trending in your corpus right now."),
    _p("supergroup_rising", "watch", "A theme rising",
       "A whole super-group rising against its own baseline, not just one keyword."),
    _p("promises_due", "watch", "A promise came due",
       "A future date an article mentioned has now arrived."),
    # context
    _p("price_narrative", "context", "Price against coverage",
       "A commodity's price beside how your corpus wrote about it — co-occurrence, never cause."),
    _p("diet_self_audit", "context", "Your reading diet",
       "How concentrated your corpus is across sources — a mirror, not a verdict."),
    _p("emotion_profile", "context", "An emotional profile",
       "How loaded the language around a topic is, measured by lexicon."),
    _p("ip_litigation_pulse", "context", "Litigation pulse",
       "The rate of intellectual-property disputes appearing in your corpus."),
    _p("story_lineage", "context", "A story's lineage",
       "How a story travelled between sources over time."),
    _p("coverage_advisor", "context", "A coverage gap",
       "Where your corpus is thin, so you can decide whether to widen it."),
    _p("story_propagation", "context", "How a story spread",
       "The path and pace of a story moving across your sources."),
    _p("supply_chain_ripple", "context", "A supply-chain ripple",
       "A commodity moving alongside coverage of something that depends on it."),
    _p("through_time", "context", "Through time",
       "What your corpus holds from this same date in earlier years."),
    _p("source_candidates_waiting", "context", "Sources awaiting review",
       "Discovered sources sitting in the queue for your decision."),
    # trust
    _p("stale_data", "trust", "Stale data",
       "Part of your corpus has not refreshed when it should have."),
)


CARD_CATALOG: tuple[ProducerSpec, ...] = _OVERTOLD + _OTHERS

# Display order of the families on Home and in Settings (mirrors card.BUCKETS).
FAMILY_ORDER: tuple[str, ...] = (
    "rising", "overtold", "undertold", "investigate", "debunk", "watch", "context", "trust",
)

_BY_NAME: dict[str, ProducerSpec] = {s.name: s for s in CARD_CATALOG}


def spec_for(name: str) -> ProducerSpec | None:
    return _BY_NAME.get(name)


def by_family() -> list[tuple[str, list[ProducerSpec]]]:
    """The catalog grouped for display, families in :data:`FAMILY_ORDER`."""
    groups: dict[str, list[ProducerSpec]] = {f: [] for f in FAMILY_ORDER}
    for spec in CARD_CATALOG:
        groups.setdefault(spec.family, []).append(spec)
    ordered = [(f, groups.get(f, [])) for f in FAMILY_ORDER]
    # A family that somehow escaped FAMILY_ORDER is still shown, never dropped.
    extra = [(f, v) for f, v in groups.items() if f not in FAMILY_ORDER and v]
    return ordered + sorted(extra)


# --------------------------------------------------------------------------- #
#  Reading an operator's settings back out, safely
# --------------------------------------------------------------------------- #
def clamp_settings(name: str, values: dict) -> tuple[dict, list[dict]]:
    """Clamp ``values`` to ``name``'s safe ranges. Returns (clamped, notes).

    NOTES ARE THE POINT (ruling 3): a value outside its range is corrected AND
    reported, so the caller can tell the operator what happened. Silently
    rewriting a number the operator typed is exactly the behaviour the ruling
    forbids -- they would go on believing the producer runs at a setting it
    does not have.

    An unknown key, or one whose value is not a number, is DROPPED with a note
    rather than guessed at.
    """
    spec = _BY_NAME.get(name)
    if spec is None or not isinstance(values, dict):
        return {}, ([{"key": "*", "reason": "unknown producer", "producer": name}] if values else [])
    known = {t.key: t for t in spec.tunables}
    out: dict = {}
    notes: list[dict] = []
    for key, raw in values.items():
        tunable = known.get(key)
        if tunable is None:
            notes.append({"producer": name, "key": key, "reason": "not a setting of this Lead"})
            continue
        num = tunable.coerce(raw)
        if num is None:
            notes.append({"producer": name, "key": key, "reason": "not a number"})
            continue
        if num < tunable.lo:
            notes.append({
                "producer": name, "key": key, "given": raw, "used": tunable.lo,
                "reason": tunable.floor_reason or f"below the safe minimum of {tunable.lo}",
            })
            num = tunable.lo
        elif num > tunable.hi:
            notes.append({
                "producer": name, "key": key, "given": raw, "used": tunable.hi,
                "reason": f"above the safe maximum of {tunable.hi}",
            })
            num = tunable.hi
        out[key] = int(num) if tunable.kind == "int" else float(num)
    return out, notes


def defaults_for(name: str) -> dict:
    spec = _BY_NAME.get(name)
    if spec is None:
        return {}
    return {t.key: (int(t.default) if t.kind == "int" else float(t.default)) for t in spec.tunables}


def settings_for(name: str) -> dict:
    """A producer's effective tunables: defaults, overlaid with the operator's
    persisted values, clamped to the safe range.

    Never raises: a settings problem must not blank a Lead (the fail-safe rule),
    so any failure falls back to the shipped defaults.
    """
    values = defaults_for(name)
    try:
        from src.config.app_settings import load_settings

        stored = (load_settings().card_settings or {}).get(name)
    except Exception:  # noqa: BLE001 - settings must never take down the briefing
        _LOG.debug("card settings unavailable for %r; using defaults", name, exc_info=True)
        return values
    if isinstance(stored, dict):
        clamped, _notes = clamp_settings(name, stored)
        values.update(clamped)
    return values


def is_disabled(name: str) -> bool:
    """Whether the operator has switched this producer off.

    Reads the unified ``cards_disabled`` list, which the settings loader seeds
    from the legacy ``recipes_disabled`` key so an existing settings file keeps
    working -- extending that mechanism rather than running a second one beside
    it (the brief's instruction).
    """
    try:
        from src.config.app_settings import load_settings

        s = load_settings()
        return name in set(s.cards_disabled or []) | set(s.recipes_disabled or [])
    except Exception:  # noqa: BLE001 - settings must never take down the briefing
        return False
