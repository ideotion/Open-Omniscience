"""
Persisted, GUI-editable scheduler configuration.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Same small-JSON-file pattern as custody/app settings. ``autostart`` records
whether the scheduler should begin running on app launch; the live running state
is separate (the operator can start/stop without changing the preference).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

_LOG = logging.getLogger(__name__)

SETTINGS_VERSION = "oo-scheduler-settings-1"
# `VALID_MODES` and the `mode` field are RETIRED (Q1020 = a, Q716 = a; brief S04-08 S3).
# The scheduler no longer picks ONE of press / crawl / markets / wiki / law per pass: press
# collection is the pass itself, and every other kind runs BESIDE it as a lane (the
# housekeeping lane in ``runner.py`` for markets, law, hazards, discovery and the crawl
# supplement; the Wikipedia stream on the online seam). A stored ``mode`` is migrated once
# by ``_migrate_retired_mode`` below and disclosed; see ``_RETIRED_MODE_SENTENCES``.
VALID_RATE_MODES = ("target", "maximum")
# Bounds for the download-rate target (KiB/s): a generous, honest range.
_MIN_TARGET_KBPS, _MAX_TARGET_KBPS = 50, 50_000
# Hard ceiling on concurrent fetches (the governor's upper bound).
_MAX_PARALLELISM = 50
_MIN_INTERVAL, _MAX_INTERVAL = 1, 7 * 24 * 60  # minutes: 1 min .. 1 week

#: The twelve editions the Wikipedia lane follows by default (Q725 = a's "default:
#: all twelve"), in the app's own locale order.
#:
#: SPELLED OUT HERE rather than imported, because this module deliberately has no
#: ``src.`` imports -- it is read on the boot path and a settings file that could not
#: be loaded without pulling in the wiki package would be a boot dependency nobody
#: chose. The duplication is PINNED instead of trusted:
#: ``tests/test_wiki_tiers.py`` asserts this tuple equals
#: ``src.wiki.languages.UI_LOCALE_CODES``, so the two cannot drift apart silently.
WIKI_LANE_DEFAULT_EDITIONS: tuple = (
    "en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id",
)

#: Q707's published default budget, in whole GB, TOTAL for the lane. Duplicated from
#: ``src.wiki.tiers.DEFAULT_TOTAL_BUDGET_GB`` for the same no-imports reason, and
#: pinned to it by the same test.
WIKI_LANE_DEFAULT_BUDGET_GB: int = 20

#: What the wizard will accept. Mirrors ``src.wiki.tiers.BUDGET_GB_MIN/MAX``, pinned.
WIKI_LANE_BUDGET_GB_MIN, WIKI_LANE_BUDGET_GB_MAX = 1, 2000


class SchedulerSettingsError(ValueError):
    """Raised when a scheduler settings update carries an invalid value."""


@dataclass
class SchedulerSettings:
    """Operator-controlled scheduling preferences."""

    autostart: bool = False
    interval_minutes: int = 60
    # Continuous collection (maintainer 2026-06-13: "scraping should never
    # stop"). When True (the default), the scheduler runs passes back-to-back
    # with only a short inter-pass gap instead of idling ``interval_minutes``
    # between them — so when the operator is online, collection is permanent.
    # Set False to restore the old run-once-then-wait-``interval_minutes`` cadence.
    continuous: bool = True
    # Collection speed is expressed as a DOWNLOAD-RATE target, not a raw worker
    # count (maintainer ruling 2026-06-16). The bandwidth governor varies how many
    # sources are fetched at once to APPROACH the target — always across DIFFERENT
    # hosts, each on its own Tor circuit, while the single SQLite writer keeps
    # writes serialised. Per-host politeness is never traded for speed: one host is
    # fetched by at most one worker at a time.
    #   collect_rate_mode  : "target" (track collect_target_kbps) | "maximum"
    #   collect_target_kbps: best-effort download-rate goal in KiB/s (target mode)
    #   collect_parallelism: the hard CEILING on concurrent fetches (the governor's
    #                        upper bound). 1 = the sequential loop (governor off).
    # The default is "maximum" (maintainer ruling 2026-07-23: the old 500 KiB/s
    # target deliberately parked workers and left real connections under-used —
    # field-observed as "a few kB/s average"); the governor still backs off
    # automatically under CPU/memory/writer contention (logged in
    # src/monitoring/collect_perf.py) and per-host politeness is untouched, so
    # "maximum" ramps to the ceiling only where the machine and the hosts allow.
    # "target" mode + collect_target_kbps stay available for constrained lines.
    collect_rate_mode: str = "maximum"
    collect_target_kbps: int = 500
    collect_parallelism: int = 50
    # 0 = UNBOUNDED (cover every source / watched item) -- the default. Any cap
    # silently SELECTS which sources to skip, which cannot be justified
    # (maintainer 2026-06-13). A positive value is honoured as a soft cap.
    max_sources_per_run: int = 0
    # The operator's caps on the CRAWL SUPPLEMENT (see ``crawl_supplement`` below). Before
    # Q1020 these bounded the whole-source ``mode="crawl"``; that mode is retired, and the
    # supplement already read them through ``min(..., its own ceiling)``, so they keep a
    # meaning rather than becoming dead fields an operator can still edit.
    crawl_max_depth: int = 2
    crawl_max_pages: int = 50

    # THE MARKETS LANE'S TWO OPT-INS (Q1020 = a). Before the ruling, the operator's own
    # price-extraction rules and the refresh of the statistics figures they SUBSCRIBED to
    # ran only when the scheduler's ``mode`` was "markets" -- a mode that also stopped
    # press collection. The markets lane now runs beside press on every online pass, so
    # both become per-lane switches. They default OFF because that is what every install
    # outside the retired markets mode was doing; an install that WAS in markets mode is
    # migrated to ON for both (``_migrate_retired_mode``), so nobody's collection narrows.
    # The bundled commodity and index feeds are not behind either switch: they have ridden
    # the lane on every pass since 2026-07-24 and still do.
    auto_run_market_rules: bool = False
    auto_refresh_stat_subscriptions: bool = False

    # Which retired ``mode`` this install was migrated FROM ("" = none, or dismissed).
    # Kept so the disclosure survives the first save -- the migration drops ``mode`` from
    # the stored blob on that save, and a disclosure that vanished before the operator
    # opened the panel would be the silent change it exists to prevent. Not settable to
    # anything but "" (the Dismiss button); see ``save_settings``.
    retired_mode: str = ""

    # Source selection for rss/crawl runs (empty list = no filter on that facet).
    # Sources are always also filtered to enabled=True. Tags match ANY (substring).
    select_languages: list[str] = field(default_factory=list)
    select_tags: list[str] = field(default_factory=list)
    select_source_types: list[str] = field(default_factory=list)

    # Opt-in drop-folder export (WP3/RM-06): after each run, the new-articles
    # delta is written into this LOCAL folder (envelope JSON). Empty = off
    # (the default) -- no file is ever written unless the operator sets it.
    export_dir: str = ""

    # Offline source-discovery budget per run (WP5/RM-19): how many candidates
    # the citation/catalog channels may stage per scheduler run. 0 disables
    # discovery entirely. Network channels do not exist here by design.
    discovery_per_run: int = 10

    # WORLD source-discovery ride-along (maintainer ruled 2026-07-15: source
    # discovery should be "background and automated"): how many COUNTRIES the
    # persisted world-discovery cursor advances per online collection pass,
    # through the same guarded transport as the pass itself. Every find stays a
    # DISABLED source for review (automation covers discovery, never enabling).
    # 0 disables the ride-along; the manual Diagnostics job remains either way.
    world_discovery_per_pass: int = 2

    # QUALIFICATION ride-along (0.3 CLOSE GATE ruling: "qualification runs as a
    # background job... like the world-discovery ride-along"): how many candidate
    # sources (never-yet-qualified, then due re-qualifications) the admission gate
    # trial-fetches + judges per online collection pass. 0 disables the ride-along
    # (candidates then simply stay unqualified/disqualified -- never auto-admitted).
    qualification_per_pass: int = 5

    # RE-VERIFICATION budget, DELIBERATELY SEPARATE from `qualification_per_pass`
    # (maintainer ruling 2026-09-04). The two must never share one budget: candidates are
    # selected never-judged-first, and with a backlog of tens of thousands of unqualified
    # sources (42.6k-66.7k measured in the field) a shared budget is always exhausted
    # before a single re-check is reached -- which is exactly why the re-qualification
    # ladder, shipped correct in 2026-07, had never actually run on a field instance.
    # A separate budget makes starvation impossible in BOTH directions by construction,
    # with no ratio to tune and no cross-pass state to keep.
    #
    # The marginal cost is small: re-checks ride the SAME pass, so they reuse its one
    # frozen cohort and its one scoped-metrics query -- what a re-check adds is a few
    # source ids and (for a source with a feed) a mostly-304 conditional GET.
    # Sized from the work: ~3,600 catalog sources on a ~6-month clock is ~20 re-checks a
    # day, and ~4 passes an hour is ~96 passes a day, so 2 per pass carries a corpus an
    # order of magnitude larger than today's. 0 disables re-verification entirely.
    qualification_recheck_per_pass: int = 2

    # SCRAPING SCOPE. `scrape_app_provided_only` narrows collection to the sources that
    # SHIPPED with the app, by their seed-time provenance tag. See
    # catalog.provenance_scope.is_app_provided for why this is an exact-set match and not
    # a prefix one.
    scrape_app_provided_only: bool = False
    #
    # `scrape_unqualified` IS RETIRED (Q1101 = a, 2026-09-15; brief S04-12 S1). It was a
    # 2026-08-03 amendment relaxing the close-gate ruling so collection could reach
    # sources the engine had not judged. Q1101 settles the same question the other way and
    # settles it at the source: a `qualified` verdict now flips `enabled=True`, so
    # qualification IS the admission gate and there is nothing left for a hatch to relax.
    # The field is GONE rather than defaulted-off, because a dormant relaxation of a
    # ruling is a relaxation somebody eventually turns on.
    #
    # A persisted `true` is dropped by `load_settings` and DISCLOSED ONCE (see
    # `_RETIRED_KEYS`): an operator who had opted in is told their setting no longer
    # exists and why, rather than finding collection quietly narrower.

    # Optional per-language cadence lever (default OFF). ``language_equilibrium``
    # is a {lang: weight} TARGET the operator opts into; when set, over-
    # represented languages are re-checked LESS often (never excluded — a hard
    # freshness floor guarantees re-check). Empty {} = OFF = the pure random
    # per-tag rotation, byte-identical. ``equilibrium_floor`` is the minimum pace
    # multiplier (never fully stop a language).
    language_equilibrium: dict = field(default_factory=dict)
    equilibrium_floor: float = 0.2
    # Opt-in per-country PRIORITY LADDER (default OFF): a {iso2: weight>0} map the operator
    # sets so chosen countries scrape FIRST under constrained bandwidth. It only ORDERS,
    # never excludes (ordering != exclusion — the continuous round-robin still covers every
    # source). Empty {} = OFF = the pure stratified order, byte-identical.
    country_priority: dict = field(default_factory=dict)

    # Opt-out for the background hazard-snapshot + weather-signal refresh pass (Wave 4 J).
    # When True (default) each collect pass keeps the local hazard snapshot (the severity
    # alert tier's data) fresh via the consented USGS/GDACS fetch AND re-derives the weather
    # SIGNAL keywords from the corpus (network-free) — both freshness-gated so they are
    # usually no-ops. Set False to leave those stores to the explicit manual endpoints only.
    auto_track_signals: bool = True

    # THE WIKIPEDIA LANE'S RUN STATE (Q702's NOTE, ruled 2026-09-15). The label of
    # Q702's answer said "default off"; the note that follows it says "make it
    # default on, and add a toggle on the taskbar ... to allow users to stop / start
    # / halt / resume wikipedia streaming". The working mode's rule for this pair is
    # explicit -- "the label is context; the note is the ruling" -- so the default
    # here is ON, and the field is a STATE rather than a boolean because the note
    # names four verbs, not two.
    #
    #   "running" : the stream is connected (or reconnecting). START and RESUME both
    #               land here; what differs is what the lane PROMISES about the gap.
    #   "halted"  : deliberately paused. The connection is closed and the cursor is
    #               kept, so RESUME continues from the stored Last-Event-ID and the
    #               lane can say honestly whether anything was missed.
    #   "stopped" : off. The connection is closed and nothing reconnects.
    #
    # THE CURSOR SURVIVES BOTH, and that is deliberate: discarding a resume point
    # because an operator pressed stop would turn a reversible choice into data loss.
    # What "stopped" gives up is the PROMISE -- a start after a long stop may find its
    # cursor outside EventStreams' retention, and the lane then records a gap saying
    # so (Q727) rather than resuming as though nothing had happened.
    wiki_lane_state: str = "running"

    # THE FIRST-RUN WIZARD'S TWO ANSWERS (Q725 = a: "Edition choice (default: all
    # twelve) + the storage budget (Q707) + the plain statement of what the lane
    # contacts"). Stored beside the run state because they are the same operator's
    # same decision about the same lane, and a second settings file for two fields
    # is a second thing to keep in step.
    #
    # ``wiki_lane_editions`` is a TUPLE, not a set: the order is the order the wizard
    # showed and the hover lists, and a set would re-order it differently on every
    # process. Empty is REFUSED on the way in (a lane with no editions is a lane that
    # is off, and the toggle already says that honestly).
    wiki_lane_editions: tuple = WIKI_LANE_DEFAULT_EDITIONS
    # Whole GB, TOTAL for the lane. Q707's published default. See
    # ``src/wiki/tiers.py`` for the arithmetic and for why this is a STORAGE cap and
    # never a second rate authority beside the collection-speed governor (Q1012).
    wiki_lane_budget_gb: int = WIKI_LANE_DEFAULT_BUDGET_GB
    # Whether the operator has been THROUGH the wizard, which is a different fact
    # from whether the values differ from the defaults. An operator who read the
    # three disclosures and pressed "Use the defaults" has consented; one who never
    # saw the screen has not, and the two would be indistinguishable if this were
    # inferred from the values.
    wiki_lane_wizard_done: bool = False

    # COUNTRY-DATA ride-along (2026-07-24 field-feedback Session A §2, ruled: Governments-
    # tab figures should load automatically, not only via the manual "Load standard
    # country data" button): how many curated World-Bank indicators the scheduler
    # bootstraps per online pass (never-yet-fetched ones only — ongoing refresh of an
    # already-loaded indicator is the SEPARATE, already-wired stats.subscriptions.
    # refresh_due). 0 disables the ride-along (the manual button remains either way).
    country_data_per_pass: int = 2

    # §8 CRAWL-BY-DEFAULT (maintainer-ruled 2026-07-24, PR766 throughput brief C3): a
    # HYBRID BUDGETED RUNG, never a mode flip. (The whole-source ``mode="crawl"`` it once
    # sat beside is retired, Q1020 = a; its caps now bound this rung.) When True (the ruled
    # default), a bounded crawl sub-pass runs over ``crawl_per_pass`` qualified sources
    # per online collection pass (least-recently-crawled + feedless-first rotation, the
    # lane's LOWEST bandwidth-ladder rung), reusing crawl_source through the ONE
    # EthicalFetcher -- no new fetch path, same politeness/robots. ``crawl_per_pass=0``
    # disables the supplement entirely (never a selection of which sources to crawl --
    # the rotation covers every qualified source over time, ordering never exclusion).
    crawl_supplement: bool = True
    crawl_per_pass: int = 3

    # ARCHIVE BACKFILL ride-along (2026-07-24 throughput brief, C15/S-E slice 2): how
    # many sitemap-enumerated URLs the persisted backfill cursor advances per online
    # collection pass. Auto-enqueued (bounded ~100-500 pages) when a source QUALIFIES
    # (src.catalog.qualification); a source's FULL history needs an explicit,
    # separate per-source action -- never enqueued by this ride-along. Runs on the
    # ladder's LOWEST rung (below "crawl") so live collection is never starved.
    # 0 disables the ride-along (queued sources simply wait; nothing is lost).
    archive_backfill_per_pass: int = 5

    def to_dict(self) -> dict:
        return asdict(self)


# The ``app_state`` kv key this preference blob lives under (DB-reliability D1).
_KV_KEY = "settings.scheduler"


def _settings_path():
    from src.paths import data_dir

    return data_dir() / "scheduler_settings.json"


def _use_kv() -> bool:
    """Use the encrypted ``app_state`` store at the DEFAULT location; honour a redirected
    ``_settings_path`` (test isolation) as JSON instead. See app_settings._use_kv."""
    from src.paths import data_dir

    return _settings_path() == data_dir() / "scheduler_settings.json"


def _read_json_file() -> dict | None:
    path = _settings_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 - a bad file must not break startup
        _LOG.warning("scheduler_settings.json unreadable; using defaults", exc_info=True)
        return None


def _read_raw() -> dict | None:
    """Scheduler prefs source of truth: the encrypted ``app_state`` row (D1), falling
    back to (and one-time migrating) the legacy ``scheduler_settings.json`` file."""
    if not _use_kv():
        return _read_json_file()
    from src.config.kv_store import kv_get_json, kv_set_json

    raw = kv_get_json(_KV_KEY)
    if raw is not None:
        return raw
    raw = _read_json_file()
    if raw is None:
        return None
    try:
        kv_set_json(_KV_KEY, raw)
    except Exception:  # noqa: BLE001 - migration is best-effort; retried next load
        _LOG.debug("scheduler_settings migration into app_state deferred", exc_info=True)
    return raw


def _coerce_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def _coerce_int(value, fallback: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return fallback


def _coerce_float(value, fallback: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return fallback


def _coerce_target(value) -> dict:
    """A {lang: weight} language-equilibrium target → cleaned {lang: float>0}.

    Only positive weights on non-empty lowercased language keys survive; anything
    malformed is dropped. An empty result means the lever is OFF.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in value.items():
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        key = str(k).strip().lower()
        if key and w > 0:
            out[key] = w
    return out


def _coerce_list(value) -> list[str]:
    """Normalise a selection facet to a deduped list of lowercase, non-empty tokens."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    out, seen = [], set()
    for item in value:
        token = str(item).strip().lower()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out



#: The Wikipedia lane's three persistent states (Q702's NOTE). A CLOSED vocabulary:
#: the four verbs the note names are TRANSITIONS between these, not states of their
#: own -- "start" and "resume" both arrive at ``running``, and conflating the verb
#: with the state is how a UI comes to show a fourth thing the backend cannot store.
WIKI_LANE_STATES: tuple[str, ...] = ("running", "halted", "stopped")


def _require_wiki_lane_state(value) -> str:
    """Refuse anything outside :data:`WIKI_LANE_STATES`, by name."""
    text = str(value).strip().lower()
    if text not in WIKI_LANE_STATES:
        raise SchedulerSettingsError(
            f"wiki_lane_state must be one of {', '.join(WIKI_LANE_STATES)}, got {value!r}"
        )
    return text


def _coerce_wiki_lane_state(value, default: str) -> str:
    """Read a PERSISTED value, falling back to the default for an unreadable one.

    Distinct from :func:`_require_wiki_lane_state` on purpose. A settings FILE that
    cannot be read must not stop the app booting -- the operator would have no way in
    to fix it -- so a corrupt stored value falls back. An API REQUEST is a live
    instruction from somebody who is watching, and there the refusal is the honest
    answer. The two differ in what a wrong value costs, so they are two functions.
    """
    if value is None:
        return default
    try:
        return _require_wiki_lane_state(value)
    except SchedulerSettingsError:
        _LOG.warning("ignoring an unreadable wiki_lane_state %r; using %r", value, default)
        return default


_EDITION_MAX_LEN = 16


def _require_wiki_lane_editions(value) -> tuple:
    """Refuse anything that is not a non-empty list of edition CODES.

    WHAT THIS CHECKS AND WHAT IT DELIBERATELY DOES NOT. It checks the SHAPE -- a
    non-empty sequence of short lowercase codes, de-duplicated with the operator's
    order kept. It does NOT check that a code names a real Wikipedia edition, because
    that answer lives in ``src.wiki.languages`` and this module has no ``src.``
    imports by design (see :data:`WIKI_LANE_DEFAULT_EDITIONS`). The API layer, which
    already owns ``_validated_wiki``, is where an unknown edition is refused -- said
    out loud so nobody reads this function as the guarantee it is not.
    """
    if isinstance(value, (str, bytes)):
        # A bare string is the classic shape bug here: "en" would iterate into
        # ("e", "n"), two editions that do not exist, and the lane would follow
        # neither. Refused by name rather than iterated.
        raise SchedulerSettingsError(
            "wiki_lane_editions must be a list of edition codes, not a single string"
        )
    try:
        items = list(value)
    except TypeError:
        raise SchedulerSettingsError(
            f"wiki_lane_editions must be a list of edition codes, got {value!r}"
        ) from None
    out: list[str] = []
    for item in items:
        code = str(item).strip().lower()
        if not code or len(code) > _EDITION_MAX_LEN or not code.replace("-", "").isalnum():
            raise SchedulerSettingsError(f"not an edition code: {item!r}")
        if code not in out:
            out.append(code)
    if not out:
        # A lane with no editions follows nothing while reporting itself as running.
        # The toggle already expresses "off" honestly; this would be a second, silent
        # way to say it.
        raise SchedulerSettingsError("wiki_lane_editions must name at least one edition")
    return tuple(out)


def _coerce_wiki_lane_editions(value, default: tuple) -> tuple:
    """Read a PERSISTED value, falling back for an unreadable one. Same reasoning as
    :func:`_coerce_wiki_lane_state`: a settings file must never stop the app booting."""
    if value is None:
        return tuple(default)
    try:
        return _require_wiki_lane_editions(value)
    except SchedulerSettingsError:
        _LOG.warning("ignoring unreadable wiki_lane_editions %r; using %r", value, default)
        return tuple(default)


def _require_wiki_lane_budget_gb(value) -> int:
    """Refuse a budget outside the wizard's bounds, by name rather than clamping.

    A clamp turns a slipped keystroke into a silently tiny lane whose owner finds out
    weeks later; a refusal puts the disagreement on screen while they are looking at
    it. The same function's twin lives in ``src.wiki.tiers.require_budget_gb`` for
    callers that are not settings; the bounds are pinned equal by test.
    """
    try:
        gb = int(value)
    except (TypeError, ValueError):
        raise SchedulerSettingsError(
            f"wiki_lane_budget_gb must be a whole number of GB, got {value!r}"
        ) from None
    if gb < WIKI_LANE_BUDGET_GB_MIN or gb > WIKI_LANE_BUDGET_GB_MAX:
        raise SchedulerSettingsError(
            f"wiki_lane_budget_gb must be between {WIKI_LANE_BUDGET_GB_MIN} and "
            f"{WIKI_LANE_BUDGET_GB_MAX} GB, got {gb}"
        )
    return gb

# Settings that existed once, were REMOVED by a ruling, and may still sit in an
# operator's stored file. Each maps to the sentence an operator gets, ONCE, when their
# stored value is dropped -- because a control that silently stops existing is
# indistinguishable, from the outside, from a control that stopped working.
#
# The disclosure fires only for a value that was actually SET to something other than the
# retired default: an operator who never touched the hatch is told nothing, since nothing
# about their install changed.
_RETIRED_KEYS: dict[str, str] = {
    "scrape_unqualified": (
        "The 'also scrape unqualified sources' setting has been retired (ruling Q1101, "
        "2026-09-15). A source that passes qualification is now enabled for collection "
        "automatically, so there is nothing left for the setting to relax. Every "
        "automatic admission is listed in Settings > Sources > Admission audit, where it "
        "can be undone."
    ),
}
# Process-global, so one boot emits one disclosure per retired key rather than one per
# `load_settings()` call -- and it is per PROCESS rather than persisted, because a
# disclosure an operator may have missed is worth repeating on the next run and a
# persisted "already told them" flag is a second thing to get wrong.
_RETIRED_DISCLOSED: set[str] = set()


def _disclose_retired(raw: dict) -> list[str]:
    """Drop any retired key's stored value and return the disclosures owed for it."""
    owed: list[str] = []
    for key, sentence in _RETIRED_KEYS.items():
        if key not in raw:
            continue
        # A stored falsy value is the retired default: nothing the operator chose is being
        # taken away, so there is nothing to disclose.
        if not raw.get(key):
            continue
        owed.append(sentence)
        if key not in _RETIRED_DISCLOSED:
            _RETIRED_DISCLOSED.add(key)
            _LOG.warning("retired scheduler setting %r dropped: %s", key, sentence)
    return owed


# THE RETIRED ``mode`` (Q1020 = a, Q716 = a). Not an entry in ``_RETIRED_KEYS`` because
# it differs from those in two ways that matter. Its retired default ("rss") is truthy, so
# "any truthy stored value is disclosed" would tell every install on earth that something
# changed when for almost all of them nothing did. And what the operator is owed depends on
# WHICH mode they were in, because each one maps onto a different lane. One sentence per
# value, each saying what now happens instead; a value outside this table (a corrupt blob
# that the old loader was already ignoring) is dropped without a disclosure, since no
# behaviour the operator chose is being taken away.
_MODE_RETIRED_DEFAULT = "rss"
_RETIRED_MODE_SENTENCES: dict[str, str] = {
    "crawl": (
        "The scheduler's 'Recursive crawl' mode has been retired (ruling Q1020, "
        "2026-09-15). Every pass now reads your sources' feeds again, and crawling "
        "continues beside it as the bounded crawl supplement, within the depth and page "
        "caps you had set. The supplement was switched on for you."
    ),
    "markets": (
        "The scheduler's 'Markets' mode has been retired (ruling Q1020, 2026-09-15). "
        "Markets now run as a lane beside feed collection on every pass, so feed "
        "collection has resumed. Your price-extraction rules and your subscribed "
        "statistics keep refreshing: both were switched on for you below."
    ),
    "law": (
        "The scheduler's 'Law' mode has been retired (ruling Q1020, 2026-09-15). Watched "
        "legal documents are now re-checked by the law lane, beside feed collection, "
        "whenever they are due, so feed collection has resumed."
    ),
    "wiki": (
        "The scheduler's 'Wikipedia (watched pages)' mode has been retired (ruling Q716, "
        "2026-09-15). Wikipedia is now a lane beside feed collection: your watched pages "
        "are followed through the live edit stream in the editions the lane follows, "
        "which the Wikipedia button in the top bar starts and stops. Feed collection has "
        "resumed."
    ),
}


def _migrate_retired_mode(raw: dict, settings: SchedulerSettings) -> None:
    """Map a stored retired ``mode`` onto the lanes, IN PLACE, and record where it came from.

    The mapping is the brief's design note (S04-08 section 6): every lane the old mode
    implied is ON, and press is ON, because Q716 says "beside" -- the four non-default modes
    each STOPPED feed collection, and that is the one behaviour no lane keeps.

    Idempotent and one-time by construction rather than by a flag: it acts only while the
    stored blob still carries ``mode``, and ``save_settings`` writes ``to_dict()``, which no
    longer has the key -- so the first save persists the mapped values and ends it. An
    operator who then switches a mapped lane off is never overridden, because by then there
    is no ``mode`` left to migrate from.

    ``law`` and ``wiki`` map onto nothing to switch: the law lane has no off switch today
    (the OPEN_QUEUE entry on phantom ride-along settings), and the Wikipedia lane's run
    state is the operator's own, newer choice on the top-bar toggle -- overriding a
    "stopped" they pressed because an older setting implied "running" would be this
    migration deciding for them.
    """
    old = raw.get("mode")
    if not isinstance(old, str) or old not in _RETIRED_MODE_SENTENCES:
        return
    if old == "crawl":
        settings.crawl_supplement = True
        if settings.crawl_per_pass <= 0:
            settings.crawl_per_pass = SchedulerSettings().crawl_per_pass
    elif old == "markets":
        settings.auto_run_market_rules = True
        settings.auto_refresh_stat_subscriptions = True
    if not settings.retired_mode:
        settings.retired_mode = old
        if f"mode:{old}" not in _RETIRED_DISCLOSED:
            _RETIRED_DISCLOSED.add(f"mode:{old}")
            _LOG.warning(
                "retired scheduler mode %r migrated: %s", old, _RETIRED_MODE_SENTENCES[old]
            )


def retired_mode_disclosure(settings: SchedulerSettings | None = None) -> list[str]:
    """The sentence owed for this install's retired mode, or nothing.

    Read from the persisted ``retired_mode`` rather than from the raw blob, so it outlives
    the save that drops ``mode`` and ends only when the operator dismisses it.
    """
    s = settings if settings is not None else load_settings()
    sentence = _RETIRED_MODE_SENTENCES.get(s.retired_mode or "")
    return [sentence] if sentence else []


def retired_settings_disclosures() -> list[str]:
    """The disclosures a UI surface should show. Reads the stored file, never a cache, so
    a fresh import that carries the retired key is disclosed too."""
    raw = _read_raw()
    if not raw:
        return []
    return [
        sentence
        for key, sentence in _RETIRED_KEYS.items()
        if raw.get(key)
    ]


def load_settings() -> SchedulerSettings:
    """Load scheduler settings, falling back to safe defaults."""
    d = SchedulerSettings()
    raw = _read_raw()
    if raw is None:
        return d
    _disclose_retired(raw)
    rate_mode = raw.get("collect_rate_mode", d.collect_rate_mode)
    if rate_mode not in VALID_RATE_MODES:
        rate_mode = d.collect_rate_mode
    settings = SchedulerSettings(
        autostart=_coerce_bool(raw.get("autostart"), d.autostart),
        interval_minutes=_coerce_int(
            raw.get("interval_minutes"), d.interval_minutes, _MIN_INTERVAL, _MAX_INTERVAL
        ),
        continuous=_coerce_bool(raw.get("continuous"), d.continuous),
        collect_rate_mode=rate_mode,
        collect_target_kbps=_coerce_int(
            raw.get("collect_target_kbps"), d.collect_target_kbps, _MIN_TARGET_KBPS, _MAX_TARGET_KBPS
        ),
        collect_parallelism=_coerce_int(
            raw.get("collect_parallelism"), d.collect_parallelism, 1, _MAX_PARALLELISM
        ),
        # lo=0 allows the unbounded default; hi is a generous safety ceiling for
        # an explicit soft cap, never a selection imposed by us.
        max_sources_per_run=_coerce_int(
            raw.get("max_sources_per_run"), d.max_sources_per_run, 0, 1_000_000
        ),
        crawl_max_depth=_coerce_int(raw.get("crawl_max_depth"), d.crawl_max_depth, 0, 6),
        crawl_max_pages=_coerce_int(raw.get("crawl_max_pages"), d.crawl_max_pages, 1, 500),
        select_languages=_coerce_list(raw.get("select_languages")),
        select_tags=_coerce_list(raw.get("select_tags")),
        select_source_types=_coerce_list(raw.get("select_source_types")),
        export_dir=str(raw.get("export_dir") or "").strip(),
        discovery_per_run=_coerce_int(raw.get("discovery_per_run"), d.discovery_per_run, 0, 100),
        world_discovery_per_pass=_coerce_int(
            raw.get("world_discovery_per_pass"), d.world_discovery_per_pass, 0, 12
        ),
        qualification_per_pass=_coerce_int(
            raw.get("qualification_per_pass"), d.qualification_per_pass, 0, 100
        ),
        qualification_recheck_per_pass=_coerce_int(
            raw.get("qualification_recheck_per_pass"), d.qualification_recheck_per_pass, 0, 100
        ),
        scrape_app_provided_only=_coerce_bool(
            raw.get("scrape_app_provided_only"), d.scrape_app_provided_only
        ),
        language_equilibrium=_coerce_target(raw.get("language_equilibrium")),
        equilibrium_floor=_coerce_float(raw.get("equilibrium_floor"), d.equilibrium_floor, 0.0, 1.0),
        # Reuses _coerce_target: a {iso2: weight} map cleaned to {lowercased-key: float>0},
        # exactly the shape the priority ladder needs (empty = OFF).
        country_priority=_coerce_target(raw.get("country_priority")),
        auto_track_signals=_coerce_bool(raw.get("auto_track_signals"), d.auto_track_signals),
        wiki_lane_state=_coerce_wiki_lane_state(raw.get("wiki_lane_state"), d.wiki_lane_state),
        wiki_lane_editions=_coerce_wiki_lane_editions(
            raw.get("wiki_lane_editions"), d.wiki_lane_editions
        ),
        wiki_lane_budget_gb=_coerce_int(
            raw.get("wiki_lane_budget_gb"),
            d.wiki_lane_budget_gb,
            WIKI_LANE_BUDGET_GB_MIN,
            WIKI_LANE_BUDGET_GB_MAX,
        ),
        wiki_lane_wizard_done=_coerce_bool(
            raw.get("wiki_lane_wizard_done"), d.wiki_lane_wizard_done
        ),
        country_data_per_pass=_coerce_int(
            raw.get("country_data_per_pass"), d.country_data_per_pass, 0, 100
        ),
        crawl_supplement=_coerce_bool(raw.get("crawl_supplement"), d.crawl_supplement),
        crawl_per_pass=_coerce_int(raw.get("crawl_per_pass"), d.crawl_per_pass, 0, 100),
        archive_backfill_per_pass=_coerce_int(
            raw.get("archive_backfill_per_pass"), d.archive_backfill_per_pass, 0, 100
        ),
        auto_run_market_rules=_coerce_bool(
            raw.get("auto_run_market_rules"), d.auto_run_market_rules
        ),
        auto_refresh_stat_subscriptions=_coerce_bool(
            raw.get("auto_refresh_stat_subscriptions"), d.auto_refresh_stat_subscriptions
        ),
        retired_mode=_coerce_retired_mode(raw.get("retired_mode")),
    )
    _migrate_retired_mode(raw, settings)
    return settings


def _coerce_retired_mode(value) -> str:
    """Only a mode the disclosure table knows survives a load; anything else reads as none."""
    return value if isinstance(value, str) and value in _RETIRED_MODE_SENTENCES else ""


def save_settings(updates: dict) -> SchedulerSettings:
    """Apply a partial update and persist atomically. Validates before writing."""
    # A RETIRED key is REFUSED BY NAME, never accepted and dropped. Pydantic would drop an
    # undeclared field silently and this endpoint would answer 200 having changed nothing,
    # which tells a caller their scope decision took effect when it did not (the
    # 2026-09-16 `auto_track_signals` lesson). The refusal carries the ruling, so a caller
    # learns why rather than only that.
    for key in _RETIRED_KEYS:
        if key in updates and updates[key] is not None:
            raise SchedulerSettingsError(
                f"{key} has been retired and can no longer be set. {_RETIRED_KEYS[key]}"
            )
    current = load_settings()

    # ``mode`` is REFUSED BY NAME, like the retired keys above and for the same reason: a
    # caller still sending it would otherwise get a 200 that changed nothing.
    if "mode" in updates and updates["mode"] is not None:
        raise SchedulerSettingsError(
            "mode has been retired and can no longer be set (ruling Q1020, 2026-09-15). "
            "Feed collection runs on every pass and every other kind runs beside it as a "
            "lane; switch a lane with its own setting instead."
        )
    if "retired_mode" in updates and updates["retired_mode"] is not None:
        # The one value an operator may write is "" -- the Dismiss button. Anything else
        # would let a caller manufacture a disclosure for a migration that never ran.
        if str(updates["retired_mode"]) != "":
            raise SchedulerSettingsError(
                "retired_mode can only be cleared (set to an empty string)"
            )
        current.retired_mode = ""
    for key in ("auto_run_market_rules", "auto_refresh_stat_subscriptions"):
        if key in updates and updates[key] is not None:
            setattr(current, key, _coerce_bool(updates[key], getattr(current, key)))
    if "autostart" in updates and updates["autostart"] is not None:
        current.autostart = _coerce_bool(updates["autostart"], current.autostart)
    if "continuous" in updates and updates["continuous"] is not None:
        current.continuous = _coerce_bool(updates["continuous"], current.continuous)
    if "auto_track_signals" in updates and updates["auto_track_signals"] is not None:
        current.auto_track_signals = _coerce_bool(
            updates["auto_track_signals"], current.auto_track_signals
        )
    if "wiki_lane_state" in updates and updates["wiki_lane_state"] is not None:
        # REFUSES an unknown state rather than coercing it. A lane whose state fell
        # back to a default on a typo would be running when the operator asked it to
        # stop, which is the one direction this control must never fail in.
        current.wiki_lane_state = _require_wiki_lane_state(updates["wiki_lane_state"])
    if "wiki_lane_editions" in updates and updates["wiki_lane_editions"] is not None:
        current.wiki_lane_editions = _require_wiki_lane_editions(updates["wiki_lane_editions"])
    if "wiki_lane_budget_gb" in updates and updates["wiki_lane_budget_gb"] is not None:
        current.wiki_lane_budget_gb = _require_wiki_lane_budget_gb(updates["wiki_lane_budget_gb"])
    if "wiki_lane_wizard_done" in updates and updates["wiki_lane_wizard_done"] is not None:
        current.wiki_lane_wizard_done = _coerce_bool(
            updates["wiki_lane_wizard_done"], current.wiki_lane_wizard_done
        )
    if "crawl_supplement" in updates and updates["crawl_supplement"] is not None:
        current.crawl_supplement = _coerce_bool(
            updates["crawl_supplement"], current.crawl_supplement
        )
    if "scrape_app_provided_only" in updates and updates["scrape_app_provided_only"] is not None:
        current.scrape_app_provided_only = _coerce_bool(
            updates["scrape_app_provided_only"], current.scrape_app_provided_only
        )
    if "collect_rate_mode" in updates and updates["collect_rate_mode"] is not None:
        rm = str(updates["collect_rate_mode"])
        if rm not in VALID_RATE_MODES:
            raise SchedulerSettingsError(
                f"collect_rate_mode must be one of: {', '.join(VALID_RATE_MODES)}"
            )
        current.collect_rate_mode = rm

    def _ranged(key: str, lo: int, hi: int, label: str) -> None:
        if key in updates and updates[key] is not None:
            try:
                v = int(updates[key])
            except (TypeError, ValueError) as exc:
                raise SchedulerSettingsError(f"{label} must be an integer") from exc
            if not (lo <= v <= hi):
                raise SchedulerSettingsError(f"{label} must be between {lo} and {hi}")
            setattr(current, key, v)

    if "export_dir" in updates and updates["export_dir"] is not None:
        current.export_dir = str(updates["export_dir"]).strip()

    _ranged("discovery_per_run", 0, 100, "discovery_per_run")
    _ranged("world_discovery_per_pass", 0, 12, "world_discovery_per_pass")
    _ranged("qualification_per_pass", 0, 100, "qualification_per_pass")
    _ranged("qualification_recheck_per_pass", 0, 100, "qualification_recheck_per_pass")
    _ranged("country_data_per_pass", 0, 100, "country_data_per_pass")
    _ranged("crawl_per_pass", 0, 100, "crawl_per_pass")
    _ranged("archive_backfill_per_pass", 0, 100, "archive_backfill_per_pass")
    _ranged("collect_parallelism", 1, _MAX_PARALLELISM, "collect_parallelism")
    _ranged("collect_target_kbps", _MIN_TARGET_KBPS, _MAX_TARGET_KBPS, "collect_target_kbps")
    _ranged("interval_minutes", _MIN_INTERVAL, _MAX_INTERVAL, "interval_minutes")
    # Audit finding 2026-07-17: this was `1, 1000` -- but max_sources_per_run is
    # documented + tested (tests/test_no_source_cap.py) as "0 = UNBOUNDED (cover
    # every source) -- the default. Any cap silently SELECTS which sources to
    # skip, which cannot be justified (maintainer 2026-06-13)", and load_settings
    # (above) already coerces it with bounds (0, 1_000_000). The stale 1..1000
    # range here meant a client could never explicitly PUT {"max_sources_per_
    # run": 0} to reset the cap to unbounded, and could never set a cap above
    # 1000 either -- a real regression relative to the maintainer's own ruling.
    _ranged("max_sources_per_run", 0, 1_000_000, "max_sources_per_run")
    _ranged("crawl_max_depth", 0, 6, "crawl_max_depth")
    _ranged("crawl_max_pages", 1, 500, "crawl_max_pages")

    for key in ("select_languages", "select_tags", "select_source_types"):
        if key in updates:
            setattr(current, key, _coerce_list(updates[key]))

    if "language_equilibrium" in updates:
        # A dict target (or None/empty to turn the lever OFF). Malformed entries
        # are dropped by _coerce_target; an all-invalid target becomes {} = OFF.
        val = updates["language_equilibrium"]
        if val is not None and not isinstance(val, dict):
            raise SchedulerSettingsError(
                "language_equilibrium must be an object of {language: weight}"
            )
        current.language_equilibrium = _coerce_target(val)
    if "equilibrium_floor" in updates and updates["equilibrium_floor"] is not None:
        try:
            f = float(updates["equilibrium_floor"])
        except (TypeError, ValueError) as exc:
            raise SchedulerSettingsError("equilibrium_floor must be a number") from exc
        if not (0.0 <= f <= 1.0):
            raise SchedulerSettingsError("equilibrium_floor must be between 0 and 1")
        current.equilibrium_floor = f

    if "country_priority" in updates:
        # A {iso2: weight} map (or None/empty to turn the ladder OFF). Malformed entries
        # are dropped by _coerce_target; an all-invalid map becomes {} = OFF.
        val = updates["country_priority"]
        if val is not None and not isinstance(val, dict):
            raise SchedulerSettingsError(
                "country_priority must be an object of {country: weight}"
            )
        current.country_priority = _coerce_target(val)

    payload = {"version": SETTINGS_VERSION, **current.to_dict()}
    if not _use_kv():
        path = _settings_path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
        tmp.replace(path)
        return current
    from src.config.kv_store import kv_set_json

    kv_set_json(_KV_KEY, payload)
    return current
